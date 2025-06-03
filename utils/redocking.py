# redocking.py
import os
import sys
from pathlib import Path
import shutil
import logging
import traceback
import subprocess
import threading
import time
import json
import tempfile
from typing import List, Dict, Any, Tuple, Optional

# Import environment manager for conda environment handling
from utils.environment_manager import env_manager

# Get logger for this module
logger = logging.getLogger(__name__)

# Define a timeout for the Unidock subprocess (e.g., 2 hours)
UNIDOCK_SUBPROCESS_TIMEOUT = 7200

def run_unidock_pipeline_simplified(receptor_pdb: Path, sdf_files: List[Path], output_dir: Path, 
                                   center: Tuple[float, float, float], box_size: Tuple[float, float, float],
                                   search_mode: str = "balance", log_callback=None) -> bool:
    """
    Run complete Unidock pipeline using unidocktools unidock_pipeline with GPU.
    
    Args:
        receptor_pdb: Path to receptor PDB file (will be prepared automatically)
        sdf_files: List of SDF ligand files
        output_dir: Directory to save docking results
        center: Center coordinates (x, y, z)
        box_size: Box dimensions (x, y, z)
        search_mode: Search mode ("fast", "balance", or "detail")
        log_callback: Function to call for logging
        
    Returns:
        True if successful, False otherwise
    """
    if log_callback is None:
        log_callback = print
        
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        
        center_x, center_y, center_z = center
        size_x, size_y, size_z = box_size
        
        # Create comma-separated list of SDF files
        ligands_str = ",".join(str(sdf_file) for sdf_file in sdf_files)
        
        # Create working and save directories
        save_dir = output_dir / "savedir"
        
        # Run unidocktools unidock_pipeline command
        command = [
            "unidocktools", "unidock_pipeline",
            "--receptor", str(receptor_pdb),
            "--ligands", ligands_str,
            "--center_x", str(center_x),
            "--center_y", str(center_y),
            "--center_z", str(center_z),
            "--size_x", str(size_x),
            "--size_y", str(size_y),
            "--size_z", str(size_z),
            "--search_mode", search_mode,
            "--savedir", str(save_dir),
            "--batch_size", "100",  # Good batch size for GPU
            "--num_modes", "3",     # Multiple modes for better results
            "--scoring_function", "vina",
            "--prepared_hydrogen"   # Prepare hydrogen automatically
        ]
        
        log_callback(f"Running unidock_pipeline: {' '.join(command)}")
        
        result = env_manager.run_tool(
            tool_name="unidock",
            command=command,
            timeout=UNIDOCK_SUBPROCESS_TIMEOUT,
            capture_output=True,
            text=True,
            log_callback=log_callback,
            stream_output=True
        )
        
        if result.returncode == 0:
            log_callback("Unidock_pipeline completed successfully")
            return True
        else:
            log_callback(f"Unidock_pipeline failed with return code {result.returncode}")
            if result.stderr:
                log_callback(f"Error: {result.stderr}")
            return False
            
    except Exception as e:
        log_callback(f"Error in unidock_pipeline: {e}")
        logger.error(f"Error in unidock_pipeline: {e}", exc_info=True)
        return False

def redock_compound(compound_id, smiles, redock_params, receptor=None, log_callback=print):
    """
    Redock a compound using Unidock pipeline.

    Args:
        compound_id: ID of the compound
        smiles: SMILES string of the compound
        redock_params: Tuple of redocking parameters (center_x, center_y, center_z, size_x, size_y, size_z, search_mode)
        receptor: Path to the receptor PDB file
        log_callback: Function to call for logging

    Returns:
        Tuple of (threading.Thread, dict): The thread running the Unidock subprocess
                                           and a dictionary to store results asynchronously.
    """
    if log_callback is None:
        log_callback = print

    log_callback(f"Preparing asynchronous Unidock pipeline process for {compound_id}.")

    # Create a dictionary to store results asynchronously
    result_storage = {"status": "pending", "data": None}

    # Check if receptor file exists
    if not receptor or not Path(receptor).exists():
        error_msg = f"Receptor file not found: {receptor}"
        log_callback(error_msg)
        result_storage["status"] = "error"
        result_storage["data"] = {"error": error_msg}
        return None, result_storage

    # Create output directory
    output_dir = Path("outputs") / "temp_docking" / f"compound_{compound_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create variant list for the single compound
    variants = [{
        "compound_id": compound_id,
        "variant_id": compound_id,
        "smiles": smiles
    }]

    # Start thread
    log_callback(f"Starting Unidock pipeline thread for {compound_id}...")
    thread = threading.Thread(
        target=_run_unidock_subprocess,
        args=(variants, receptor, redock_params, output_dir, log_callback, result_storage)
    )
    thread.daemon = True
    thread.start()

    log_callback(f"Unidock pipeline thread for {compound_id} started.")

    return thread, result_storage

def _run_unidock_subprocess(variants: List[Dict[str, Any]], receptor_pdb: str, redock_params: Tuple,
                           output_dir: Path, log_callback, result_storage: Dict[str, Any]):
    """Internal function to run the complete Unidock pipeline using unidocktools unidock_pipeline."""
    start_time = time.time()
    
    # Initialize result storage
    result_storage["data"] = {}
    result_storage["status"] = "starting"
    
    try:
        # Extract parameters
        (center_x, center_y, center_z, size_x, size_y, size_z, search_mode) = redock_params
        
        center = (center_x, center_y, center_z)
        box_size = (size_x, size_y, size_z)
        
        # Create temporary working directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Step 1: Create SDF files for all variants
            log_callback("Step 1: Creating SDF files for variants...")
            ligand_input_dir = temp_path / "ligand_input"
            ligand_input_dir.mkdir(parents=True, exist_ok=True)
            
            sdf_files = []
            variant_mapping = {}  # Map SDF files to variant IDs
            
            for variant in variants:
                variant_id = variant.get("variant_id", variant.get("compound_id", "unknown"))
                smiles = variant["smiles"]
                
                # Create SDF file for this variant
                variant_sdf = ligand_input_dir / f"{variant_id}.sdf"
                success = create_sdf_from_smiles(smiles, variant_sdf, variant_id)
                
                if success:
                    sdf_files.append(variant_sdf)
                    variant_mapping[variant_sdf.name] = variant_id
                else:
                    log_callback(f"Failed to create SDF for variant {variant_id}")
            
            if not sdf_files:
                raise Exception("No valid SDF files created for variants")
            
            # Step 2: Run complete unidock_pipeline
            log_callback("Step 2: Running complete unidock_pipeline...")
            
            # Create pipeline output directory
            pipeline_output_dir = output_dir / "pipeline_results"
            
            # Run simplified pipeline
            pipeline_success = run_unidock_pipeline_simplified(
                Path(receptor_pdb), sdf_files, pipeline_output_dir,
                center, box_size, search_mode, log_callback=log_callback
            )
            
            if not pipeline_success:
                raise Exception("Unidock pipeline failed")
            
            # Step 3: Parse pipeline results
            log_callback("Step 3: Parsing pipeline results...")
            docking_results = {}
            
            # Look for results in save directory
            save_dir = pipeline_output_dir / "savedir"
            
            if save_dir.exists():
                log_callback(f"Parsing results from {save_dir}")
                
                # Parse results from this directory
                for sdf_file in sdf_files:
                    variant_id = variant_mapping.get(sdf_file.name, sdf_file.stem)
                    
                    # Look for result files
                    result_files = list(save_dir.glob(f"*{sdf_file.stem}*"))
                    if not result_files:
                        # Try without stem matching
                        result_files = list(save_dir.glob("*.sdf"))
                    
                    if result_files:
                        # Use the first result file found
                        result_file = result_files[0]
                        variant_results = parse_sdf_results(result_file, variant_id, log_callback)
                        if variant_results:
                            docking_results[variant_id] = variant_results
                        else:
                            log_callback(f"Could not parse results for variant {variant_id}")
                    else:
                        log_callback(f"No result files found for variant {variant_id}")
            
            if not docking_results:
                log_callback("Warning: No docking results could be parsed")
            
            result_storage["data"] = docking_results
            result_storage["status"] = "success"
            log_callback("Unidock pipeline completed successfully")
            
    except Exception as e:
        error_msg = f"Unidock pipeline failed: {e}"
        log_callback(error_msg)
        result_storage["data"] = {"error": error_msg}
        result_storage["status"] = "error"
        logger.error(f"Unidock pipeline error: {e}", exc_info=True)
    
    finally:
        elapsed_time = time.time() - start_time
        log_callback(f"Unidock pipeline finished in {elapsed_time:.2f} seconds. Status: {result_storage['status']}")

def create_sdf_from_smiles(smiles: str, output_file: Path, mol_name: str = "molecule") -> bool:
    """
    Create an SDF file from a SMILES string.
    
    Args:
        smiles: SMILES string
        output_file: Path to save the SDF file
        mol_name: Name for the molecule
        
    Returns:
        True if successful, False otherwise
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
        
        # Create molecule from SMILES
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return False
        
        # Add hydrogens
        mol = Chem.AddHs(mol)
        
        # Generate 3D coordinates
        AllChem.EmbedMolecule(mol, randomSeed=42)
        AllChem.UFFOptimizeMolecule(mol)
        
        # Set molecule name
        mol.SetProp("_Name", mol_name)
        
        # Write to SDF
        writer = Chem.SDWriter(str(output_file))
        writer.write(mol)
        writer.close()
        
        return True
        
    except Exception as e:
        logger.error(f"Error creating SDF from SMILES: {e}")
        return False

def parse_sdf_results(result_file: Path, variant_id: str, log_callback) -> Optional[Dict[str, Any]]:
    """Parse SDF result file and extract docking scores."""
    try:
        from rdkit import Chem
        
        supplier = Chem.SDMolSupplier(str(result_file))
        best_score = float('inf')
        pose_count = 0
        
        for mol in supplier:
            if mol is not None:
                pose_count += 1
                # Try to extract score from molecule properties
                score = None
                for prop in mol.GetPropNames():
                    if 'score' in prop.lower() or 'energy' in prop.lower() or 'affinity' in prop.lower():
                        try:
                            score = float(mol.GetProp(prop))
                            break
                        except:
                            continue
                
                if score is not None and score < best_score:
                    best_score = score
        
        if best_score != float('inf'):
            result_dict = {
                "docking_score": best_score,
                "pose_count": pose_count,
                "result_file": str(result_file)
            }
            log_callback(f"Parsed SDF results for {variant_id}: score={best_score}, poses={pose_count}")
            return result_dict
        else:
            log_callback(f"Could not extract score from SDF for {variant_id}")
            return None
            
    except Exception as e:
        log_callback(f"Error parsing SDF results for {variant_id}: {e}")
        return None

# For backward compatibility, keep some references
# These are no longer used but may be referenced in imports
vfu_dir = None  # Deprecated
vfu_config_dir = None  # Deprecated