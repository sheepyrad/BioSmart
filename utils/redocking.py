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

def run_protein_prep(receptor_pdb: Path, output_pdbqt: Path, log_callback=None) -> bool:
    """
    Run protein preparation using unidocktools proteinprep.
    
    Args:
        receptor_pdb: Path to input PDB file
        output_pdbqt: Path to output PDBQT file
        log_callback: Function to call for logging
        
    Returns:
        True if successful, False otherwise
    """
    if log_callback is None:
        log_callback = print
        
    try:
        # Ensure output directory exists
        output_pdbqt.parent.mkdir(parents=True, exist_ok=True)
        
        # Run proteinprep command
        command = [
            "unidocktools", "proteinprep",
            "-r", str(receptor_pdb),
            "-o", str(output_pdbqt),
            "-ph"
        ]
        
        log_callback(f"Running protein preparation: {' '.join(command)}")
        
        result = env_manager.run_tool(
            tool_name="unidocktools",
            command=command,
            timeout=300,  # 5 minutes should be enough for protein prep
            capture_output=True,
            text=True,
            log_callback=log_callback,
            stream_output=True
        )
        
        if result.returncode == 0:
            log_callback(f"Protein preparation completed successfully: {output_pdbqt}")
            if output_pdbqt.exists():
                file_size = output_pdbqt.stat().st_size
                log_callback(f"Generated PDBQT file size: {file_size} bytes")
            return True
        else:
            log_callback(f"Protein preparation failed with return code {result.returncode}")
            if result.stderr:
                log_callback(f"Error: {result.stderr}")
            if result.stdout:
                log_callback(f"Output: {result.stdout}")
            return False
            
    except Exception as e:
        log_callback(f"Error in protein preparation: {e}")
        logger.error(f"Error in protein preparation: {e}", exc_info=True)
        return False

def run_ligand_prep(sdf_files: List[Path], output_dir: Path, batch_size: int = 1200, log_callback=None) -> bool:
    """
    Run ligand preparation using unidocktools ligandprep.
    
    Args:
        sdf_files: List of SDF ligand files
        output_dir: Output directory for prepared ligands
        batch_size: Batch size for processing
        log_callback: Function to call for logging
        
    Returns:
        True if successful, False otherwise
    """
    if log_callback is None:
        log_callback = print
        
    try:
        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Write ligand file paths to a temporary text file to avoid OS arg length limits
        tmp_list_file = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as tmpf:
                for sdf_file in sdf_files:
                    tmpf.write(str(sdf_file) + "\n")
                tmp_list_file = Path(tmpf.name)

            # Run ligandprep command using -i <Txt File>
            command = [
                "unidocktools", "ligandprep",
                "-i", str(tmp_list_file),
                "-sd", str(output_dir),
                "-bs", str(batch_size)
            ]

            log_callback(f"Running ligand preparation: {' '.join(command)}")

            result = env_manager.run_tool(
                tool_name="unidocktools",
                command=command,
                timeout=1800,  # 30 minutes for ligand prep
                capture_output=True,
                text=True,
                log_callback=log_callback,
                stream_output=True
            )
        finally:
            # Clean up temp list file
            if tmp_list_file and tmp_list_file.exists():
                try:
                    tmp_list_file.unlink()
                except Exception:
                    pass
        
        if result.returncode == 0:
            log_callback(f"Ligand preparation completed successfully: {output_dir}")
            # Check for output files
            output_files = list(output_dir.glob("*.sdf"))
            log_callback(f"Generated {len(output_files)} ligand SDF files")
            for sdf_file in output_files[:3]:  # Log first 3 files
                log_callback(f"  - {sdf_file.name} ({sdf_file.stat().st_size} bytes)")
            if len(output_files) > 3:
                log_callback(f"  ... and {len(output_files) - 3} more files")
            return True
        else:
            log_callback(f"Ligand preparation failed with return code {result.returncode}")
            if result.stderr:
                log_callback(f"Error: {result.stderr}")
            if result.stdout:
                log_callback(f"Output: {result.stdout}")
            return False
            
    except Exception as e:
        log_callback(f"Error in ligand preparation: {e}")
        logger.error(f"Error in ligand preparation: {e}", exc_info=True)
        return False

def run_unidock_docking(receptor_pdbqt: Path, ligand_sdfs: List[Path], output_dir: Path,
                       center: Tuple[float, float, float], box_size: Tuple[float, float, float],
                       search_mode: str = "detail", log_callback=None) -> bool:
    """
    Run Unidock docking with prepared receptor and ligands.
    
    Args:
        receptor_pdbqt: Path to prepared receptor PDBQT file
        ligand_sdfs: List of prepared ligand SDF files
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
        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)
        
        center_x, center_y, center_z = center
        size_x, size_y, size_z = box_size
        
        # Create ligand index file to avoid command-line argument length limits
        # This follows the official Uni-Dock example pattern (see run_dock.py)
        # The file is retained for reference and debugging purposes
        ligand_index_file = output_dir / "ligand_index.txt"
        with open(ligand_index_file, 'w') as f:
            # Write space-separated ligand file paths
            ligand_paths = [str(ligand_sdf) for ligand_sdf in ligand_sdfs]
            f.write(" ".join(ligand_paths))
        
        log_callback(f"Created ligand index file with {len(ligand_sdfs)} ligands: {ligand_index_file}")
        
        # Run unidock command using --ligand_index (not --gpu_batch) to avoid command-line argument length limits
        # This approach is safer and more reliable for large batches, preventing potential errors
        command = [
            "unidock",
            "--receptor", str(receptor_pdbqt),
            "--ligand_index", str(ligand_index_file),
            "--search_mode", search_mode,
            "--scoring", "vina",
            "--center_x", str(center_x),
            "--center_y", str(center_y),
            "--center_z", str(center_z),
            "--size_x", str(size_x),
            "--size_y", str(size_y),
            "--size_z", str(size_z),
            "--dir", str(output_dir)
        ]
        
        log_callback(f"Running Unidock docking with {len(ligand_sdfs)} ligands using ligand_index file")
        log_callback(f"Command: {' '.join(command)}")
        
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
            log_callback(f"Unidock docking completed successfully: {output_dir}")
            log_callback(f"Ligand index file retained at: {ligand_index_file}")
            # Check for output files
            output_files = list(output_dir.glob("*.sdf")) + list(output_dir.glob("*.pdbqt"))
            log_callback(f"Generated {len(output_files)} docking result files")
            for result_file in output_files[:3]:  # Log first 3 files
                log_callback(f"  - {result_file.name} ({result_file.stat().st_size} bytes)")
            if len(output_files) > 3:
                log_callback(f"  ... and {len(output_files) - 3} more files")
            return True
        else:
            log_callback(f"Unidock docking failed with return code {result.returncode}")
            if result.stderr:
                log_callback(f"Error: {result.stderr}")
            if result.stdout:
                log_callback(f"Output: {result.stdout}")
            return False
            
    except Exception as e:
        log_callback(f"Error in Unidock docking: {e}")
        logger.error(f"Error in Unidock docking: {e}", exc_info=True)
        return False

# DEPRECATED: The following function was removed because it was unused and redundant:
# - run_complete_docking_workflow() - unused function that provided proteinprep -> ligandprep -> unidock
#   workflow but without result parsing. This functionality is fully covered by run_batch_compound_redocking()
#   which additionally handles SMILES-to-SDF conversion and result parsing.
# 
# Use run_batch_compound_redocking() instead for complete docking workflows with result parsing.
# Date removed: 20251031

def run_batch_compound_redocking(compounds_data: List[Dict[str, Any]], receptor_pdb: Path, 
                                redock_params: Tuple, output_base_dir: Path, 
                                batch_size: int = 1200, save_temp_files: bool = True, 
                                log_callback=None) -> Dict[str, Any]:
    """
    Run batch redocking for multiple compounds with optimizations:
    1. Prepare protein only once
    2. Batch prepare all ligands together
    3. Run docking for all compounds
    4. Save temp files for testing
    
    Args:
        compounds_data: List of compound dictionaries with 'compound_id' and 'smiles'
        receptor_pdb: Path to receptor PDB file
        redock_params: Tuple of redocking parameters (center_x, center_y, center_z, size_x, size_y, size_z, search_mode)
        output_base_dir: Base output directory
        batch_size: Batch size for ligand preparation
        save_temp_files: Whether to save temporary files
        log_callback: Function to call for logging
        
    Returns:
        Dictionary with results for each compound
    """
    if log_callback is None:
        log_callback = print
        
    try:
        output_base_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract parameters
        (center_x, center_y, center_z, size_x, size_y, size_z, search_mode) = redock_params
        center = (center_x, center_y, center_z)
        box_size = (size_x, size_y, size_z)
        
        log_callback("=" * 60)
        log_callback("BATCH REDOCKING WORKFLOW STARTING")
        log_callback(f"Number of compounds: {len(compounds_data)}")
        log_callback(f"Receptor: {receptor_pdb}")
        log_callback(f"Output directory: {output_base_dir}")
        log_callback("=" * 60)
        
        # Step 1: Prepare protein once
        log_callback("Step 1: Preparing protein (once for all compounds)...")
        prepared_receptor = output_base_dir / "shared_receptor_prepared.pdbqt"
        
        if not run_protein_prep(receptor_pdb, prepared_receptor, log_callback):
            raise Exception("Protein preparation failed")
        
        # Step 2: Create SDF files for all compounds
        log_callback("Step 2: Creating SDF files for all compounds...")
        ligand_input_dir = output_base_dir / "all_ligand_inputs"
        ligand_input_dir.mkdir(parents=True, exist_ok=True)
        
        sdf_files = []
        compound_mapping = {}  # Map SDF files to compound IDs
        
        for compound_data in compounds_data:
            compound_id = compound_data["compound_id"]
            smiles = compound_data["smiles"]
            
            # Create SDF file for this compound
            compound_sdf = ligand_input_dir / f"{compound_id}.sdf"
            success = create_sdf_from_smiles(smiles, compound_sdf, compound_id)
            
            if success:
                sdf_files.append(compound_sdf)
                compound_mapping[compound_sdf.name] = compound_id
                log_callback(f"Created SDF for compound {compound_id}")
            else:
                log_callback(f"Failed to create SDF for compound {compound_id}")
        
        if not sdf_files:
            raise Exception("No valid SDF files created for compounds")
        
        log_callback(f"Successfully created {len(sdf_files)} SDF files")
        
        # Step 3: Run batch ligand preparation
        log_callback("Step 3: Running batch ligand preparation...")
        ligand_prep_dir = output_base_dir / "batch_ligand_prep"
        
        if not run_ligand_prep(sdf_files, ligand_prep_dir, batch_size, log_callback):
            raise Exception("Batch ligand preparation failed")
        
        # Find prepared ligand files
        prepared_ligand_sdfs = list(ligand_prep_dir.glob("*.sdf"))
        log_callback(f"Batch preparation completed: {len(prepared_ligand_sdfs)} files")
        
        # Step 4: Run batch docking
        log_callback("Step 4: Running batch docking...")
        docking_output_dir = output_base_dir / "batch_docking_results"
        
        if not run_unidock_docking(prepared_receptor, prepared_ligand_sdfs, docking_output_dir,
                                  center, box_size, search_mode, log_callback):
            raise Exception("Batch docking failed")
        
        # Step 5: Parse results for each compound
        log_callback("Step 5: Parsing docking results...")
        results = {}
        
        # Parse docking results
        for sdf_file in sdf_files:
            compound_id = compound_mapping.get(sdf_file.name, sdf_file.stem)
            
            # Look for result files in docking output
            result_files = list(docking_output_dir.glob(f"*{sdf_file.stem}*"))
            if not result_files:
                # Try to find any result files
                all_result_files = list(docking_output_dir.glob("*.pdbqt")) + list(docking_output_dir.glob("*.sdf"))
                # For batch docking, results might be in a combined file, try to match by compound ID
                result_files = [f for f in all_result_files if compound_id in f.name]
            
            if result_files:
                result_file = result_files[0]
                if result_file.suffix.lower() == '.pdbqt':
                    compound_results = parse_pdbqt_results(result_file, compound_id, log_callback)
                elif result_file.suffix.lower() == '.sdf':
                    compound_results = parse_sdf_results(result_file, compound_id, log_callback)
                else:
                    log_callback(f"Unknown result file format for {compound_id}: {result_file.suffix}")
                    compound_results = None
                
                if compound_results:
                    results[compound_id] = compound_results
                else:
                    log_callback(f"Could not parse results for compound {compound_id}")
                    results[compound_id] = {"error": "Could not parse results"}
            else:
                log_callback(f"No result files found for compound {compound_id}")
                results[compound_id] = {"error": "No result files found"}
        
        # Step 6: Save temp files if requested
        if save_temp_files:
            log_callback("Step 6: Saving temporary files for future testing...")
            temp_save_dir = output_base_dir / "temp_files_for_testing"
            temp_save_dir.mkdir(exist_ok=True)
            
            # Save prepared receptor
            if prepared_receptor.exists():
                shutil.copy2(prepared_receptor, temp_save_dir / "shared_receptor_prepared.pdbqt")
                log_callback(f"Saved shared receptor to: {temp_save_dir / 'shared_receptor_prepared.pdbqt'}")
            
            # Save all input ligands
            input_ligands_dir = temp_save_dir / "input_ligands"
            if ligand_input_dir.exists():
                shutil.copytree(ligand_input_dir, input_ligands_dir, dirs_exist_ok=True)
                log_callback(f"Saved input ligands to: {input_ligands_dir}")
            
            # Save prepared ligands
            prep_ligands_dir = temp_save_dir / "prepared_ligands"
            if ligand_prep_dir.exists():
                shutil.copytree(ligand_prep_dir, prep_ligands_dir, dirs_exist_ok=True)
                log_callback(f"Saved prepared ligands to: {prep_ligands_dir}")
            
            # Save docking results
            docking_results_dir = temp_save_dir / "docking_results"
            if docking_output_dir.exists():
                shutil.copytree(docking_output_dir, docking_results_dir, dirs_exist_ok=True)
                log_callback(f"Saved docking results to: {docking_results_dir}")
            
            # Save parameters and compound mapping
            metadata_file = temp_save_dir / "batch_metadata.json"
            with open(metadata_file, 'w') as f:
                metadata = {
                    "docking_parameters": {
                        "center": center,
                        "box_size": box_size,
                        "search_mode": search_mode,
                        "batch_size": batch_size
                    },
                    "compounds": compounds_data,
                    "compound_mapping": compound_mapping,
                    "receptor_pdb": str(receptor_pdb),
                    "prepared_receptor": str(prepared_receptor),
                    "num_compounds": len(compounds_data),
                    "num_successful_sdfs": len(sdf_files),
                    "num_prepared_ligands": len(prepared_ligand_sdfs)
                }
                json.dump(metadata, f, indent=2)
            log_callback(f"Saved batch metadata to: {metadata_file}")
        
        log_callback("=" * 60)
        log_callback("BATCH REDOCKING WORKFLOW COMPLETED SUCCESSFULLY")
        log_callback(f"Processed {len(results)} compounds")
        successful_results = sum(1 for r in results.values() if "error" not in r)
        log_callback(f"Successful docking results: {successful_results}/{len(results)}")
        log_callback("=" * 60)
        
        return results
        
    except Exception as e:
        log_callback(f"Error in batch redocking workflow: {e}")
        logger.error(f"Error in batch redocking workflow: {e}", exc_info=True)
        return {"error": str(e)}

# DEPRECATED: The following functions were removed because they were unused:
# - redock_compound() - unused wrapper function for single compound processing
# - _run_optimized_single_compound_workflow() - internal helper only used by redock_compound
# - _run_unidock_workflow() - legacy function that was also unused
# 
# Use run_batch_compound_redocking() instead for batch processing of compounds.
# Date removed: 20251031

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

def parse_pdbqt_results(result_file: Path, variant_id: str, log_callback) -> Optional[Dict[str, Any]]:
    """Parse PDBQT result file and extract docking scores."""
    try:
        best_score = float('inf')
        pose_count = 0
        
        with open(result_file, 'r') as f:
            for line in f:
                if line.startswith('REMARK VINA RESULT:'):
                    # Parse Vina score from REMARK line
                    # Format: REMARK VINA RESULT:    -8.5      0.000      0.000
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            score = float(parts[3])
                            pose_count += 1
                            if score < best_score:
                                best_score = score
                        except ValueError:
                            continue
        
        if best_score != float('inf'):
            result_dict = {
                "docking_score": best_score,
                "pose_count": pose_count,
                "result_file": str(result_file)
            }
            log_callback(f"Parsed PDBQT results for {variant_id}: score={best_score}, poses={pose_count}")
            return result_dict
        else:
            log_callback(f"Could not extract score from PDBQT for {variant_id}")
            return None
            
    except Exception as e:
        log_callback(f"Error parsing PDBQT results for {variant_id}: {e}")
        return None

def parse_sdf_results(result_file: Path, variant_id: str, log_callback) -> Optional[Dict[str, Any]]:
    """Parse SDF result file and extract docking scores from Unidock output format."""
    try:
        best_score = float('inf')
        pose_count = 0
        all_scores = []
        
        # Parse the SDF file directly to extract Uni-Dock RESULT sections
        with open(result_file, 'r') as f:
            content = f.read()
        
        # Split by molecule separators
        molecules = content.split('$$$$')
        
        for mol_block in molecules:
            if '> <Uni-Dock RESULT>' in mol_block:
                pose_count += 1
                
                # Extract the Uni-Dock RESULT section
                lines = mol_block.split('\n')
                in_result_section = False
                
                for line in lines:
                    if '> <Uni-Dock RESULT>' in line:
                        in_result_section = True
                        continue
                    elif in_result_section and line.strip() == '':
                        in_result_section = False
                        continue
                    elif in_result_section and line.startswith('ENERGY='):
                        # Parse the energy line: ENERGY=   -6.276  LOWER_BOUND=    0.000  UPPER_BOUND=    0.000
                        try:
                            energy_part = line.split('ENERGY=')[1].split('LOWER_BOUND=')[0].strip()
                            score = float(energy_part)
                            all_scores.append(score)
                            if score < best_score:
                                best_score = score
                        except (ValueError, IndexError) as e:
                            log_callback(f"Could not parse energy line: {line.strip()}")
                            continue
        
        # Fallback: try RDKit parsing if no Uni-Dock results found
        if pose_count == 0:
            log_callback(f"No Uni-Dock RESULT sections found, trying RDKit parsing for {variant_id}")
            try:
                from rdkit import Chem
                
                supplier = Chem.SDMolSupplier(str(result_file))
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
                        
                        if score is not None:
                            all_scores.append(score)
                            if score < best_score:
                                best_score = score
            except Exception as rdkit_e:
                log_callback(f"RDKit parsing also failed for {variant_id}: {rdkit_e}")
        
        if best_score != float('inf') and pose_count > 0:
            result_dict = {
                "docking_score": best_score,
                "pose_count": pose_count,
                "all_scores": all_scores,
                "result_file": str(result_file)
            }
            log_callback(f"Parsed SDF results for {variant_id}: best_score={best_score}, poses={pose_count}")
            return result_dict
        else:
            log_callback(f"Could not extract scores from SDF for {variant_id}")
            return None
            
    except Exception as e:
        log_callback(f"Error parsing SDF results for {variant_id}: {e}")
        return None
