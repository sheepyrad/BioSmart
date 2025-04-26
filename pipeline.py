#!/usr/bin/env python
"""
Final pipeline.py for de novo drug discovery.

Workflow:
  1. Ligand Generation
  2. Energy Minimization (multiple-ligand mode only)
  3. Pose Evaluation (concatenation + PoseBuster filtering)
  4. [Optional] MedChem Generative Filtering for redocking
  5. Redocking

Default parameters are set based on screen_test.ipynb but can be overridden.
The only required input is the output directory (--out_dir). All results will be stored in subdirectories.
Note: redocking.py uses a temporary sys.path context so that run_vf_unity can be imported from the VFU folder.
"""

import os
import sys
import time
from pathlib import Path
import logging
import pandas as pd
import shutil
from rdkit import Chem


logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("project.log", mode="w")
    ]
)

logger = logging.getLogger(__name__)
logger.info("Starting pipeline...")

# Import functions from the utils modules
from utils.ligand_generation import run_ligand_generation
from utils.energy_minimization_module import split_sdf_file, optimize_ligand, concatenate_sdf_files_sorted
from utils.pose_evaluation import run_posebuster, extract_valid_ligands
from utils.redocking import redock_compound, vfu_dir
from utils.medchem_filter import filter_by_pass_count
from utils.dock_synformer_compounds import dock_synformer_compounds

def main(out_dir, rounds, checkpoint, pdbfile, resi_list, n_samples, sanitize,
         protein_file, base_name, prep_only, program_choice, scoring_function,
         center, box_size, exhaustiveness, is_selfies, is_peptide, receptor, apply_filters,
         retro_top_n):
    
    # Set up output directories.
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ligand_gen_dir = out_dir / "ligand_generation"
    ligand_gen_dir.mkdir(exist_ok=True)
    minim_dir = out_dir / "minimized_ligands"
    minim_dir.mkdir(exist_ok=True)
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(exist_ok=True)
    redock_dir = out_dir / "redocking_results"
    redock_dir.mkdir(exist_ok=True)
    
    # Create additional output directories
    posebuster_dir = out_dir / "posebuster_results"
    posebuster_dir.mkdir(exist_ok=True)
    medchem_dir = out_dir / "medchem_results"
    medchem_dir.mkdir(exist_ok=True)
    retro_dir = out_dir / "retrosyn_results"
    retro_dir.mkdir(exist_ok=True)
    
    # Process each round.
    for round_no in range(rounds):
        logger.info(f"=== Starting Round {round_no+1} ===")
        
        # Define filenames for this round.
        ligand_gen_out = ligand_gen_dir / f"{base_name}_round{round_no+1}_mols_gen.sdf"
        # Save concatenated files in a dedicated directory
        concat_sdf = minim_dir / f"concatenated_ligands_round{round_no+1}.sdf"  # Changed from out_dir
        # Save posebuster pass files in the posebuster directory
        valid_sdf = posebuster_dir / f"round_{round_no+1}" / f"posebuster_pass_round{round_no+1}.sdf"  # Changed from out_dir
        
        # Step 1: Ligand Generation
        logger.info("Running ligand generation...")
        lg_thread = run_ligand_generation(
            checkpoint=checkpoint,
            pdbfile=pdbfile,
            outfile=str(ligand_gen_out),
            resi_list=resi_list.split(),
            n_samples=n_samples,
            sanitize=sanitize,
            log_callback=logger.info
        )
        lg_thread.join()
        logger.info(f"Ligand generation complete. Output: {ligand_gen_out}")

        # Step 2: Energy Minimization
        logger.info("Running energy minimization (multiple-ligand mode)...")
        protein_file_path = Path(protein_file)
        split_dir = cache_dir / f"{base_name}_split_ligands"
        split_dir.mkdir(exist_ok=True)
        logger.info(f"Splitting ligand file {ligand_gen_out} into individual molecules...")
        ligand_files = split_sdf_file(ligand_gen_out, split_dir, base_name)
        if not ligand_files:
            logger.warning("No valid ligands found after splitting. Aborting round.")
            continue

        for idx, single_ligand in enumerate(ligand_files):
            out_file = minim_dir / f"{base_name}_round_{round_no+1}_ligand_{idx}_minimized.sdf"
            try:
                optimize_ligand(
                    protein_file=protein_file_path,
                    ligand_file=single_ligand,
                    output_file=out_file,
                    cache_dir=cache_dir,
                    prep_only=prep_only,
                    name=f"{base_name}_round_{round_no+1}_ligand_{idx}",
                    platform_name="fastest",
                    add_solvent=False
                )
                logger.info(f"Ligand {idx} minimized. Saved to: {out_file}")
            except Exception as e:
                logger.error(f"Error minimizing ligand {idx}: {e}")

        # Step 3: Pose Evaluation
        logger.info("Running PoseBuster evaluation...")
        concatenate_sdf_files_sorted(str(minim_dir), str(concat_sdf))
        logger.info(f"Concatenated SDF file saved: {concat_sdf}")
        df_posebuster = run_posebuster(concat_sdf, config="mol", output_folder=posebuster_dir / f"round_{round_no+1}")
        valid_sdf, valid_count = extract_valid_ligands(df_posebuster, minim_dir, valid_sdf)
        logger.info(f"Extracted {valid_count} valid molecules to: {valid_sdf}")

        # Step 4: Optional Generative Filtering
        if apply_filters:
            logger.info("Selecting compounds that pass medchem filtering for redocking...")
            try:
                # Convert valid SDFs to a list of dictionaries with SMILES
                valid_compounds = []
                supplier = Chem.SDMolSupplier(str(valid_sdf))
                for idx, mol in enumerate(supplier):
                    if mol is not None:
                        compound_id = mol.GetProp("_Name") if mol.HasProp("_Name") else f"compound_{idx+1}"
                        smiles = Chem.MolToSmiles(mol)
                        valid_compounds.append({"compound_id": compound_id, "smiles": smiles})
                
                # Apply pass-count filtering
                filtered_compounds = filter_by_pass_count(
                    input_variants=valid_compounds,
                    rule_threshold=13,  # Default thresholds, adjust as needed
                    structural_threshold=27
                )
                
                if not filtered_compounds:
                    logger.warning("No compounds passed the medchem filtering for redocking.")
                    logger.info("Falling back to using all valid compounds without filtering...")
                    # Fall back to using all valid compounds
                    df_for_redock = None
                else:
                    # Convert to DataFrame for backward compatibility
                    df_for_redock = pd.DataFrame(filtered_compounds)
                    logger.info(f"After medchem filtering, {len(df_for_redock)} compounds remain for redocking.")
            except OSError as e:
                if "Too many open files" in str(e):
                    logger.error(f"Medchem filtering failed due to file descriptor limits: {e}")
                    logger.info("Falling back to using all valid compounds without filtering...")
                    df_for_redock = None
                else:
                    logger.error(f"Medchem filtering failed with OSError: {e}")
                    if round_no == rounds - 1:
                        logger.info("This is the final round. Exiting pipeline.")
                        sys.exit(1)
                    else:
                        logger.info("Skipping redocking for this round.")
                        continue
            except Exception as e:
                logger.error(f"Medchem filtering failed: {e}")
                logger.info("Falling back to using all valid compounds without filtering...")
                df_for_redock = None
        else:
            df_for_redock = None  # When filtering is off, we use all compounds later.

        # Step 5: Redocking
        logger.info("Running redocking...")
        center_x, center_y, center_z = center
        size_x, size_y, size_z = box_size
        redock_params = (
            program_choice,
            scoring_function,
            center_x, center_y, center_z,
            size_x, size_y, size_z,
            exhaustiveness,
            is_selfies,
            is_peptide
        )

        # Gather compounds (from filtering or from minimized_ligands)
        if apply_filters:
            compounds_df = df_for_redock
        else:
            # More strictly match only the current round's ligands
            # The pattern ensures we get only ligands generated in THIS round
            pattern = f"{base_name}_round_{round_no+1}_ligand_*_minimized.sdf"
            logger.info(f"Looking for compounds with pattern: {pattern}")
            
            compound_files = sorted(list(minim_dir.glob(pattern)))
            logger.info(f"Found {len(compound_files)} compound files for round {round_no+1}")
            
            compounds = []
            for f in compound_files:
                supplier = Chem.SDMolSupplier(str(f))
                if supplier and supplier[0] is not None:
                    mol = supplier[0]
                    # Get proper compound ID from the file stem instead of relying on properties
                    # which might be inconsistent
                    compound_id = f.stem.replace("_minimized", "")
                    smiles = Chem.MolToSmiles(mol)
                    compounds.append({"compound_id": compound_id, "smiles": smiles})
            
            compounds_df = pd.DataFrame(compounds)
            logger.info(f"Prepared {len(compounds_df)} compounds for redocking in round {round_no+1}")

        if compounds_df.empty:
            logger.warning("No compounds found for redocking in this round.")
        else:
            redock_results = []
            # Create a round-specific directory to store all poses for this round
            round_poses_dir = redock_dir / f"poses_round_{round_no+1}"
            round_poses_dir.mkdir(exist_ok=True)
            
            for index, comp in compounds_df.iterrows():
                cid = comp["compound_id"]
                smi = comp["smiles"]
                logger.info(f"Redocking compound {cid} with SMILES: {smi}")
                pose_out, rescored = redock_compound(
                    cid,
                    smi,
                    redock_params,
                    receptor=receptor,
                    log_callback=logger.info
                )
                redock_results.append({
                    "compound_id": cid,
                    "smiles": smi,
                    "pose_pred_out": pose_out,
                    "re_scored_values": rescored
                })
                
                # Copy the poses for this compound right after redocking
                vfu_outputs_dir = Path(vfu_dir) / "outputs"
                compound_poses_dir = round_poses_dir / f"compound_{cid}_{round_no+1}"
                compound_poses_dir.mkdir(exist_ok=True)
                
                # Copy all files from VFU outputs to the compound-specific directory
                for file_path in vfu_outputs_dir.glob("*"):
                    if file_path.is_file():
                        shutil.copy2(file_path, compound_poses_dir)
                    elif file_path.is_dir():
                        dest_dir = compound_poses_dir / file_path.name
                        if dest_dir.exists():
                            shutil.rmtree(dest_dir)
                        shutil.copytree(file_path, dest_dir)
                
                logger.info(f"Copied poses for compound {cid} to {compound_poses_dir}")
                
            if redock_results:
                results_df = pd.DataFrame(redock_results)
                results_csv = redock_dir / f"redocking_results_round_{round_no+1}.csv"
                results_df.to_csv(results_csv, index=False)
                logger.info(f"Redocking results (CSV) saved to: {results_csv}")
                
                # Run retrosynthesis on top compounds
                from retrosynformer import process_redocking_results
                logger.info(f"Running retrosynthesis on top {retro_top_n} compounds...")
                retro_result_dir = process_redocking_results(redock_dir, round_no, top_n=retro_top_n, retro_dir=retro_dir)
                if retro_result_dir:
                    logger.info(f"Retrosynthesis results saved to {retro_result_dir}")
                    
                    # Now dock the top synthetic products from Synformer results
                    # The improved dock_synformer_compounds function will dock up to 5 synthetic products 
                    # from each of the top compounds, using the 'smiles' column in the retrosynthesis results
                    logger.info(f"Redocking synthetic products from top {retro_top_n} compounds from Synformer results...")
                    synformer_dock_dir = dock_synformer_compounds(
                        retro_dir=retro_dir,
                        round_no=round_no,
                        receptor=receptor,
                        out_dir=out_dir / "redock_synformer_top5",
                        top_n=retro_top_n,
                        program_choice=program_choice,
                        scoring_function=scoring_function,
                        center=center,
                        box_size=box_size,
                        exhaustiveness=exhaustiveness,
                        is_selfies=is_selfies,
                        is_peptide=is_peptide,
                        log_callback=logger.info
                    )
                    logger.info(f"Synformer docking results saved to {synformer_dock_dir}")
                else:
                    logger.warning("Retrosynthesis processing failed")
        
        logger.info(f"=== End of Round {round_no+1} ===\n")
    
    logger.info("Pipeline completed successfully.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="De Novo Drug Discovery Pipeline\n"
                    "Default parameters are provided but can be overridden.\n"
                    "At minimum, specify the output directory (--out_dir)."
    )
    # Output and rounds.
    parser.add_argument("--out_dir", type=str, required=True,
                        help="Base output directory for all pipeline results")
    parser.add_argument("--rounds", type=int, default=1,
                        help="Number of screening rounds (default: 1)")
    
    # Ligand generation parameters.
    parser.add_argument("--checkpoint", type=str, default="DiffSBDD/checkpoints/crossdocked_fullatom_cond.ckpt",
                        help="Path to the checkpoint file (default: DiffSBDD/checkpoints/crossdocked_fullatom_cond.ckpt)")
    parser.add_argument("--pdbfile", type=str, default="input/NS5.pdb",
                        help="Path to target protein PDB file")
    parser.add_argument("--resi_list", type=str, default="A:719 A:770 A:841 A:856 A:887 A:888",
                        help="Residue identifiers (space-separated)")
    parser.add_argument("--n_samples", type=int, default=100,
                        help="Number of ligand molecules to generate (default: 100)")
    parser.add_argument("--sanitize", action="store_true", default=True,
                        help="Apply sanitization to generated molecules (default: True)")
    
    # Energy minimization parameters.
    parser.add_argument("--protein_file", type=str, default="input/NS5.pdb",
                        help="Protein file for energy minimization")
    parser.add_argument("--base_name", type=str, default="NS5",
                        help="Base identifier for naming outputs")
    parser.add_argument("--prep_only", action="store_true", default=False,
                        help="Only perform preparation without minimization (default: False)")
    parser.add_argument("--platform", type=str, default="OpenCL", 
                       help="OpenMM platform to use (CUDA, OpenCL, CPU, Reference, or 'fastest')")
    
    # Redocking parameters.
    parser.add_argument("--program_choice", type=str, default="qvina",
                        help="Redocking program (default: qvina)")
    parser.add_argument("--scoring_function", type=str, default="nnscore2",
                        help="Scoring function (default: nnscore2)")
    parser.add_argument("--center", type=float, nargs=3, default=[114.817, 75.602, 82.416],
                        help="X Y Z coordinates of the docking center (default: 114.817 75.602 82.416)")
    parser.add_argument("--box_size", type=float, nargs=3, default=[38, 70, 58],
                        help="Box sizes in X Y Z (default: 38 70 58)")
    parser.add_argument("--exhaustiveness", type=int, default=10,
                        help="Exhaustiveness for docking (default: 10)")
    parser.add_argument("--is_selfies", action="store_true", default=False,
                        help="Use SELFIES in redocking (default: False)")
    parser.add_argument("--is_peptide", action="store_true", default=False,
                        help="Flag if the ligand is a peptide (default: False)")
    parser.add_argument("--receptor", type=str, default="NS5_test.pdbqt",
                        help="Receptor filename in PDBQT format. The file must be placed in the ./input directory. (default: NS5_test.pdbqt)")
    
    # Optional generative filtering flag.
    parser.add_argument("--apply_filters", action="store_true", default=True,
                        help="Select compounds that pass at least one generative filter for redocking (default: True)")
    
    # Retrosynthesis parameters
    parser.add_argument("--retro_top_n", type=int, default=5,
                        help="Number of top compounds to select for retrosynthesis analysis (default: 5)")
    
    args = parser.parse_args()
    main(
        out_dir=args.out_dir,
        rounds=args.rounds,
        checkpoint=args.checkpoint,
        pdbfile=args.pdbfile,
        resi_list=args.resi_list,
        n_samples=args.n_samples,
        sanitize=args.sanitize,
        protein_file=args.protein_file,
        base_name=args.base_name,
        prep_only=args.prep_only,
        program_choice=args.program_choice,
        scoring_function=args.scoring_function,
        center=args.center,
        box_size=args.box_size,
        exhaustiveness=args.exhaustiveness,
        is_selfies=args.is_selfies,
        is_peptide=args.is_peptide,
        receptor=args.receptor,
        apply_filters=args.apply_filters,
        retro_top_n=args.retro_top_n
    )
