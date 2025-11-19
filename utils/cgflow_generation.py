"""
CGFlow molecule generation wrapper.

Runs the finetuned CGFlow generator script in the designated conda environment
and writes outputs to a user-specified directory. The CGFlow script produces:
- samples.smi: SMILES of generated molecules
- samples.sdf: 3D structures docked within the pocket

This module exposes a threaded interface consistent with other generation utils.
"""

import os
import threading
from pathlib import Path
from typing import Optional, Callable, Dict, Any
import yaml

from .environment_manager import env_manager


def run_cgflow_generation(
    config_path: str,
    checkpoint_path: str,
    num_samples: int,
    out_dir: str,
    log_callback: Optional[Callable[[str], None]] = None,
    timeout: Optional[int] = 7200,
) -> threading.Thread:
    """
    Launch CGFlow generation using a fine-tuned checkpoint.

    Args:
        config_path: Path to CGFlow YAML config (e.g., src/cgflow/configs/opt/NS5.yaml)
        checkpoint_path: Path to CGFlow checkpoint (model_state.pt)
        num_samples: Number of molecules to generate (mapped to --n)
        out_dir: Output directory; CGFlow will create samples.smi and samples.sdf here
        log_callback: Optional logging callback
        timeout: Optional timeout in seconds (default: 2 hours)

    Returns:
        threading.Thread: The thread running the generation process.
    """
    # Normalize to absolute paths
    config_abs = os.path.abspath(config_path)
    ckpt_abs = os.path.abspath(checkpoint_path)
    out_abs = os.path.abspath(out_dir)

    os.makedirs(out_abs, exist_ok=True)

    # Detect if this is a boltzina checkpoint by checking the config file
    is_boltzina = False
    try:
        with open(config_abs, 'r') as f:
            config_data = yaml.safe_load(f)
            if config_data and 'boltzina' in config_data:
                is_boltzina = True
                if log_callback:
                    log_callback("Detected boltzina checkpoint - using generate_unidock_boltzina.py")
    except Exception as e:
        if log_callback:
            log_callback(f"Warning: Could not read config file to detect boltzina: {e}. Using default script.")

    # Build command and set working directory to CGFlow project root so its
    # internal relative paths (e.g., data/envs/...) resolve correctly.
    repo_root = Path(__file__).resolve().parents[1]
    cgflow_root = repo_root / "src" / "cgflow"

    if not cgflow_root.exists():
        # Fallback: keep repo root and use full script path (may fail if CGFlow assumes its own root)
        if log_callback:
            log_callback(f"Warning: CGFlow root not found at {cgflow_root}. Falling back to repo root.")
        run_cwd = str(repo_root)
        script_name = "generate_unidock_boltzina.py" if is_boltzina else "generate_unidock.py"
        script_path = f"src/cgflow/scripts/opt/{script_name}"
    else:
        run_cwd = str(cgflow_root)
        script_name = "generate_unidock_boltzina.py" if is_boltzina else "generate_unidock.py"
        script_path = f"scripts/opt/{script_name}"

    command = [
        "python",
        script_path,
        "--config", config_abs,
        "--ckpt", ckpt_abs,
        "--n", str(num_samples),
        "--out_dir", out_abs,
    ]

    result_storage: Dict[str, Any] = {}

    def _run():
        try:
            thread = env_manager.run_tool_async(
                tool_name="cgflow",
                command=command,
                cwd=run_cwd,
                timeout=timeout,
                log_callback=log_callback,
                result_storage=result_storage,
                stream_output=True,
            )
            thread.join()

            status = result_storage.get("status", "unknown")
            if log_callback:
                if status == "success":
                    log_callback("CGFlow generation completed successfully")
                elif status == "timeout":
                    log_callback(f"CGFlow generation timed out after {timeout} seconds")
                else:
                    log_callback(f"CGFlow generation failed: {result_storage.get('error', 'Unknown error')}")
        except Exception as e:
            if log_callback:
                log_callback(f"Error running CGFlow generation: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


