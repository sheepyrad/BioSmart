"""
ChemAP wrapper utilities.

This module provides helper functions to run the ChemAP FDA-approval predictor
on a list of SMILES and filter variants accordingly. It relies on the existing
EnvironmentManager to run the external tool inside its conda environment.
"""

import os
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import pandas as pd

from utils.environment_manager import env_manager

# Helper functions for DataFrame pipe operations
def _filter_approved_smiles(df: pd.DataFrame) -> pd.DataFrame:
    """Filter DataFrame to only approved SMILES (ChemAP_pred == 1)."""
    return df[df.get("ChemAP_pred", 0) == 1]

def _extract_smiles_set(df: pd.DataFrame) -> set:
    """Extract SMILES set from DataFrame."""
    return set(df["SMILES"].astype(str).tolist())


def _ensure_directory(path: Path) -> None:
    """Create a directory if it does not exist."""
    path.mkdir(parents=True, exist_ok=True)


def run_chemap(
    smiles_list: List[str],
    chemap_dir: Path,
    output_tag: str,
    round_dir: Path,
    log_callback: Callable[[str], None] = None,
) -> Tuple[pd.DataFrame, Path]:
    """
    Run ChemAP on a list of SMILES and return the predictions DataFrame.

    Args:
        smiles_list: List of SMILES strings to evaluate.
        chemap_dir: Path to the ChemAP tool directory (e.g., src/ChemAP).
        output_tag: Base name for the ChemAP output CSV (without suffix).
        round_dir: Round-specific directory to store copies of inputs/outputs.
        log_callback: Optional logger callback.

    Returns:
        A tuple of (predictions_df, predictions_csv_path).
        predictions_df contains at least columns ['SMILES', 'ChemAP_pred'].
    """
    if log_callback is None:
        log_callback = lambda m: None

    dataset_dir = chemap_dir / "dataset"
    results_dir = chemap_dir / "results"
    _ensure_directory(dataset_dir)
    _ensure_directory(results_dir)

    # Prepare input CSV with required schema: one column named 'SMILES'
    input_basename = f"{output_tag}.csv"
    input_csv_for_chemap = dataset_dir / input_basename
    pd.DataFrame({"SMILES": smiles_list}).to_csv(input_csv_for_chemap, index=False)
    log_callback(f"ChemAP input written: {input_csv_for_chemap}")

    # Run ChemAP: outputs to ./results/{output_tag}_prediction.csv under chemap_dir
    # Ensure 'src' package is importable by setting PYTHONPATH to project root
    project_root = chemap_dir.parents[1]
    shell_cmd = (
        f"PYTHONPATH='{project_root}' python ChemAP.py --data_type custom --input_file {input_basename} --output {output_tag}"
    )
    cmd = ["bash", "-lc", shell_cmd]

    result = env_manager.run_tool(
        tool_name="chemap",
        command=cmd,
        cwd=str(chemap_dir),
        timeout=3600,
        capture_output=True,
        text=True,
        check=False,
        log_callback=log_callback,
        stream_output=True,
    )

    if result.returncode != 0:
        log_callback(
            f"ChemAP execution failed with exit code {result.returncode}. Stderr: {result.stderr}"
        )
        raise RuntimeError("ChemAP execution failed")

    predictions_csv = results_dir / f"{output_tag}_prediction.csv"
    if not predictions_csv.exists() or predictions_csv.stat().st_size == 0:
        raise FileNotFoundError(
            f"ChemAP predictions not found at {predictions_csv}. Check ChemAP outputs."
        )

    # Read predictions
    pred_df = pd.read_csv(predictions_csv)

    # Copy artifacts into the round directory for provenance
    chemap_round_dir = round_dir / "chemap"
    _ensure_directory(chemap_round_dir)
    try:
        # Copy input and output for this round
        shutil.copy2(input_csv_for_chemap, chemap_round_dir / input_basename)
        shutil.copy2(predictions_csv, chemap_round_dir / predictions_csv.name)
    except Exception:
        # Non-fatal if copy fails
        pass

    return pred_df, predictions_csv


def chemap_filter_variants(
    variants: List[Dict],
    round_dir: Path,
    log_callback: Callable[[str], None] = None,
) -> Tuple[List[Dict], pd.DataFrame]:
    """
    Filter variants using ChemAP predictions, keeping only those predicted as approved (ChemAP_pred == 1).

    Args:
        variants: List of variant dicts; each must include key 'smiles'.
        round_dir: Directory for the current round to store I/O artifacts.
        log_callback: Optional logger callback.

    Returns:
        A tuple of (filtered_variants, predictions_df).
    """
    if log_callback is None:
        log_callback = lambda m: None

    if not variants:
        return [], pd.DataFrame(columns=["SMILES", "ChemAP_pred"])  # nothing to do

    # Resolve ChemAP tool directory relative to project root
    project_root = Path(__file__).resolve().parents[1]
    chemap_dir = project_root / "src" / "ChemAP"

    smiles_list = [v["smiles"] for v in variants if v.get("smiles")]
    output_tag = f"round_{Path(round_dir).name}_chemap"

    log_callback(
        f"Running ChemAP on {len(smiles_list)} SMILES with output tag '{output_tag}'"
    )

    pred_df, _ = run_chemap(
        smiles_list=smiles_list,
        chemap_dir=chemap_dir,
        output_tag=output_tag,
        round_dir=round_dir,
        log_callback=log_callback,
    )

    # Determine approved SMILES using pipe
    approved_smiles = (
        pred_df
        .pipe(_filter_approved_smiles)
        .pipe(_extract_smiles_set)
    )

    approved_variants = [v for v in variants if v.get("smiles") in approved_smiles]

    log_callback(
        f"ChemAP filtering retained {len(approved_variants)}/{len(variants)} variants as approved"
    )

    return approved_variants, pred_df


