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

# Determine the absolute path to the VFU folder relative to this file
vfu_dir = Path(__file__).parent.parent / "src" / "VFU"
vfu_config_dir = vfu_dir / "config"
input_dir = Path(__file__).parent.parent / "input"
vfu_wrapper_script = Path(__file__).parent / "vfu_subprocess_wrapper.py"

# Get logger for this module
logger = logging.getLogger(__name__)

# Define a timeout for the VFU subprocess (e.g., 2 hours)
VFU_SUBPROCESS_TIMEOUT = 7200

def _run_vfu_subprocess(command, timeout, log_callback, result_storage):
    """Internal function to run the VFU wrapper script in a subprocess."""
    start_time = time.time()
    process = None
    results = {"pose_pred_out": None, "re_scored_values": None, "error": None, "stdout": "", "stderr": ""}

    # Ensure result_storage is updated even if exceptions occur early
    result_storage["data"] = results
    result_storage["status"] = "starting"

    try:
        log_callback(f"Executing VFU wrapper command: {' '.join(command)} in CWD={vfu_dir}")
        # Use a context manager for Popen
        with subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8', # Be explicit about encoding
            errors='replace',  # Handle potential decoding errors
            cwd=str(vfu_dir) # Set the current working directory for the subprocess
        ) as process:
            try:
                stdout_data, stderr_data = process.communicate(timeout=timeout)
                results["stdout"] = stdout_data
                results["stderr"] = stderr_data
                exit_code = process.returncode
                log_callback(f"VFU wrapper process finished with exit code: {exit_code}")

                if exit_code == 0:
                    try:
                        parsed_output = json.loads(stdout_data)
                        results["pose_pred_out"] = parsed_output.get("pose_pred_out")
                        results["re_scored_values"] = parsed_output.get("re_scored_values")
                        # Check for errors reported within the JSON output
                        if parsed_output.get("error"):
                            results["error"] = f"Error reported by VFU wrapper: {parsed_output['error']}"
                            log_callback(results["error"])
                            result_storage["status"] = "error"
                        else:
                            log_callback("VFU wrapper executed successfully and results parsed.")
                            result_storage["status"] = "success"
                    except json.JSONDecodeError as json_err:
                        results["error"] = f"Failed to parse JSON output from VFU wrapper: {json_err}. stdout: {stdout_data[:500]}..."
                        log_callback(results["error"])
                        result_storage["status"] = "error"
                    except Exception as parse_err: # Catch other potential parsing issues
                        results["error"] = f"Error processing VFU wrapper output: {parse_err}"
                        log_callback(results["error"])
                        result_storage["status"] = "error"
                else:
                    results["error"] = f"VFU wrapper process failed with exit code {exit_code}. stderr: {stderr_data[:500]}..."
                    log_callback(results["error"])
                    result_storage["status"] = "error"

            except subprocess.TimeoutExpired:
                log_callback(f"VFU wrapper process timed out after {timeout} seconds. Terminating...")
                process.terminate()
                try:
                    stdout_data, stderr_data = process.communicate(timeout=30) # Wait a bit
                except subprocess.TimeoutExpired:
                    log_callback("VFU wrapper did not terminate gracefully. Killing...")
                    process.kill()
                    stdout_data, stderr_data = process.communicate()

                results["stdout"] = stdout_data
                results["stderr"] = stderr_data
                results["error"] = f"VFU wrapper process timed out after {timeout} seconds."
                log_callback(results["error"])
                result_storage["status"] = "error"

    except FileNotFoundError:
        results["error"] = f"Error: Could not find python interpreter or wrapper script '{vfu_wrapper_script}'."
        log_callback(results["error"])
        result_storage["status"] = "error"
    except Exception as e:
        # Catch broader errors during subprocess setup/execution
        error_traceback = traceback.format_exc()
        results["error"] = f"Error running VFU subprocess: {e}. Traceback: {error_traceback}"
        log_callback(results["error"])
        result_storage["status"] = "error"
        # Ensure process is terminated if started and an exception occurred
        if process and process.poll() is None:
            try: process.kill() # Kill directly if setup failed badly
            except Exception: pass
    finally:
        elapsed_time = time.time() - start_time
        log_callback(f"VFU subprocess execution attempt finished in {elapsed_time:.2f} seconds. Final status: {result_storage['status']}")
        # Update the central storage dictionary with the final results
        result_storage["data"] = results
        # Ensure status reflects final state
        if results["error"] and result_storage["status"] != "error":
             result_storage["status"] = "error"
        elif not results["error"] and result_storage["status"] == "starting": # Handle case where process finished instantly without error/success path
             result_storage["status"] = "success" # Assume success if no error logged

def redock_compound(compound_id, smiles, redock_params, receptor=None, log_callback=print):
    """
    Redock a compound using VF Unity by running a wrapper script in a subprocess.

    Args:
        compound_id: ID of the compound
        smiles: SMILES string of the compound
        redock_params: Tuple of redocking parameters
        receptor: Filename of the receptor file (should be in ./input directory)
        log_callback: Function to call for logging

    Returns:
        Tuple of (threading.Thread, dict): The thread running the VFU subprocess
                                           and a dictionary to store results asynchronously.
                                           The dict structure: {"status": "starting"|"success"|"error",
                                                              "data": {"pose_pred_out": ..., "re_scored_values": ..., "error": ...}}
    """
    if log_callback is None:
        log_callback = print

    log_callback(f"Preparing asynchronous redocking process for {compound_id}.")

    # Create a dictionary to store results asynchronously
    # Initialize status and data structure
    result_storage = {"status": "pending", "data": None}

    # --- VFU Path and Setup Checks ---
    if not vfu_dir.exists():
        error_msg = f"VFU directory not found at {vfu_dir}. Please ensure it exists."
        log_callback(error_msg)
        result_storage["status"] = "error"
        result_storage["data"] = {"error": error_msg}
        return None, result_storage # Return None for thread if setup fails

    if not vfu_wrapper_script.exists():
        error_msg = f"VFU wrapper script not found at {vfu_wrapper_script}."
        log_callback(error_msg)
        result_storage["status"] = "error"
        result_storage["data"] = {"error": error_msg}
        return None, result_storage

    # Ensure VFU config directory exists
    vfu_config_dir.mkdir(parents=True, exist_ok=True)

    (program_choice, scoring_function, center_x, center_y, center_z,
     size_x, size_y, size_z, exhaustiveness, is_selfies, is_peptide) = redock_params

    # --- Receptor Handling ---
    absolute_receptor_path_in_vfu_config = None
    if receptor:
        receptor_filename = Path(receptor).name # Use Path for robustness
        receptor_in_input = input_dir / receptor_filename
        receptor_in_vfu_config = vfu_config_dir / receptor_filename
        absolute_receptor_path_in_vfu_config = str(receptor_in_vfu_config.resolve())

        log_callback(f"Looking for receptor file: {receptor_filename} in input directory {input_dir}")

        if not receptor_in_input.exists():
            error_msg = f"Receptor file '{receptor_filename}' not found in input directory at {receptor_in_input}. Please place it there."
            log_callback(error_msg)
            result_storage["status"] = "error"
            result_storage["data"] = {"error": error_msg}
            return None, result_storage

        try:
            # Copy receptor from input to VFU/config if needed
            if not receptor_in_vfu_config.exists() or receptor_in_input.stat().st_mtime > receptor_in_vfu_config.stat().st_mtime:
                log_callback(f"Copying receptor from {receptor_in_input} to {receptor_in_vfu_config}")
                shutil.copy2(receptor_in_input, receptor_in_vfu_config)
                log_callback(f"Receptor copied successfully.")
            else:
                log_callback(f"Receptor already present in {receptor_in_vfu_config}")
        except Exception as e:
            error_msg = f"Error copying receptor file: {e}"
            log_callback(error_msg)
            result_storage["status"] = "error"
            result_storage["data"] = {"error": error_msg}
            return None, result_storage

    # --- Prepare Subprocess Command ---
    # Ensure scoring function is separated if passed like 'qvina+nnscore2'
    actual_program_choice = program_choice
    actual_scoring_function = scoring_function
    if '+' in program_choice:
        parts = program_choice.split('+')
        actual_program_choice = parts[0]
        if len(parts) > 1:
            actual_scoring_function = parts[1]

    command = [
        sys.executable, # Use the current Python interpreter
        str(vfu_wrapper_script.resolve()),
        "--vfu_dir", str(vfu_dir.resolve()),
        "--program_choice", actual_program_choice,
        "--scoring_function", actual_scoring_function,
        "--center_x", str(center_x),
        "--center_y", str(center_y),
        "--center_z", str(center_z),
        "--size_x", str(size_x),
        "--size_y", str(size_y),
        "--size_z", str(size_z),
        "--exhaustiveness", str(exhaustiveness),
        "--smiles", smiles,
        "--is_selfies", str(is_selfies), # Pass booleans as strings
        "--is_peptide", str(is_peptide)
    ]
    if absolute_receptor_path_in_vfu_config:
        command.extend(["--receptor_path", absolute_receptor_path_in_vfu_config])

    # --- Start Thread ---
    log_callback(f"Starting VFU subprocess thread for {compound_id}...")
    thread = threading.Thread(
        target=_run_vfu_subprocess,
        args=(command, VFU_SUBPROCESS_TIMEOUT, log_callback, result_storage)
    )
    thread.daemon = True # Allow main program to exit even if thread hangs (though timeout should prevent)
    thread.start()

    log_callback(f"VFU subprocess thread for {compound_id} started.")

    # Return the thread and the dictionary where results will be stored
    return thread, result_storage

# --- Removed old direct call logic ---