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
from rdkit import Chem

# Define a timeout for the subprocess (e.g., 2 hours)
SUBPROCESS_TIMEOUT = 7200 

def run_pocket2mol(pdbfile, center, bbox_size, out_dir, n_samples, log_callback=None):
    """
    Run the Pocket2Mol model for ligand generation.
    
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
    
    # Change to the directory containing Pocket2Mol
    pocket2mol_dir = os.path.join(current_dir, "src", "Pocket2Mol")
    
    # Format center coordinates as a comma-separated string
    center_str = f"{center[0]},{center[1]},{center[2]}"
    
    # Define config file paths
    config_path = os.path.join(pocket2mol_dir, "configs", "sample_for_pdb.yml")
    config_file_name = os.path.basename(config_path)
    temp_config_path = os.path.join(pocket2mol_dir, "configs", f"temp_{config_file_name}")
    final_config_to_use = config_path # Default to original config

    # Load, modify, and save the config file if n_samples needs changing
    try:
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
        
        # Check if modification is needed in the correct location (avoids unnecessary writes)
        # Ensure the 'sample' key exists and 'num_samples' within it needs updating
        if 'sample' in config_data and config_data['sample'].get('num_samples') != n_samples:
            config_data['sample']['num_samples'] = n_samples
            with open(temp_config_path, 'w') as f:
                yaml.dump(config_data, f, default_flow_style=False)
            final_config_to_use = temp_config_path # Use the modified temp config
            if log_callback:
                log_callback(f"Using temporary config {temp_config_path} with num_samples set to {n_samples}")
        else:
             if log_callback:
                log_callback(f"Using original config {config_path} (num_samples already {n_samples})")

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

    # Construct the command using the final config path
    # Removed explicit conda activate - assuming parent environment is correct
    command = (
        f"cd {pocket2mol_dir} && python sample_for_pdb.py "
        f"--pdb_path {pdbfile_path} "
        f"--center {center_str} "
        f"--bbox_size {bbox_size} "
        f"--config {final_config_to_use} "  # Use the determined config path
        f"--outdir {out_dir_path}"
    )
    
    if log_callback:
        log_callback(f"Executing Pocket2Mol: {command}\nGenerating molecules...\n")

    def run_process():
        start_time = time.time()
        process = None
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        
        try:
            # Try to increase the soft limit for file descriptors for this process
            try:
                soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                if log_callback:
                    log_callback(f"Current file descriptor limits: soft={soft}, hard={hard}")
                target_soft = min(hard, 4096) # Or potentially higher if needed
                resource.setrlimit(resource.RLIMIT_NOFILE, (target_soft, hard))
                new_soft, new_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                if log_callback:
                    log_callback(f"Successfully set file descriptor limit: soft={new_soft}, hard={new_hard}")
            except Exception as e:
                if log_callback:
                    log_callback(f"Warning: Could not set file descriptor limit: {e}")
            
            # Use a with statement to ensure proper cleanup
            with subprocess.Popen(
                command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            ) as process:
                # Create a safe logging function that won't throw exceptions
                def safe_log(message):
                    try:
                        if log_callback and message.strip():
                            log_callback(message.strip())
                    except Exception as e:
                        # If logging fails, write to a local buffer instead
                        print(f"Logging error: {e}", file=sys.stderr)
                        print(f"Message: {message}", file=sys.stderr)
                
                # Use communicate to read output and wait for completion with timeout
                stdout_data, stderr_data = None, None
                exit_code = None
                try:
                    stdout_data, stderr_data = process.communicate(timeout=SUBPROCESS_TIMEOUT)
                    exit_code = process.returncode
                    safe_log(f"Pocket2Mol process finished with exit code: {exit_code}")
                except subprocess.TimeoutExpired:
                    safe_log(f"Pocket2Mol process timed out after {SUBPROCESS_TIMEOUT} seconds. Terminating...")
                    process.terminate() # Ask nicely first
                    try:
                        process.wait(timeout=30) # Wait a bit for termination
                    except subprocess.TimeoutExpired:
                        safe_log("Process did not terminate gracefully. Killing...")
                        process.kill() # Force kill
                    exit_code = -1 # Indicate timeout/termination
                    safe_log("Pocket2Mol process terminated due to timeout.")
                
                # --- Log captured stdout/stderr --- 
                if stdout_data:
                    safe_log("--- Pocket2Mol stdout ---")
                    for line in stdout_data.splitlines():
                        safe_log(line)
                    safe_log("--- End Pocket2Mol stdout ---")
                if stderr_data:
                    safe_log("--- Pocket2Mol stderr ---")
                    for line in stderr_data.splitlines():
                        safe_log(line)
                    safe_log("--- End Pocket2Mol stderr ---")
                
                # --- Read Pocket2Mol's own log file (only if process started successfully) --- 
                if process.pid and exit_code is not None: # Check if process launched and finished/timed out
                    try:
                        # Find the specific output directory created by Pocket2Mol inside out_dir_path
                        # It usually starts with 'temp_sample_for_pdb_' followed by the PDB name
                        p2m_output_dirs = list(Path(out_dir_path).glob(f"temp_sample_for_pdb_{Path(pdbfile_path).stem}*"))
                        if p2m_output_dirs:
                            p2m_log_dir = sorted(p2m_output_dirs)[-1] # Get the latest one if multiple exist
                            p2m_log_file = p2m_log_dir / "log.txt"
                            if p2m_log_file.exists():
                                safe_log("--- Start Pocket2Mol Internal Log --- ")
                                with open(p2m_log_file, 'r') as f_log:
                                    for log_line in f_log:
                                        safe_log(log_line.strip()) # Log each line
                                safe_log("--- End Pocket2Mol Internal Log --- ")
                            else:
                                safe_log(f"Pocket2Mol log file not found at: {p2m_log_file}")
                        else:
                            safe_log(f"Could not find Pocket2Mol output subdirectory in: {out_dir_path}")
                    except Exception as log_read_e:
                        safe_log(f"Error reading Pocket2Mol log file: {log_read_e}")
                # --- End Reading Log File ---
            
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
            
            # Ensure process is terminated if an exception occurs
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except:
                    try:
                        process.kill()
                    except:
                        pass
        
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

def combine_pocket2mol_outputs(output_dir, target_sdf):
    """
    Combine Pocket2Mol output SDF files into a single SDF file.
    
    Args:
        output_dir (str): Pocket2Mol output directory
        target_sdf (str): Target SDF file path
        
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

def run_ligand_generation(checkpoint=None, pdbfile=None, outfile=None, resi_list=None, 
                          n_samples=100, sanitize=True, log_callback=None, model="diffsbdd",
                          center=None, bbox_size=None, out_dir=None):
    """
    Run ligand generation using either DiffSBDD or Pocket2Mol model.
    
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
        
        command = (
            f"cd {diffsbdd_dir} && python generate_ligands.py {checkpoint_path} "
            f"--pdbfile {pdbfile_path} --outfile {outfile_path} --resi_list {' '.join(resi_list)} "
            f"--n_samples {n_samples} {'--sanitize' if sanitize else ''}"
        )
        
        if log_callback:
            log_callback(f"Executing DiffSBDD: {command}\nGenerating {n_samples} ligands...\n")

        def run_process():
            start_time = time.time()
            process = None
            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            
            try:
                # Try to increase the soft limit for file descriptors for this process
                try:
                    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                    resource.setrlimit(resource.RLIMIT_NOFILE, (min(hard, 4096), hard))
                    if log_callback:
                        log_callback(f"Set file descriptor limit to {min(hard, 4096)}")
                except Exception as e:
                    if log_callback:
                        log_callback(f"Warning: Could not set file descriptor limit: {e}")
                
                # Use a with statement to ensure proper cleanup
                with subprocess.Popen(
                    command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                    text=True, close_fds=True, bufsize=1
                ) as process:
                    # Create a safe logging function that won't throw exceptions
                    def safe_log(message):
                        try:
                            if log_callback and message.strip():
                                log_callback(message.strip())
                        except Exception as e:
                            # If logging fails, write to a local buffer instead
                            print(f"Logging error: {e}", file=sys.stderr)
                            print(f"Message: {message}", file=sys.stderr)
                    
                    # Read output in chunks to avoid buffer issues
                    for line in iter(process.stdout.readline, ''):
                        stdout_buffer.write(line)
                        safe_log(line)
                    
                    # Read error output
                    for err in iter(process.stderr.readline, ''):
                        stderr_buffer.write(err)
                        safe_log(err)
                    
                    # Wait for process to complete with timeout
                    try:
                        process.wait(timeout=3600)  # 1 hour timeout
                    except subprocess.TimeoutExpired:
                        safe_log("Process timed out after 1 hour, terminating...")
                        try:
                            process.terminate()
                            process.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            safe_log("Process did not terminate gracefully, killing...")
                            process.kill()
                
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
                
                # Ensure process is terminated if an exception occurs
                if process and process.poll() is None:
                    try:
                        process.terminate()
                        process.wait(timeout=5)
                    except:
                        try:
                            process.kill()
                        except:
                            pass
        
        thread = threading.Thread(target=run_process)
        thread.daemon = True  # Make thread a daemon so it doesn't block program exit
        thread.start()
        return thread
