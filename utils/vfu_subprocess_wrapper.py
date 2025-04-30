import sys
import os
import argparse
import json
import traceback
from pathlib import Path

def run_vfu_from_wrapper():
    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(description="Wrapper to run VFU main function and capture output.")
    parser.add_argument("--vfu_dir", required=True, help="Absolute path to the VFU directory.")
    parser.add_argument("--program_choice", required=True)
    parser.add_argument("--scoring_function", required=True)
    parser.add_argument("--center_x", type=float, required=True)
    parser.add_argument("--center_y", type=float, required=True)
    parser.add_argument("--center_z", type=float, required=True)
    parser.add_argument("--size_x", type=float, required=True)
    parser.add_argument("--size_y", type=float, required=True)
    parser.add_argument("--size_z", type=float, required=True)
    parser.add_argument("--exhaustiveness", type=int, required=True)
    parser.add_argument("--smiles", required=True)
    parser.add_argument("--is_selfies", type=lambda x: (str(x).lower() == 'true'), default=False) # Handle boolean conversion
    parser.add_argument("--is_peptide", type=lambda x: (str(x).lower() == 'true'), default=False)  # Handle boolean conversion
    parser.add_argument("--receptor_path", help="Absolute path to the receptor file in VFU/config.") # Optional

    args = parser.parse_args()

    vfu_module_path = args.vfu_dir
    path_added = False
    results = {"pose_pred_out": None, "re_scored_values": None, "error": None}

    try:
        # --- VFU Import ---
        if vfu_module_path not in sys.path:
            sys.path.insert(0, vfu_module_path)
            path_added = True

        # Ensure VFU inputs/outputs directories exist relative to VFU path
        vfu_path = Path(vfu_module_path)
        (vfu_path / "inputs").mkdir(exist_ok=True)
        (vfu_path / "outputs").mkdir(exist_ok=True)

        # Dynamically import VFU's main function
        from run_vf_unity import main as vfu_main

        # --- VFU Execution ---
        pose_pred_out, re_scored_values = vfu_main(
            args.program_choice,
            args.scoring_function,
            args.center_x,
            args.center_y,
            args.center_z,
            args.size_x,
            args.size_y,
            args.size_z,
            args.exhaustiveness,
            args.smiles,
            args.is_selfies,
            args.is_peptide,
            args.receptor_path # Pass absolute path directly
        )
        results["pose_pred_out"] = pose_pred_out
        results["re_scored_values"] = re_scored_values

    except ImportError as e:
        results["error"] = f"ImportError: {e}. Check VFU path and dependencies. Traceback: {traceback.format_exc()}"
    except Exception as e:
        results["error"] = f"VFU Execution Error: {e}. Traceback: {traceback.format_exc()}"
    finally:
        # --- Cleanup ---
        if path_added:
            try:
                sys.path.remove(vfu_module_path)
            except ValueError:
                # Ignore if path wasn't found (shouldn't happen ideally)
                pass

    # --- Output Results as JSON ---
    # Use a custom encoder if necessary for complex objects returned by VFU,
    # but assuming standard dicts/lists/primitives for now.
    try:
        print(json.dumps(results))
    except TypeError as json_err:
        # Fallback if JSON serialization fails
        error_result = {"error": f"JSON Serialization Error: {json_err}. Could not serialize VFU results."}
        print(json.dumps(error_result))
        sys.exit(1) # Indicate error

if __name__ == "__main__":
    run_vfu_from_wrapper() 