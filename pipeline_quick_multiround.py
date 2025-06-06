#!/usr/bin/env python
"""
Multi-round quick pipeline for de novo drug discovery.

Streamlined workflow with the ability to run multiple rounds:
  1. Ligand Generation (using DiffSBDD or Pocket2Mol)
  2. Convert SDF to SMILES strings
  3. Run retrosynthesis (Synformer) on each compound
  4. Extract top N variants from retrosynthesis results
  5. Apply medchem filtering to the variants
  6. Redock filtered variants to the receptor
  7. Optionally iterate for multiple rounds, using top compounds from previous rounds

The quick pipeline skips energy minimization, posebuster evaluation, 
and other intermediate steps to provide faster results. With the added
multi-round capability, the pipeline can iteratively improve compounds
over several generations.
"""

import os
import sys
import time
from pathlib import Path
import logging
import pandas as pd
import shutil
import tempfile
import multiprocessing
from multiprocessing import Process, Queue
from contextlib import contextmanager
import queue
import threading
import json
from datetime import datetime
from typing import List

# Get logger for this module
logger = logging.getLogger(__name__)

# Import functions from the utils modules
from utils.ligand_generation import run_ligand_generation, combine_pocket2mol_outputs
from utils.redocking import redock_compound
from utils.retrosynformer import run_retrosynthesis
from utils.medchem_filter import filter_by_pass_count, generate_filter_plots
from utils.boltz_filter import boltz_filter_variants

# Import helper functions moved to dedicated utility modules
from utils.molecule_processing import extract_smiles_from_sdf, smiles_to_sdf, extract_best_pose_and_score
from utils.retro_utils import extract_variants_from_retrosynthesis, run_retrosynthesis_with_timeout
from utils.tracking import generate_tracking_report, update_tracking_report
from utils.logging_utils import setup_logging, ThreadSafeRotatingFileHandler

# Import the environment manager for conda environment handling
from utils.environment_manager import env_manager

def main(out_dir, model_choice="diffsbdd", checkpoint=None, pdbfile=None, resi_list=None, 
         n_samples=200, sanitize=True, center=(114.817, 75.602, 82.416), box_size=(38, 70, 58),
         bbox_size=23.0, exhaustiveness="balance", top_n=5, max_variants=5, num_rounds=1, 
         stop_flag=None):
    """
    Multi-round quick pipeline main function with batch filtering optimization.
    
    Args:
        out_dir: Output directory for results
        model_choice: Model to use for molecule generation ('diffsbdd' or 'pocket2mol')
        checkpoint: Path to model checkpoint (DiffSBDD only)
        pdbfile: Path to target protein PDB file (used for both generation and docking)
        resi_list: Residue identifiers (DiffSBDD only)
        n_samples: Number of samples to generate
        sanitize: Whether to sanitize generated molecules (DiffSBDD only)
        center: Center coordinates (x, y, z) for docking box or Pocket2Mol
        box_size: Box dimensions (x, y, z) for docking 
        bbox_size: Single box size value for Pocket2Mol
        exhaustiveness: Docking exhaustiveness level ("fast", "balance", or "detail")
        top_n: Number of top compounds to process
        max_variants: Maximum number of variants per compound
        num_rounds: Number of rounds to run
        stop_flag: Dictionary containing status information for stopping the pipeline
    """
    # Set up output directories
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Use exhaustiveness level directly (no mapping needed for Unidock)
    logger.info(f"Using exhaustiveness level '{exhaustiveness}' for Unidock search mode")
    
    # Set up logging first
    setup_logging(out_dir)
    
    # Check conda environments availability
    logger.info("Checking conda environments availability...")
    env_status = env_manager.check_all_environments()
    
    # Check if required environments are available based on model choice
    required_envs = ["synformer", "boltz", "unidock", "unidocktools"]  # Always needed for docking
    if model_choice.lower() == "diffsbdd":
        required_envs.append("diffsbdd")
    elif model_choice.lower() == "pocket2mol":
        required_envs.append("pocket2mol")
    
    missing_envs = []
    for tool in required_envs:
        env_name = env_manager.get_environment_for_tool(tool)
        if not env_status.get(env_name, False):
            missing_envs.append(env_name)
    
    if missing_envs:
        error_msg = f"Required conda environments are not available: {missing_envs}. Please run './setup.sh' to create them."
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    logger.info("All required conda environments are available.")
    
    # Check model choice
    model_choice = model_choice.lower()
    if model_choice not in ['diffsbdd', 'pocket2mol']:
        logger.error(f"Invalid model choice: {model_choice}. Using default (diffsbdd).")
        model_choice = 'diffsbdd'
    
    # Log the model being used
    logger.info(f"Using {model_choice.upper()} model for molecule generation")
    
    # Create tracking report files
    master_dir = out_dir / "master_tracking"
    master_dir.mkdir(exist_ok=True)
    master_report = master_dir / "master_compound_tracking_report.csv"
    
    # Initialize master tracking DataFrame
    if master_report.exists():
        master_df = pd.read_csv(master_report)
    else:
        master_df = pd.DataFrame(columns=['compound_id', 'barcode', 'generation', 'round', 'smiles',
                                         'parent_id', 'status', 'source', 'timestamp'])
    
    # Loop through each round
    for round_num in range(1, num_rounds + 1):
        # Check if pipeline should stop
        if stop_flag and not stop_flag.get("running", True):
            logger.info("Pipeline stop requested. Stopping gracefully...")
            break
            
        logger.info(f"============= STARTING ROUND {round_num}/{num_rounds} =============")
        
        # Create round-specific directories
        round_dir = out_dir / f"round_{round_num}"
        round_dir.mkdir(exist_ok=True)
        round_report = round_dir / f"round_{round_num}_tracking_report.csv"
        
        ligand_gen_dir = round_dir / "ligand_generation"
        retro_dir = round_dir / "retrosyn_results"
        dock_dir = round_dir / "docking_results"
        filter_dir = round_dir / "filter_results"
        
        for dir_path in [ligand_gen_dir, retro_dir, dock_dir, filter_dir]:
            dir_path.mkdir(exist_ok=True)
        
        # Step 1: Ligand Generation
        logger.info(f"Round {round_num}: Running ligand generation with {model_choice}...")
        base_name = f"round_{round_num}"
        ligand_gen_out = ligand_gen_dir / f"{base_name}_mols_gen.sdf"
        
        # Check stop flag before starting ligand generation
        if stop_flag and not stop_flag.get("running", True):
            break
            
        if model_choice == 'pocket2mol':
            # Create specific directory for Pocket2Mol outputs
            pocket2mol_output_dir = ligand_gen_dir / f"{base_name}_pocket2mol_output"
            pocket2mol_output_dir.mkdir(exist_ok=True)
            
            # Run Pocket2Mol
            lg_thread = run_ligand_generation(
                model="pocket2mol",
                pdbfile=pdbfile,
                center=center,
                bbox_size=bbox_size,
                out_dir=str(pocket2mol_output_dir),
                n_samples=n_samples,
                log_callback=logger.info
            )
            lg_thread.join()
            
            # Combine Pocket2Mol outputs into a single SDF file
            logger.info(f"Round {round_num}: Combining Pocket2Mol outputs into a single SDF file...")
            success = combine_pocket2mol_outputs(pocket2mol_output_dir, ligand_gen_out)
            
            if not success:
                logger.error(f"Round {round_num}: Failed to combine Pocket2Mol outputs. Skipping this round.")
                continue
        else:
            # Run DiffSBDD
            lg_thread = run_ligand_generation(
                model="diffsbdd",
                checkpoint=checkpoint,
                pdbfile=pdbfile,
                outfile=str(ligand_gen_out),
                resi_list=resi_list.split() if isinstance(resi_list, str) else resi_list,
                n_samples=n_samples,
                sanitize=sanitize,
                log_callback=logger.info
            )
            lg_thread.join()
        
        # Check stop flag after ligand generation
        if stop_flag and not stop_flag.get("running", True):
            break
        
        # Check if output file exists and is not empty
        if not ligand_gen_out.exists() or ligand_gen_out.stat().st_size == 0:
            logger.error(f"Round {round_num}: No molecules generated. Skipping this round.")
            continue
            
        # Step 2: Process compounds
        compounds = extract_smiles_from_sdf(ligand_gen_out)
        if not compounds:
            logger.error(f"Round {round_num}: No valid compounds generated. Skipping this round.")
            continue
            
        # Collect all variants for batch processing
        all_variants = []
        total_compounds = len(compounds)
        
        # Step 3: Sequential retrosynthesis
        for idx, compound in enumerate(compounds, 1):
            # Check stop flag before each compound
            if stop_flag and not stop_flag.get("running", True):
                break
                
            # Add tracking information
            compound_id = compound["compound_id"]
            barcode = f"R{round_num}-GEN-{idx:04d}"
            compound.update({
                "barcode": barcode,
                "generation": str(round_num),
                "round": round_num,
                "status": "GENERATED",
                "source": "AI_GENERATION",
                "parent_id": "NONE"
            })
            
            # Update tracking reports
            update_tracking_report(round_report, compound, "compound")
            update_tracking_report(master_report, compound, "compound")
            
            # Run retrosynthesis
            smiles = compound["smiles"]
            logger.info(f"Round {round_num}: Running retrosynthesis {idx}/{total_compounds}: {compound_id}")
            
            retro_output = retro_dir / f"{compound_id}_retrosyn.csv"
            success = run_retrosynthesis_with_timeout(smiles, retro_output, timeout=300)
            
            if success:
                variants = extract_variants_from_retrosynthesis(retro_output, max_variants=max_variants)
                
                # Add metadata to variants
                for vidx, variant in enumerate(variants):
                    variant_barcode = f"R{round_num}-{barcode}-V-{vidx+1:02d}"
                    variant.update({
                        "source_compound": compound_id,
                        "source_smiles": smiles,
                        "barcode": variant_barcode,
                        "generation": str(round_num + 1),
                        "round": round_num,
                        "status": "SYNTHETIZED",
                        "source": "RETROSYNTHESIS"
                    })
                    all_variants.append(variant)
                    
                    # Update tracking for variant generation
                    update_tracking_report(round_report, variant, "variant")
                    update_tracking_report(master_report, variant, "variant")
        
        # End of loop processing initial compounds and their variants

        # Step 4: Batch filtering of all variants using pass-count method
        logger.info(f"\nRound {round_num}: Starting MedChem filtering (pass-count) for {len(all_variants)} generated variants...")
        # Define thresholds (could be made arguments later)
        rule_threshold = 13
        struct_threshold = 27
        if not all_variants: # Handle case where no variants were generated
             logger.warning(f"Round {round_num}: No variants generated from retrosynthesis. Skipping filtering and subsequent steps for this round.")
             continue # Skip to next round

        # Call filter_by_pass_count and capture both return values
        filtered_variants, filter_results_df = filter_by_pass_count(
            input_variants=all_variants,
            rule_threshold=rule_threshold,
            structural_threshold=struct_threshold,
            smiles_key='smiles' # Ensure this matches the key used in variant dictionaries
        )
        
        # Generate plots using the returned DataFrame
        plots_dir = filter_dir / "plots"
        generate_filter_plots(filter_results_df, plots_dir)
        
        # Now, continue using the filtered_variants list for subsequent steps
        if not filtered_variants:
            logger.warning(f"Round {round_num}: No variants passed MedChem filtering. Skipping docking and decoy generation for this round.")
            continue # Skip to next round

        logger.info(f"Round {round_num}: After MedChem filtering, {len(filtered_variants)} variants remain")

        # Update tracking for variants that passed MedChem filter
        for variant in filtered_variants:
            variant["status"] = "PASSFILTER"
            update_tracking_report(round_report, variant, "variant_status_update")
            update_tracking_report(master_report, variant, "variant_status_update")

        # ------------------------------------------------------------------
        # Step 5: Boltz-1x blind-docking filter
        # ------------------------------------------------------------------
        logger.info(
            f"Round {round_num}: Running Boltz-1x blind-docking filter on {len(filtered_variants)} variants"
        )

        passed_variants, failed_variants = boltz_filter_variants(
            variants=filtered_variants,
            pdb_file=pdbfile,
            round_dir=round_dir,
            center=center,
            box_size=box_size,
            log_callback=logger.info,
        )

        # Update tracking for all variants processed by Boltz-1x
        for variant in (passed_variants + failed_variants):
            update_tracking_report(round_report, variant, "variant_status_update")
            update_tracking_report(master_report, variant, "variant_status_update")

        if not passed_variants:
            logger.warning(
                f"Round {round_num}: No variants passed Boltz-1x blind-docking filter. Skipping docking for this round."
            )
            continue  # Proceed to next round directly

        # Replace filtered_variants with the subset that passed Boltz-1x for docking
        filtered_variants = passed_variants

        logger.info(
            f"Round {round_num}: After Boltz-1x filter, {len(filtered_variants)} variants remain for docking"
        )

        # Save variants that passed both MedChem and Boltz-1x filters to SDF for reference
        filtered_sdf = filter_dir / f"round_{round_num}_filtered_variants.sdf"
        smiles_to_sdf(filtered_variants, filtered_sdf)

        # Check stop flag before batch filtering
        if stop_flag and not stop_flag.get("running", True):
            break
            
        # Step 6: Sequential docking
        logger.info(f"Round {round_num}: Starting docking of {len(filtered_variants)} filtered variants")
        
        # Prepare docking parameters (simplified for direct unidock command)
        center_x, center_y, center_z = center
        size_x, size_y, size_z = box_size
        redock_params = (
            center_x, center_y, center_z,
            size_x, size_y, size_z,
            exhaustiveness  # Use exhaustiveness level directly as search_mode
        )
        
        # Create a directory for each variant's docking results
        round_redock_results = []
        docking_threads = {} # To keep track if needed, though we join immediately now

        for idx, variant in enumerate(filtered_variants, 1):
            # Check stop flag before each docking
            if stop_flag and not stop_flag.get("running", True):
                break

            variant_id = variant["variant_id"]
            smiles = variant["smiles"]
            barcode = variant["barcode"]

            logger.info(f"Round {round_num}: Initiating docking variant {idx}/{len(filtered_variants)}: {variant_id} ({barcode})")

            # Run docking using the new asynchronous function
            # We'll wait for it immediately to maintain sequential flow for now
            docking_thread, result_storage = redock_compound(
                variant_id,
                smiles,
                redock_params,
                receptor=pdbfile,  # Use the same PDB file as receptor
                log_callback=logger.info
            )

            # Check if thread started successfully
            if docking_thread:
                logger.info(f"Waiting for docking thread for {barcode} to complete...")
                docking_thread.join() # Wait for the subprocess to finish
                logger.info(f"Docking thread for {barcode} finished.")

                # Check results from the storage dictionary
                status = result_storage.get("status", "unknown")
                data = result_storage.get("data", {})
                error_msg = data.get("error")

                if status == "success" and not error_msg:
                    # Check if we have docking results for this variant
                    variant_results = data.get(variant_id)
                    if variant_results:
                        # Extract docking information from Unidock results
                        best_score = variant_results.get("docking_score")
                        pose_count = variant_results.get("pose_count", 1)
                        result_file = variant_results.get("result_file")
                        all_scores = variant_results.get("all_scores", [])

                        # Log detailed docking results
                        logger.info(f"Docking successful for {barcode}: score={best_score}, poses={pose_count}")
                        if all_scores and len(all_scores) > 1:
                            logger.info(f"All scores for {barcode}: {all_scores}")

                        # Update variant with docking results
                        variant.update({
                            "status": "DOCKED",
                            "docking_score": best_score,
                            "pose_count": pose_count,
                            "result_file": result_file,
                            "all_scores": all_scores,
                            "barcode": barcode  # Ensure barcode is included for tracking
                        })

                        round_redock_results.append(variant)

                        # Update tracking with docking results
                        update_tracking_report(round_report, variant, "docking")
                        update_tracking_report(master_report, variant, "docking")

                        # Save docking outputs
                        variant_poses_dir = dock_dir / f"variant_{barcode}"
                        variant_poses_dir.mkdir(exist_ok=True)

                        # Save comprehensive Unidock results summary to JSON
                        unidock_scores_file = variant_poses_dir / "unidock_results.json"
                        try:
                            # Save the complete data extracted from result_storage
                            unidock_data = {
                                "variant_id": variant_id,
                                "barcode": barcode,
                                "smiles": smiles,
                                "docking_score": best_score,
                                "pose_count": pose_count,
                                "result_file": result_file,
                                "all_scores": all_scores,
                                "workflow_status": status,
                                "docking_parameters": {
                                    "center": center,
                                    "box_size": box_size,
                                    "search_mode": exhaustiveness,
                                    "receptor": str(pdbfile)
                                },
                                "timestamp": datetime.now().isoformat()
                            }
                            with open(unidock_scores_file, 'w') as f:
                                json.dump(unidock_data, f, indent=4)
                            logger.info(f"Saved comprehensive Unidock results to {unidock_scores_file}")
                        except Exception as e:
                            logger.error(f"Error saving Unidock results for {variant_id} ({barcode}): {e}")

                        # Copy Unidock result files if they exist
                        if result_file and Path(result_file).exists():
                            try:
                                dest_file = variant_poses_dir / Path(result_file).name
                                shutil.copy2(result_file, dest_file)
                                logger.info(f"Copied Unidock result file to {dest_file}")
                            except Exception as copy_e:
                                logger.warning(f"Could not copy Unidock result file for {barcode}: {copy_e}")

                    else:
                        logger.warning(f"Docking for {barcode} completed successfully but no results found for variant {variant_id}.")
                        # Update status to indicate docking attempt but failure to get results
                        variant["status"] = "DOCKFAIL_NORESULTS"
                        update_tracking_report(round_report, {"barcode": barcode, "status": "DOCKFAIL_NORESULTS"}, "variant_status_update")
                        update_tracking_report(master_report, {"barcode": barcode, "status": "DOCKFAIL_NORESULTS"}, "variant_status_update")

                else:
                    # Log error from result_storage or generic failure
                    log_message = f"Docking failed for {barcode}. Status: {status}."
                    if error_msg:
                        log_message += f" Error: {error_msg}"
                    logger.error(log_message)
                    # Update status to indicate docking failure
                    variant["status"] = "DOCKFAIL"
                    update_tracking_report(round_report, {"barcode": barcode, "status": "DOCKFAIL"}, "variant_status_update")
                    update_tracking_report(master_report, {"barcode": barcode, "status": "DOCKFAIL"}, "variant_status_update")

            else:
                # Thread creation failed (e.g., initial setup error in redock_compound)
                logger.error(f"Could not start docking thread for {barcode}. Check previous logs for setup errors.")
                status = result_storage.get("status", "error")
                error_msg = result_storage.get("data", {}).get("error", "Setup failed before thread start.")
                logger.error(f"Setup Error: {error_msg}")
                # Update status to indicate setup failure
                variant["status"] = "DOCKFAIL_SETUP"
                update_tracking_report(round_report, {"barcode": barcode, "status": "DOCKFAIL_SETUP"}, "variant_status_update")
                update_tracking_report(master_report, {"barcode": barcode, "status": "DOCKFAIL_SETUP"}, "variant_status_update")

        logger.info(f"Round {round_num}: Finished processing docking for {len(filtered_variants)} variants.")
        logger.info(f"Round {round_num}: Successfully docked and processed {len(round_redock_results)} variants.")

        logger.info(f"============= COMPLETED ROUND {round_num}/{num_rounds} =============")
    
    if stop_flag and not stop_flag.get("running", True):
        logger.info("Pipeline stopped by user request")
    else:
        logger.info(f"Pipeline run finished. Total rounds attempted: {round_num-1}/{num_rounds}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Quick pipeline for drug discovery")
    
    # Required parameters
    parser.add_argument("--out_dir", type=str, help="Output directory", required=True)

    # Model selection
    parser.add_argument("--model", type=str, choices=["diffsbdd", "pocket2mol"], default="diffsbdd",
                        help="Model to use for molecule generation (default: diffsbdd)")

    # DiffSBDD parameters
    parser.add_argument("--checkpoint", type=str, default="src/DiffSBDD/checkpoints/crossdocked_fullatom_cond.ckpt",
                        help="Path to the checkpoint file (DiffSBDD only)")
    
    parser.add_argument("--pdbfile", type=str, default="input/NS5.pdb",
                        help="Path to target protein PDB file")
    
    parser.add_argument("--resi_list", type=str, default="A:719 A:770 A:841 A:856 A:887 A:888",
                        help="Residue identifiers (space-separated) (DiffSBDD only)")
    
    # Pocket2Mol parameters
    parser.add_argument("--bbox_size", type=float, default=23.0,
                        help="Size of the bounding box (Pocket2Mol only)")
    
    # Common parameters
    parser.add_argument("--n_samples", type=int, default=200, help="Number of samples to generate")
    parser.add_argument("--sanitize", action="store_true", help="Sanitize generated molecules (DiffSBDD only)", default=True)
    parser.add_argument("--center", nargs=3, type=float, default=[114.817, 75.602, 82.416], 
                        help="Docking box center coordinates (also used for Pocket2Mol)")
    parser.add_argument("--box_size", nargs=3, type=int, default=[38, 70, 58],
                        help="Docking box dimensions")
    parser.add_argument("--exhaustiveness", type=str, choices=["fast", "balance", "detail"], default="balance",
                        help="Docking exhaustiveness level")
    parser.add_argument("--top_n", type=int, default=5, 
                        help="Number of top compounds to process")
    parser.add_argument("--max_variants", type=int, default=5,
                        help="Maximum number of variants per compound")
    parser.add_argument("--num_rounds", type=int, default=1,
                        help="Number of rounds to run the pipeline")

    
    args = parser.parse_args()
    
    main(
        args.out_dir,
        model_choice=args.model,
        checkpoint=args.checkpoint,
        pdbfile=args.pdbfile,
        resi_list=args.resi_list,
        n_samples=args.n_samples,
        sanitize=args.sanitize,
        center=args.center,
        box_size=args.box_size,
        bbox_size=args.bbox_size,
        exhaustiveness=args.exhaustiveness,
        top_n=args.top_n,
        max_variants=args.max_variants,
        num_rounds=args.num_rounds
    )