# ligand_generation.py
import subprocess
import threading
import time
import os
import signal
import resource
import io
import sys
import glob
from pathlib import Path
import shutil
import yaml  # Add yaml import
import random # Import random module for seed generation
from rdkit import Chem
import gc

# Import the new environment manager
from .environment_manager import env_manager

# Try to import torch for CUDA memory management
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# Define a timeout for the subprocess (e.g., 2 hours)
SUBPROCESS_TIMEOUT = 7200 

def clear_gpu_memory():
    """Clear GPU memory cache to prevent memory leaks."""
    if TORCH_AVAILABLE and torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            # Force garbage collection
            gc.collect()
        except Exception as e:
            print(f"Failed to clear GPU memory cache: {e}", file=sys.stderr)

def run_pocket2mol(pdbfile, center, bbox_size, out_dir, n_samples, log_callback=None):
    """
    Run the Pocket2Mol model for ligand generation using conda environment.
    
    Args:
        pdbfile (str): Path to the PDB file
        center (list): Center coordinates [x, y, z]
        bbox_size (float): Size of the bounding box
        out_dir (str): Output directory
        n_samples (int): Number of samples to generate
        log_callback (function): Callback function for logging
        
    Returns:
        threading.Thread: Thread running the process
    """
    # Get the current directory
    current_dir = os.getcwd()
    
    # Normalize paths to be absolute
    pdbfile_path = os.path.abspath(pdbfile)
    out_dir_path = os.path.abspath(out_dir)
    
    # Make sure output directory exists
    os.makedirs(out_dir_path, exist_ok=True)
    
    # Find Pocket2Mol directory relative to this script
    current_script_dir = Path(__file__).parent
    utils_dir = current_script_dir
    root_dir = utils_dir.parent
    pocket2mol_dir = root_dir / "src" / "Pocket2Mol"
    if not pocket2mol_dir.exists():
        if log_callback:
            log_callback(f"Error: Pocket2Mol directory not found at {pocket2mol_dir}")
        raise FileNotFoundError(f"Pocket2Mol directory not found at {pocket2mol_dir}")
    
    # Format center coordinates as a comma-separated string
    center_str = ",".join(map(str, center))
    
    # Define config file paths
    config_path = os.path.join(pocket2mol_dir, "configs", "sample_for_pdb.yml")
    config_file_name = os.path.basename(config_path)
    temp_config_path = os.path.join(pocket2mol_dir, "configs", f"temp_{config_file_name}")
    final_config_to_use = config_path # Default to original config

    # Load, modify, and save the config file if n_samples needs changing
    try:
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
        
        # Generate a random seed for this run
        run_seed = random.randint(0, 2**16 - 1)
        if log_callback:
            log_callback(f"Generated random seed for Pocket2Mol run: {run_seed}")
            
        # Update seed and num_samples in the config data
        if 'sample' not in config_data:
            config_data['sample'] = {} # Ensure sample key exists
        config_data['sample']['seed'] = run_seed
        config_data['sample']['num_samples'] = n_samples

        # Always write the temp config file with the new seed and correct n_samples
        with open(temp_config_path, 'w') as f:
            yaml.dump(config_data, f, default_flow_style=False)
        final_config_to_use = temp_config_path # Use the modified temp config
        if log_callback:
            log_callback(f"Using temporary config {temp_config_path} with seed={run_seed}, num_samples={n_samples}")

    except Exception as e:
        if log_callback:
            log_callback(f"Error processing config file {config_path}: {e}. Using original config.")
        # Fallback to original config path if there's an error
        final_config_to_use = config_path 
        # Clean up potentially partially written temp file
        if os.path.exists(temp_config_path):
            try:
                os.remove(temp_config_path)
            except OSError:
                pass # Ignore error if removal fails

    # ---- Always format the center argument with leading space and quotes ----
    center_arg = f'--center " {center_str}" '
    # ---- End center argument formatting ----

    # Construct the command using the new environment manager approach
    command = [
        "python", "sample_for_pdb.py",
        "--pdb_path", pdbfile_path,
        "--center", f" {center_str}",  # Use the formatted center argument
        "--bbox_size", str(bbox_size),
        "--config", final_config_to_use,  # Use the determined config path
        "--outdir", out_dir_path
    ]
    
    if log_callback:
        log_callback(f"Executing Pocket2Mol: {' '.join(command)}\nGenerating molecules...\n")

    def run_process():
        start_time = time.time()
        result_storage = {}
        
        try:
            # Clear GPU memory before starting Pocket2Mol
            if log_callback:
                log_callback("Clearing GPU memory before Pocket2Mol execution...")
            clear_gpu_memory()
            
            # Use the environment manager to run Pocket2Mol with streaming output
            thread = env_manager.run_tool_async(
                tool_name="pocket2mol",
                command=command,
                cwd=str(pocket2mol_dir),
                timeout=SUBPROCESS_TIMEOUT,
                log_callback=log_callback,
                result_storage=result_storage,
                stream_output=True  # Enable real-time output streaming
            )
            
            # Wait for the thread to complete
            thread.join()
            
            # Clear GPU memory after Pocket2Mol execution
            if log_callback:
                log_callback("Clearing GPU memory after Pocket2Mol execution...")
            clear_gpu_memory()
            
            # Check results
            status = result_storage.get("status", "unknown")
            if status == "success":
                if log_callback:
                    log_callback("Pocket2Mol process completed successfully")
            elif status == "timeout":
                if log_callback:
                    log_callback(f"Pocket2Mol process timed out after {SUBPROCESS_TIMEOUT} seconds")
            else:
                error_msg = result_storage.get("error", "Unknown error")
                if log_callback:
                    log_callback(f"Pocket2Mol process failed: {error_msg}")
            
            # Note: stdout/stderr are now streamed in real-time, no need to log them again
            
            # --- Read Pocket2Mol's own log file --- 
            try:
                # Find the specific output directory created by Pocket2Mol inside out_dir_path
                p2m_output_dirs = list(Path(out_dir_path).glob(f"temp_sample_for_pdb_{Path(pdbfile_path).stem}*"))
                if p2m_output_dirs:
                    p2m_log_dir = sorted(p2m_output_dirs)[-1] # Get the latest one if multiple exist
                    p2m_log_file = p2m_log_dir / "log.txt"
                    if p2m_log_file.exists():
                        if log_callback:
                            log_callback("--- Start Pocket2Mol Internal Log --- ")
                        with open(p2m_log_file, 'r') as f_log:
                            for log_line in f_log:
                                if log_callback:
                                    log_callback(log_line.strip()) # Log each line
                        if log_callback:
                            log_callback("--- End Pocket2Mol Internal Log --- ")
                    else:
                        if log_callback:
                            log_callback(f"Pocket2Mol log file not found at: {p2m_log_file}")
                else:
                    if log_callback:
                        log_callback(f"Could not find Pocket2Mol output subdirectory in: {out_dir_path}")
            except Exception as log_read_e:
                if log_callback:
                    log_callback(f"Error reading Pocket2Mol log file: {log_read_e}")
            
            elapsed_time = time.time() - start_time
            if log_callback:
                try:
                    log_callback(f"Finished generating molecules! (Time taken: {elapsed_time:.2f} seconds)\n")
                    
                    # Find the output directory
                    output_dirs = glob.glob(os.path.join(out_dir_path, f"sample_for_pdb_{os.path.basename(pdbfile_path)}_*"))
                    if output_dirs:
                        latest_output_dir = sorted(output_dirs)[-1]
                        log_callback(f"Output directory: {latest_output_dir}")
                    else:
                        log_callback("Warning: Could not find output directory")
                except Exception as e:
                    print(f"Finished generating molecules! (Time taken: {elapsed_time:.2f} seconds)", file=sys.stderr)
                    print(f"Error in logging: {e}", file=sys.stderr)
                    
        except Exception as e:
            if log_callback:
                try:
                    log_callback(f"Error in molecule generation process: {e}")
                except Exception:
                    print(f"Error in molecule generation process: {e}", file=sys.stderr)
        
        finally:
            # Always clear GPU memory when done
            clear_gpu_memory()
            
            # Delete temporary config file if it was created and used
            if final_config_to_use == temp_config_path and os.path.exists(temp_config_path):
                try:
                    os.remove(temp_config_path)
                    if log_callback:
                        log_callback(f"Removed temporary config file: {temp_config_path}")
                except Exception as e:
                    # Use print instead of log_callback as it might be unavailable here
                    print(f"Error removing temporary config file {temp_config_path}: {e}", file=sys.stderr)
    
    thread = threading.Thread(target=run_process)
    thread.daemon = True  # Make thread a daemon so it doesn't block program exit
    thread.start()
    return thread

def combine_pocket2mol_outputs(output_dir, target_sdf, cleanup_pt_files=True):
    """
    Combine Pocket2Mol output SDF files into a single SDF file and optionally clean up .pt files.
    
    Args:
        output_dir (str): Pocket2Mol output directory
        target_sdf (str): Target SDF file path
        cleanup_pt_files (bool): Whether to delete .pt files after successful combination
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Find the SDF directory recursively
        output_path = Path(output_dir)

        # Search recursively for any directory named 'SDF'
        sdf_dirs = list(output_path.rglob('SDF'))

        # Filter out any results that are not directories (though rglob should only find dirs with this pattern)
        sdf_dirs = [d for d in sdf_dirs if d.is_dir()]

        if not sdf_dirs:
            print(f"Error: Could not find any 'SDF' subdirectory recursively within {output_dir}", file=sys.stderr)
            return False

        # If multiple SDF dirs are found, use the first one and maybe log a warning
        if len(sdf_dirs) > 1:
            print(f"Warning: Found multiple 'SDF' subdirectories in {output_dir}. Using the first one found: {sdf_dirs[0]}", file=sys.stderr)

        sdf_dir = sdf_dirs[0] # Use the first found SDF directory

        sdf_files = list(sdf_dir.glob("*.sdf"))

        if not sdf_files:
            print(f"Error: No SDF files found in {sdf_dir}", file=sys.stderr)
            return False

        # Combine SDF files using RDKit
        mol_count = 0
        writer = None # Initialize writer outside the loop
        try:
            writer = Chem.SDWriter(str(target_sdf)) # Convert Path object to string for SDWriter
            if writer is None:
                raise IOError(f"Could not open SDWriter for {target_sdf}")

            for sdf_file in sorted(sdf_files): # Sort to ensure consistent order
                supplier = None # Initialize supplier
                try:
                    # Use removeHs=False and sanitize=False for potentially problematic inputs
                    supplier = Chem.SDMolSupplier(str(sdf_file), removeHs=False, sanitize=False)
                    if supplier is None:
                        print(f"Warning: Could not create SDMolSupplier for {sdf_file}. Skipping.", file=sys.stderr)
                        continue

                    for mol in supplier:
                        if mol is not None:
                            # Attempt sanitization here, catch failures
                            try:
                                Chem.SanitizeMol(mol)
                                writer.write(mol)
                                mol_count += 1
                            except Chem.MolSanitizeException as sanitize_e:
                                print(f"Warning: Skipping molecule from {sdf_file} due to sanitization error: {sanitize_e}", file=sys.stderr)
                            except Exception as write_e: # Catch other potential write errors
                                 print(f"Warning: Skipping molecule from {sdf_file} due to write error: {write_e}", file=sys.stderr)
                        else:
                             print(f"Warning: Skipping invalid molecule entry in {sdf_file}.", file=sys.stderr)
                except Exception as supplier_e:
                    print(f"Error processing file {sdf_file}: {supplier_e}", file=sys.stderr)
                finally:
                    # Ensure supplier is closed if it was opened (SDMolSupplier doesn't have a close method, handled by context or GC)
                    pass

            print(f"Successfully combined {mol_count} molecules into {target_sdf}", file=sys.stderr)
            
            # Clean up .pt files after successful combination
            if cleanup_pt_files and mol_count > 0:
                try:
                    pt_files = list(output_path.rglob("*.pt"))
                    if pt_files:
                        # Calculate total size before deletion
                        total_size = sum(f.stat().st_size for f in pt_files if f.exists())
                        
                        deleted_count = 0
                        deleted_size = 0
                        for pt_file in pt_files:
                            try:
                                if pt_file.exists():
                                    file_size = pt_file.stat().st_size
                                    pt_file.unlink()
                                    deleted_count += 1
                                    deleted_size += file_size
                            except Exception as del_e:
                                print(f"Warning: Could not delete {pt_file}: {del_e}", file=sys.stderr)
                        
                        # Convert bytes to human readable format
                        def format_bytes(bytes_val):
                            for unit in ['B', 'KB', 'MB', 'GB']:
                                if bytes_val < 1024.0:
                                    return f"{bytes_val:.1f}{unit}"
                                bytes_val /= 1024.0
                            return f"{bytes_val:.1f}TB"
                        
                        print(f"Cleaned up {deleted_count} .pt files, freed {format_bytes(deleted_size)} of disk space", file=sys.stderr)
                    else:
                        print("No .pt files found for cleanup", file=sys.stderr)
                except Exception as cleanup_e:
                    print(f"Warning: Error during .pt file cleanup: {cleanup_e}", file=sys.stderr)
            
            return True
        except Exception as e:
            print(f"Error combining Pocket2Mol outputs using RDKit: {e}", file=sys.stderr)
            return False
        finally:
            if writer:
                try:
                    writer.close()
                except Exception as close_e:
                    print(f"Error closing SDWriter: {close_e}", file=sys.stderr)

    except Exception as e: # Outer try-except for path finding etc.
        print(f"Error finding Pocket2Mol output directories: {e}", file=sys.stderr)
        return False

def cleanup_pocket2mol_pt_files(directory_path, log_callback=None):
    """
    Clean up .pt files from Pocket2Mol output directories to save disk space.
    
    Args:
        directory_path (str): Path to directory containing Pocket2Mol outputs
        log_callback (function): Optional callback function for logging
        
    Returns:
        dict: Summary of cleanup operation with keys:
              - 'success': bool
              - 'files_deleted': int 
              - 'space_freed': int (bytes)
              - 'error': str (if any)
    """
    result = {
        'success': False,
        'files_deleted': 0,
        'space_freed': 0,
        'error': None
    }
    
    try:
        directory_path = Path(directory_path)
        if not directory_path.exists():
            result['error'] = f"Directory does not exist: {directory_path}"
            return result
            
        # Find all .pt files recursively
        pt_files = list(directory_path.rglob("*.pt"))
        
        if not pt_files:
            if log_callback:
                log_callback("No .pt files found for cleanup")
            result['success'] = True
            return result
        
        # Calculate total size and delete files
        total_size_before = 0
        deleted_count = 0
        deleted_size = 0
        
        for pt_file in pt_files:
            try:
                if pt_file.exists():
                    file_size = pt_file.stat().st_size
                    total_size_before += file_size
                    pt_file.unlink()
                    deleted_count += 1
                    deleted_size += file_size
                    if log_callback:
                        log_callback(f"Deleted: {pt_file} ({file_size / (1024**3):.2f} GB)")
            except Exception as del_e:
                error_msg = f"Warning: Could not delete {pt_file}: {del_e}"
                if log_callback:
                    log_callback(error_msg)
                else:
                    print(error_msg, file=sys.stderr)
        
        # Convert bytes to human readable format
        def format_bytes(bytes_val):
            for unit in ['B', 'KB', 'MB', 'GB']:
                if bytes_val < 1024.0:
                    return f"{bytes_val:.1f}{unit}"
                bytes_val /= 1024.0
            return f"{bytes_val:.1f}TB"
        
        success_msg = f"Cleanup completed: {deleted_count} .pt files deleted, {format_bytes(deleted_size)} disk space freed"
        if log_callback:
            log_callback(success_msg)
        else:
            print(success_msg, file=sys.stderr)
            
        result.update({
            'success': True,
            'files_deleted': deleted_count,
            'space_freed': deleted_size
        })
        
        return result
        
    except Exception as e:
        error_msg = f"Error during .pt file cleanup: {e}"
        result['error'] = error_msg
        if log_callback:
            log_callback(error_msg)
        else:
            print(error_msg, file=sys.stderr)
        return result

def run_ligand_generation(checkpoint=None, pdbfile=None, outfile=None, resi_list=None, 
                          n_samples=100, sanitize=True, log_callback=None, model="diffsbdd",
                          center=None, bbox_size=None, out_dir=None):
    """
    Run ligand generation using either DiffSBDD or Pocket2Mol model with conda environments.
    
    Args:
        checkpoint (str): Path to the checkpoint file (DiffSBDD only)
        pdbfile (str): Path to the PDB file
        outfile (str): Output file path (DiffSBDD only)
        resi_list (list): Residue identifiers (DiffSBDD only)
        n_samples (int): Number of samples to generate
        sanitize (bool): Whether to sanitize generated molecules (DiffSBDD only)
        log_callback (function): Callback function for logging
        model (str): Model to use ('diffsbdd' or 'pocket2mol')
        center (list): Center coordinates [x, y, z] (Pocket2Mol only)
        bbox_size (float): Size of the bounding box (Pocket2Mol only)
        out_dir (str): Output directory (Pocket2Mol only)
        
    Returns:
        threading.Thread: Thread running the process
    """
    if model.lower() == "pocket2mol":
        if not all([pdbfile, center, bbox_size, out_dir]):
            raise ValueError("pdbfile, center, bbox_size, and out_dir are required for Pocket2Mol")
        
        return run_pocket2mol(pdbfile, center, bbox_size, out_dir, n_samples, log_callback)
    else:  # Default to DiffSBDD
        # Get the current directory
        current_dir = os.getcwd()
        
        # Normalize paths to be absolute
        checkpoint_path = os.path.abspath(checkpoint)
        pdbfile_path = os.path.abspath(pdbfile)
        outfile_path = os.path.abspath(outfile)
        
        # Change to the directory containing DiffSBDD (now in src)
        diffsbdd_dir = os.path.join(current_dir, "src", "DiffSBDD")
        
        # Construct command as list for environment manager
        command = [
            "python", "generate_ligands.py", checkpoint_path,
            "--pdbfile", pdbfile_path,
            "--outfile", outfile_path,
            "--resi_list"] + resi_list + [
            "--n_samples", str(n_samples)
        ]
        
        if sanitize:
            command.append("--sanitize")
        
        if log_callback:
            log_callback(f"Executing DiffSBDD: {' '.join(command)}\nGenerating {n_samples} ligands...\n")

        def run_process():
            start_time = time.time()
            result_storage = {}
            
            try:
                # Use the environment manager to run DiffSBDD with streaming output
                thread = env_manager.run_tool_async(
                    tool_name="diffsbdd",
                    command=command,
                    cwd=diffsbdd_dir,
                    timeout=3600,  # 1 hour timeout
                    log_callback=log_callback,
                    result_storage=result_storage,
                    stream_output=True  # Enable real-time output streaming
                )
                
                # Wait for the thread to complete
                thread.join()
                
                # Check results
                status = result_storage.get("status", "unknown")
                if status == "success":
                    if log_callback:
                        log_callback("DiffSBDD process completed successfully")
                elif status == "timeout":
                    if log_callback:
                        log_callback("DiffSBDD process timed out after 1 hour")
                else:
                    error_msg = result_storage.get("error", "Unknown error")
                    if log_callback:
                        log_callback(f"DiffSBDD process failed: {error_msg}")
                
                # Note: stdout/stderr are now streamed in real-time, no need to log them again
                
                elapsed_time = time.time() - start_time
                if log_callback:
                    try:
                        log_callback(f"Finished generating ligands! (Time taken: {elapsed_time:.2f} seconds)\n")
                    except Exception:
                        print(f"Finished generating ligands! (Time taken: {elapsed_time:.2f} seconds)", file=sys.stderr)
                        
            except Exception as e:
                if log_callback:
                    try:
                        log_callback(f"Error in ligand generation process: {e}")
                    except Exception:
                        print(f"Error in ligand generation process: {e}", file=sys.stderr)
        
        thread = threading.Thread(target=run_process)
        thread.daemon = True  # Make thread a daemon so it doesn't block program exit
        thread.start()
        return thread
