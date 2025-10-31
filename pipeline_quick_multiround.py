#!/usr/bin/env python
"""
Multi-round quick pipeline for de novo drug discovery.

Streamlined workflow with the ability to run multiple rounds:
  1. Ligand Generation (using DiffSBDD or Pocket2Mol or CGFlow)
  2. Convert SDF to SMILES strings
  3. Run retrosynthesis (Synformer) on each compound
  4. Extract top N variants from retrosynthesis results
  5. Apply medchem filtering (generative design rules) to the variants
  6. Run ChemAP FDA-approval prediction filtering to the filtered variants
  7. Run Boltz-2 structure prediction to the filtered variants
  8. Redock filtered variants to the receptor
  9. Optionally iterate for multiple rounds.
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
import gc

# Get logger for this module
logger = logging.getLogger(__name__)

# Import functions from the utils modules
from utils.ligand_generation import run_ligand_generation, combine_pocket2mol_outputs
from utils.redocking import run_batch_compound_redocking
from utils.retrosynformer import run_retrosynthesis
from utils.medchem_filter import filter_by_generative_design, generate_filter_plots
from utils.boltz_filter import boltz_predict_variants
from utils.chemap_filter import chemap_filter_variants

# Import helper functions moved to dedicated utility modules
from utils.molecule_processing import extract_smiles_from_sdf, smiles_to_sdf, extract_best_pose_and_score
from utils.retro_utils import extract_variants_from_retrosynthesis, run_retrosynthesis_with_timeout
from utils.tracking import generate_tracking_report, update_tracking_report
from utils.logging_utils import setup_logging, ThreadSafeRotatingFileHandler

# Import the environment manager for conda environment handling
from utils.environment_manager import env_manager

# Import centralized GPU memory management
from utils.gpu_memory_manager import clear_gpu_memory, log_gpu_memory_usage, gpu_memory_manager

# Import DuckDB storage
from utils.duckdb_store import DuckDBStore

def main(out_dir, model_choice="diffsbdd", checkpoint=None, pdbfile=None, resi_list=None, 
         n_samples=200, sanitize=True, center=(114.817, 75.602, 82.416), box_size=(38, 70, 58),
         bbox_size=23.0, exhaustiveness="balance", top_n=5, num_rounds=1, 
         score_threshold=0.7, boltz_pocket_residues=None, stop_flag=None, cgflow_config=None,
         msa_path="/home/conrad_hku/Drug_pipeline/msa/NS5_full.a3m", job_name=None):
    """
    Multi-round quick pipeline main function with batch filtering optimization.
    
    Args:
        out_dir: Output directory for results
        model_choice: Model to use for molecule generation ('diffsbdd', 'pocket2mol', or 'cgflow')
        checkpoint: Path to model checkpoint (DiffSBDD or CGFlow)
        pdbfile: Path to target protein PDB file (used for both generation and docking)
        resi_list: Residue identifiers (DiffSBDD only)
        n_samples: Number of samples to generate
        sanitize: Whether to sanitize generated molecules (DiffSBDD only)
        center: Center coordinates (x, y, z) for docking box or Pocket2Mol
        box_size: Box dimensions (x, y, z) for docking 
        bbox_size: Single box size value for Pocket2Mol
        exhaustiveness: Docking exhaustiveness level ("fast", "balance", or "detail")
        top_n: Maximum number of variants to extract per compound after retrosynthesis
        num_rounds: Number of rounds to run
        score_threshold: Minimum retrosynthesis score threshold for variants (default: 0.7)
        boltz_pocket_residues: Comma-separated string of residue indices for Boltz-2 pocket constraints
        stop_flag: Dictionary containing status information for stopping the pipeline
        cgflow_config: Path to CGFlow YAML config (CGFlow only)
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
    required_envs = ["synformer", "boltz", "unidock", "unidocktools", "chemap"]  # Always needed for docking and ChemAP
    if model_choice.lower() == "diffsbdd":
        required_envs.append("diffsbdd")
    elif model_choice.lower() == "pocket2mol":
        required_envs.append("pocket2mol")
    elif model_choice.lower() == "cgflow":
        required_envs.append("cgflow")
    
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
    if model_choice not in ['diffsbdd', 'pocket2mol', 'cgflow']:
        logger.error(f"Invalid model choice: {model_choice}. Using default (diffsbdd).")
        model_choice = 'diffsbdd'
    
    # Log the model being used
    logger.info(f"Using {model_choice.upper()} model for molecule generation")
    # Validate CGFlow parameters when applicable
    if model_choice == 'cgflow':
        if not cgflow_config:
            error_msg = "CGFlow selected but 'cgflow_config' is missing."
            logger.error(error_msg)
            raise ValueError(error_msg)
        if not checkpoint:
            error_msg = "CGFlow selected but 'checkpoint' is missing."
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    # Log initial GPU memory usage
    if model_choice == 'pocket2mol':
        log_gpu_memory_usage()
    
    # Initialize DuckDB store for this run's tracking data
    duckdb_path = out_dir / "pipeline.duckdb"
    store = DuckDBStore(duckdb_path)
    store.init_schema()
    logger.info(f"Initialized DuckDB store at {duckdb_path}")
    
    # Initialize central jobs database in project root
    # Get project root (assuming pipeline_quick_multiround.py is in project root)
    project_root = Path(__file__).resolve().parent
    central_jobs_db_path = project_root / "jobs.duckdb"
    central_jobs_store = DuckDBStore(central_jobs_db_path)
    central_jobs_store.init_schema()
    logger.info(f"Initialized central jobs database at {central_jobs_db_path}")
    
    # Save job parameters to central jobs database
    import uuid
    job_id = str(uuid.uuid4())
    # Use job_name if provided, otherwise generate from output_dir
    if not job_name:
        job_name = Path(out_dir).name
    job_params = {
        "out_dir": str(out_dir),
        "model_choice": model_choice,
        "checkpoint": checkpoint,
        "pdbfile": pdbfile,
        "resi_list": resi_list,
        "n_samples": n_samples,
        "sanitize": sanitize,
        "center": center,
        "box_size": box_size,
        "bbox_size": bbox_size,
        "exhaustiveness": exhaustiveness,
        "top_n": top_n,
        "num_rounds": num_rounds,
        "score_threshold": score_threshold,
        "boltz_pocket_residues": boltz_pocket_residues,
        "cgflow_config": cgflow_config,
        "msa_path": msa_path,
        "job_name": job_name
    }
    central_jobs_store.create_job(job_id, str(out_dir), job_params, status="running", job_name=job_name)
    logger.info(f"Saved job parameters to central database with job_id: {job_id}, job_name: {job_name}")
    
    # Wrap main pipeline execution in try-except to handle failures
    try:
        # Create tracking report files (for CSV compatibility)
        master_dir = out_dir / "master_tracking"
        master_dir.mkdir(exist_ok=True)
        master_report = master_dir / "master_compound_tracking_report.csv"
        
        # Initialize master tracking DataFrame from DuckDB (with CSV fallback)
        try:
            master_df = store.get_all_tracking_data()
            if master_df.empty:
                master_df = pd.DataFrame(columns=['barcode', 'smiles',
                                                 'parent_id', 'status', 'source', 'timestamp'])
        except Exception as e:
            logger.warning(f"Could not read from DuckDB, falling back to CSV: {e}")
            # Fallback to CSV if DuckDB read fails
            if master_report.exists():
                master_df = pd.read_csv(master_report)
            else:
                master_df = pd.DataFrame(columns=['barcode', 'smiles',
                                                 'parent_id', 'status', 'source', 'timestamp'])
        
        # Loop through each round
        for round_num in range(1, num_rounds + 1):
            # Check if pipeline should stop
            if stop_flag and not stop_flag.get("running", True):
                logger.info("Pipeline stop requested. Stopping gracefully...")
                break
                
            logger.info(f"============= STARTING ROUND {round_num}/{num_rounds} =============")
            
            # Log GPU memory usage at start of round
            if model_choice == 'pocket2mol':
                log_gpu_memory_usage()
            
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
                
                # Clear GPU memory after Pocket2Mol execution
                logger.info(f"Round {round_num}: Clearing GPU memory after Pocket2Mol execution...")
                clear_gpu_memory()
                log_gpu_memory_usage()
                
                # Combine Pocket2Mol outputs into a single SDF file
                logger.info(f"Round {round_num}: Combining Pocket2Mol outputs into a single SDF file...")
                success = combine_pocket2mol_outputs(pocket2mol_output_dir, ligand_gen_out)
                
                if not success:
                    logger.error(f"Round {round_num}: Failed to combine Pocket2Mol outputs. Skipping this round.")
                    continue
            elif model_choice == 'cgflow':
                # CGFlow outputs directly to the provided directory with samples.smi and samples.sdf
                cgflow_output_dir = ligand_gen_dir / f"{base_name}_cgflow_output"
                cgflow_output_dir.mkdir(exist_ok=True)
                lg_thread = run_ligand_generation(
                    model="cgflow",
                    checkpoint=checkpoint,  # fine-tuned checkpoint
                    cgflow_config=cgflow_config,
                    out_dir=str(cgflow_output_dir),
                    n_samples=n_samples,
                    log_callback=logger.info,
                )
                lg_thread.join()

                # Prefer SDF if available; otherwise derive from SMILES
                samples_sdf = cgflow_output_dir / "samples.sdf"
                samples_smi = cgflow_output_dir / "samples.smi"
                if samples_sdf.exists() and samples_sdf.stat().st_size > 0:
                    ligand_gen_out = samples_sdf
                elif samples_smi.exists() and samples_smi.stat().st_size > 0:
                    # Convert SMILES to SDF of generated molecules for downstream consistency
                    from utils.molecule_processing import smiles_to_sdf_from_file
                    try:
                        smiles_to_sdf_from_file(str(samples_smi), str(ligand_gen_out))
                    except Exception as e:
                        logger.error(f"Failed to convert CGFlow samples.smi to SDF: {e}")
                else:
                    logger.error(f"CGFlow did not produce samples.sdf or samples.smi in {cgflow_output_dir}")
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
            
            # Sanitize compounds to ensure no DataFrame/Series values
            for compound in compounds:
                sanitized_compound = {}
                for key, value in compound.items():
                    if isinstance(value, pd.DataFrame):
                        sanitized_compound[key] = None
                    elif isinstance(value, pd.Series):
                        sanitized_compound[key] = value.iloc[0] if len(value) > 0 else None
                    elif isinstance(value, (list, tuple)) and len(value) > 0 and isinstance(value[0], (pd.DataFrame, pd.Series)):
                        # If it's a list/tuple containing DataFrames/Series, convert to None
                        sanitized_compound[key] = None
                    else:
                        sanitized_compound[key] = value
                # Ensure all values are basic types
                for key in sanitized_compound:
                    val = sanitized_compound[key]
                    if val is not None and not isinstance(val, (str, int, float, bool, type(None))):
                        try:
                            sanitized_compound[key] = str(val)
                        except Exception:
                            sanitized_compound[key] = None
                compound.clear()
                compound.update(sanitized_compound)
                
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
                update_tracking_report(round_report, compound, "compound", duckdb_store=store)
                update_tracking_report(master_report, compound, "compound", duckdb_store=store)
                
                # Run retrosynthesis
                smiles = compound["smiles"]
                logger.info(f"Round {round_num}: Running retrosynthesis {idx}/{total_compounds}: {compound_id}")
                
                retro_output = retro_dir / f"{compound_id}_retrosyn.csv"
                success = run_retrosynthesis_with_timeout(smiles, retro_output, timeout=300)
                
                if success:
                    variants = extract_variants_from_retrosynthesis(retro_output, top_n=top_n)
                    
                    # Add metadata to variants
                    for vidx, variant in enumerate(variants):
                        # Ensure all variant values are scalars before updating
                        sanitized_variant = {}
                        for key, value in variant.items():
                            if isinstance(value, pd.DataFrame):
                                sanitized_variant[key] = None
                            elif isinstance(value, pd.Series):
                                sanitized_variant[key] = value.iloc[0] if len(value) > 0 else None
                            elif isinstance(value, (list, tuple)) and len(value) > 0 and isinstance(value[0], (pd.DataFrame, pd.Series)):
                                # If it's a list/tuple containing DataFrames/Series, convert to None
                                sanitized_variant[key] = None
                            else:
                                sanitized_variant[key] = value
                        
                        # Ensure all values are basic types
                        for key in sanitized_variant:
                            val = sanitized_variant[key]
                            if val is not None and not isinstance(val, (str, int, float, bool, type(None))):
                                try:
                                    sanitized_variant[key] = str(val)
                                except Exception:
                                    sanitized_variant[key] = None
                        
                        variant_barcode = f"R{round_num}-{barcode}-V-{vidx+1:02d}"
                        sanitized_variant.update({
                            "source_compound": str(compound_id),
                            "source_smiles": str(smiles),
                            "barcode": str(variant_barcode),
                            "generation": str(round_num + 1),
                            "round": int(round_num),
                            "status": "SYNTHETIZED",
                            "source": "RETROSYNTHESIS"
                        })
                        all_variants.append(sanitized_variant)
                        
                        # Update tracking for variant generation
                        update_tracking_report(round_report, sanitized_variant, "variant", duckdb_store=store)
                        update_tracking_report(master_report, sanitized_variant, "variant", duckdb_store=store)
            
            # End of loop processing initial compounds and their variants

            # Step 4: Score-based filtering (pre-filter before MedChem)
            logger.info(f"\nRound {round_num}: Starting score-based filtering for {len(all_variants)} generated variants...")
            logger.info(f"Score threshold: >= {score_threshold}")
            
            if not all_variants: # Handle case where no variants were generated
                logger.warning(f"Round {round_num}: No variants generated from retrosynthesis. Skipping filtering and subsequent steps for this round.")
                continue # Skip to next round

            # Filter variants by score threshold
            score_filtered_variants = []
            for variant in all_variants:
                score = variant.get("score")
                if score is not None and score >= score_threshold:
                    score_filtered_variants.append(variant)
                    # Update status for variants that passed score filter
                    variant["status"] = "PASSSCORE"
                    update_tracking_report(round_report, variant, "variant_status_update", duckdb_store=store)
                    update_tracking_report(master_report, variant, "variant_status_update", duckdb_store=store)
                else:
                    # Update status for variants that failed score filter
                    variant["status"] = "FAILSCORE"
                    update_tracking_report(round_report, variant, "variant_status_update", duckdb_store=store)
                    update_tracking_report(master_report, variant, "variant_status_update", duckdb_store=store)

            logger.info(f"Round {round_num}: After score filtering (>= {score_threshold}), {len(score_filtered_variants)} variants remain")
            
            if not score_filtered_variants:
                logger.warning(f"Round {round_num}: No variants passed score filtering. Skipping MedChem filtering and subsequent steps for this round.")
                continue # Skip to next round

            # Step 5: Batch filtering of score-filtered variants using MedChem generative design rules
            logger.info(f"\nRound {round_num}: Starting MedChem filtering (generative design rules) for {len(score_filtered_variants)} variants...")
            filtered_variants, filter_results_df = filter_by_generative_design(
                input_variants=score_filtered_variants,
                smiles_key='smiles'
            )
            
            # Generate plots using the returned DataFrame
            plots_dir = filter_dir / "plots"
            generate_filter_plots(filter_results_df, plots_dir)
            
            # Now, continue using the filtered_variants list for subsequent steps
            if not filtered_variants:
                logger.warning(f"Round {round_num}: No variants passed MedChem filtering. Skipping docking for this round.")
                continue # Skip to next round

            logger.info(f"Round {round_num}: After MedChem filtering, {len(filtered_variants)} variants remain")

            # Update tracking for variants that passed MedChem filter
            for variant in filtered_variants:
                variant["status"] = "PASSFILTER"
                update_tracking_report(round_report, variant, "variant_status_update", duckdb_store=store)
                update_tracking_report(master_report, variant, "variant_status_update", duckdb_store=store)

            # ------------------------------------------------------------------
            # Step 6: ChemAP FDA-approval prediction filtering
            # ------------------------------------------------------------------
            logger.info(
                f"Round {round_num}: Running ChemAP FDA-approval predictions on {len(filtered_variants)} variants"
            )

            try:
                approved_variants, chemap_df = chemap_filter_variants(
                    variants=filtered_variants,
                    round_dir=round_dir,
                    log_callback=logger.info,
                )
            except Exception as e:
                logger.error(f"Round {round_num}: ChemAP step failed: {e}")
                approved_variants = []

            # Update tracking for ChemAP results
            approved_smiles_set = set()
            try:
                if 'SMILES' in chemap_df.columns and 'ChemAP_pred' in chemap_df.columns:
                    approved_smiles_set = set(chemap_df[chemap_df['ChemAP_pred'] == 1]['SMILES'].astype(str).tolist())
            except Exception:
                approved_smiles_set = set(v.get('smiles') for v in approved_variants)

            for variant in filtered_variants:
                if variant.get('smiles') in approved_smiles_set:
                    variant["status"] = "CHEMAPPASS"
                else:
                    variant["status"] = "CHEMAPFAIL"
                update_tracking_report(round_report, variant, "variant_status_update", duckdb_store=store)
                update_tracking_report(master_report, variant, "variant_status_update", duckdb_store=store)

            if not approved_variants:
                logger.warning(f"Round {round_num}: No variants approved by ChemAP. Skipping Boltz-2 and docking for this round.")
                continue

            filtered_variants = approved_variants

            # ------------------------------------------------------------------
            # Step 7: Boltz-2 predictions (no filtering)
            # ------------------------------------------------------------------
            logger.info(
                f"Round {round_num}: Running Boltz-2 predictions (no filtering) on {len(filtered_variants)} variants"
            )

            # Parse pocket residues if provided
            pocket_residues_list = None
            if boltz_pocket_residues and boltz_pocket_residues.strip():
                try:
                    pocket_residues_list = [int(x.strip()) for x in boltz_pocket_residues.split(',') if x.strip()]
                    logger.info(f"Round {round_num}: Using Boltz-2 pocket constraints for residues: {pocket_residues_list}")
                except ValueError as e:
                    logger.warning(f"Round {round_num}: Invalid pocket residues format '{boltz_pocket_residues}': {e}. Proceeding without constraints.")
                    pocket_residues_list = None

            # Ensure pdbfile is valid before calling boltz_filter_variants
            if pdbfile is None:
                logger.error(f"Round {round_num}: PDB file is None, cannot run Boltz-2 filter. Skipping this round.")
                continue
                
            filtered_variants = boltz_predict_variants(
                variants=filtered_variants,
                pdb_file=pdbfile,
                round_dir=round_dir,
                msa_path=msa_path,
                pocket_residues=pocket_residues_list,
                log_callback=logger.info,
                round_report=round_report,
                master_report=master_report,
            )

            # Update tracking for all variants processed by Boltz-2 (annotations only)
            for variant in filtered_variants:
                update_tracking_report(round_report, variant, "variant_status_update", duckdb_store=store)
                update_tracking_report(master_report, variant, "variant_status_update", duckdb_store=store)

            logger.info(
                f"Round {round_num}: Proceeding to batch docking with {len(filtered_variants)} variants (no Boltz filtering)"
            )

            # Save variants that passed both MedChem and Boltz-2 filters to SDF for reference
            filtered_sdf = filter_dir / f"round_{round_num}_filtered_variants.sdf"
            smiles_to_sdf(filtered_variants, filtered_sdf)

            # Check stop flag before batch filtering
            if stop_flag and not stop_flag.get("running", True):
                break
                
            # Step 7: Batch docking
            logger.info(f"Round {round_num}: Starting batch docking of {len(filtered_variants)} variants")
            
            # Prepare docking parameters (simplified for direct unidock command)
            center_x, center_y, center_z = center
            size_x, size_y, size_z = box_size
            redock_params = (
                center_x, center_y, center_z,
                size_x, size_y, size_z,
                exhaustiveness  # Use exhaustiveness level directly as search_mode
            )
            
            # Batch call: prepare protein once, ligandprep once, unidock once
            compounds_data = [{
                "compound_id": v["variant_id"],
                "smiles": v["smiles"],
            } for v in filtered_variants]

            batch_output_dir = dock_dir / "batch"
            batch_output_dir.mkdir(exist_ok=True)

            batch_results = run_batch_compound_redocking(
                compounds_data=compounds_data,
                receptor_pdb=Path(pdbfile),
                redock_params=redock_params,
                output_base_dir=batch_output_dir,
                batch_size=1200,
                save_temp_files=True,
                log_callback=logger.info
            )

            round_redock_results = []

            if isinstance(batch_results, dict) and "error" in batch_results:
                logger.error(f"Round {round_num}: Batch docking failed: {batch_results['error']}")
            else:
                # Update each variant with its docking results
                for variant in filtered_variants:
                    variant_id = variant["variant_id"]
                    barcode = variant["barcode"]
                    smiles = variant["smiles"]

                    variant_results = batch_results.get(variant_id)
                    if variant_results and isinstance(variant_results, dict) and "error" not in variant_results:
                        best_score = variant_results.get("docking_score")
                        pose_count = variant_results.get("pose_count", 1)
                        result_file = variant_results.get("result_file")
                        all_scores = variant_results.get("all_scores", [])

                        logger.info(f"Docking successful for {barcode}: score={best_score}, poses={pose_count}")
                        if all_scores and len(all_scores) > 1:
                            logger.info(f"All scores for {barcode}: {all_scores}")

                        variant.update({
                            "status": "DOCKED",
                            "docking_score": best_score,
                            "pose_count": pose_count,
                            "result_file": result_file,
                            "all_scores": all_scores,
                            "barcode": barcode
                        })

                        round_redock_results.append(variant)

                        update_tracking_report(round_report, variant, "docking", duckdb_store=store)
                        update_tracking_report(master_report, variant, "docking", duckdb_store=store)

                        variant_poses_dir = dock_dir / f"variant_{barcode}"
                        variant_poses_dir.mkdir(exist_ok=True)

                        unidock_scores_file = variant_poses_dir / "unidock_results.json"
                        try:
                            unidock_data = {
                                "variant_id": variant_id,
                                "barcode": barcode,
                                "smiles": smiles,
                                "docking_score": best_score,
                                "pose_count": pose_count,
                                "result_file": result_file,
                                "all_scores": all_scores,
                                "workflow_status": "success",
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

                        if result_file and Path(result_file).exists():
                            try:
                                dest_file = variant_poses_dir / Path(result_file).name
                                shutil.copy2(result_file, dest_file)
                                logger.info(f"Copied Unidock result file to {dest_file}")
                            except Exception as copy_e:
                                logger.warning(f"Could not copy Unidock result file for {barcode}: {copy_e}")
                    else:
                        logger.warning(f"Docking failed or no results for {barcode} (variant {variant_id}).")
                        variant["status"] = "DOCKFAIL"
                        update_tracking_report(round_report, {"barcode": barcode, "status": "DOCKFAIL"}, "variant_status_update", duckdb_store=store)
                        update_tracking_report(master_report, {"barcode": barcode, "status": "DOCKFAIL"}, "variant_status_update", duckdb_store=store)

            logger.info(f"Round {round_num}: Finished batch docking for {len(filtered_variants)} variants.")
            logger.info(f"Round {round_num}: Successfully docked and processed {len(round_redock_results)} variants.")

            # Clear GPU memory at the end of each round
            if model_choice == 'pocket2mol':
                logger.info(f"Round {round_num}: Clearing GPU memory at end of round...")
                clear_gpu_memory()
                log_gpu_memory_usage()

                logger.info(f"============= COMPLETED ROUND {round_num}/{num_rounds} =============")
            
            # Final GPU memory cleanup
            if model_choice == 'pocket2mol':
                logger.info("Final GPU memory cleanup...")
                clear_gpu_memory()
                log_gpu_memory_usage()
            
        # Update job status in central database - wrapped in try-except to handle any errors during status update
        try:
            project_root = Path(__file__).resolve().parent
            central_jobs_db_path = project_root / "jobs.duckdb"
            central_jobs_store = DuckDBStore(central_jobs_db_path)
            
            if stop_flag and not stop_flag.get("running", True):
                logger.info("Pipeline stopped by user request")
                central_jobs_store.update_job_status(job_id, "stopped")
            else:
                logger.info(f"Pipeline run finished. Total rounds attempted: {round_num-1}/{num_rounds}")
                central_jobs_store.update_job_status(job_id, "completed")
        except Exception as e:
            logger.error(f"Error updating job status in central database: {e}")
    
    except Exception as e:
        # Handle any unhandled exceptions during pipeline execution
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        try:
            project_root = Path(__file__).resolve().parent
            central_jobs_db_path = project_root / "jobs.duckdb"
            central_jobs_store = DuckDBStore(central_jobs_db_path)
            central_jobs_store.update_job_status(job_id, "failed")
        except Exception as status_error:
            logger.error(f"Failed to update job status to 'failed': {status_error}")
        raise  # Re-raise the original exception

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Quick pipeline for drug discovery")
    
    # Required parameters
    parser.add_argument("--out_dir", type=str, help="Output directory", required=True)

    # Model selection
    parser.add_argument("--model", type=str, choices=["diffsbdd", "pocket2mol", "cgflow"], default="diffsbdd",
                        help="Model to use for molecule generation (default: diffsbdd)")

    # DiffSBDD parameters
    parser.add_argument("--checkpoint", type=str, default="src/DiffSBDD/checkpoints/crossdocked_fullatom_cond.ckpt",
                        help="Path to the checkpoint file (DiffSBDD only)")
    # CGFlow parameters
    parser.add_argument("--cgflow_config", type=str, default="",
                        help="Path to CGFlow YAML config (CGFlow only)")
    parser.add_argument("--cgflow_checkpoint", type=str, default="",
                        help="Path to CGFlow checkpoint (.pt) (CGFlow only)")
    
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
                        help="Maximum number of variants to extract per compound after retrosynthesis")
    parser.add_argument("--num_rounds", type=int, default=1,
                        help="Number of rounds to run the pipeline")
    parser.add_argument("--score_threshold", type=float, default=0.7,
                        help="Minimum retrosynthesis score threshold for variants (default: 0.7)")
    parser.add_argument("--boltz_pocket_residues", type=str, default="",
                        help="Comma-separated residue indices for Boltz-2 pocket constraints (e.g., '156,158,202')")
    parser.add_argument("--job_name", type=str, default=None,
                        help="Optional name for this pipeline run")

    
    args = parser.parse_args()
    
    main(
        args.out_dir,
        model_choice=args.model,
        checkpoint=(args.cgflow_checkpoint if args.model == "cgflow" and args.cgflow_checkpoint else args.checkpoint),
        pdbfile=args.pdbfile,
        resi_list=args.resi_list,
        n_samples=args.n_samples,
        sanitize=args.sanitize,
        center=args.center,
        box_size=args.box_size,
        bbox_size=args.bbox_size,
        exhaustiveness=args.exhaustiveness,
        top_n=args.top_n,
        num_rounds=args.num_rounds,
        score_threshold=args.score_threshold,
        boltz_pocket_residues=args.boltz_pocket_residues,
        cgflow_config=args.cgflow_config if args.cgflow_config else None,
        job_name=args.job_name
    )