# medchem_filter.py
import os, re
import pandas as pd
import numpy as np
from rdkit import Chem
from rdkit import RDLogger
import medchem as mc
import logging
from pathlib import Path
import gc
import time
import datamol as dm
import warnings
from typing import List, Dict, Any
# Add plotting imports
import matplotlib
matplotlib.use('Agg') # Use Agg backend for non-interactive plotting
import matplotlib.pyplot as plt
import seaborn as sns

# Suppress RDKit warnings for cleaner output
RDLogger.DisableLog('rdApp.*')
warnings.filterwarnings("ignore", category=UserWarning, module='datamol')
warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger("MedChemFilter")
logger.propagate = True

# Helper functions for DataFrame pipe operations
def _add_molecule_objects(df: pd.DataFrame, smiles_key: str) -> pd.DataFrame:
    """Add molecule objects column to DataFrame."""
    df['mol'] = dm.parallelized(dm.to_mol, df[smiles_key].tolist(), n_jobs=-1, progress=True)
    return df

def _drop_invalid_molecules(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with invalid molecules."""
    return df.dropna(subset=['mol'])

def _calculate_pass_counts(df: pd.DataFrame, rule_cols: List[str], structural_cols: List[str]) -> pd.DataFrame:
    """Calculate pass counts for rules and structural filters."""
    df['n_rules_pass'] = df[rule_cols].astype(bool).sum(axis=1) if rule_cols else 0
    df['n_structural_pass'] = df[structural_cols].astype(bool).sum(axis=1) if structural_cols else 0
    return df

def _filter_by_thresholds(df: pd.DataFrame, rule_threshold: int, structural_threshold: int) -> pd.DataFrame:
    """Filter DataFrame by rule and structural thresholds."""
    return df[
        (df['n_rules_pass'] >= rule_threshold) &
        (df['n_structural_pass'] >= structural_threshold)
    ].copy()

def _yield_batches(items, batch_size: int):
    """
    Yield successive batches of size `batch_size` from `items` while preserving order.
    """
    for start_idx in range(0, len(items), batch_size):
        yield items[start_idx:start_idx + batch_size]

def _run_pass_count_on_batch(
    input_variants: List[Dict[str, Any]],
    rule_threshold: int,
    structural_threshold: int,
    smiles_key: str,
):
    """
    Execute pass-count MedChem filters on a single batch and return (filtered_variants, results_df).
    """
    if not input_variants:
        return [], pd.DataFrame(columns=[smiles_key, 'mol', 'n_rules_pass', 'n_structural_pass'])

    # Extract SMILES and create a temporary DataFrame for processing
    smiles_list = [item.get(smiles_key) for item in input_variants]
    if not all(smiles_list):
        return [], None

    # Create DataFrame and process using pipe
    temp_df = (
        pd.DataFrame({smiles_key: smiles_list})
        .pipe(_add_molecule_objects, smiles_key=smiles_key)
        .pipe(_drop_invalid_molecules)
    )
    
    if temp_df.empty:
        return [], pd.DataFrame(columns=[smiles_key, 'mol', 'n_rules_pass', 'n_structural_pass'])

    mols_list = temp_df["mol"].tolist()

    # --- Apply Filters and Rules ---
    n_jobs = -1
    filter_results = {}

    # === Rules ===
    rules_to_apply = [
        "rule_of_five", "rule_of_ghose", "rule_of_veber", "rule_of_reos",
        "rule_of_chemaxon_druglikeness", "rule_of_egan", "rule_of_pfizer_3_75",
        "rule_of_gsk_4_400", "rule_of_oprea", "rule_of_xu", "rule_of_zinc",
        "rule_of_leadlike_soft", "rule_of_druglike_soft",
        "rule_of_generative_design", "rule_of_generative_design_strict"
    ]
    for rule_name in rules_to_apply:
        if hasattr(mc.rules.basic_rules, rule_name):
            rule_func = getattr(mc.rules.basic_rules, rule_name)
            try:
                filter_results[rule_name] = [rule_func(mol) for mol in mols_list]
            except Exception:
                filter_results[rule_name] = [False] * len(mols_list)
        else:
            # Keep column alignment even if rule missing
            filter_results[rule_name] = [False] * len(mols_list)

    # === Structural Alerts ===
    structural_alerts_to_apply = [
        "Glaxo", "Dundee", "BMS", "PAINS", "SureChEMBL", "MLSMR", "Inpharmatica",
        "LINT", "Alarm-NMR", "AlphaScreen-Hitters", "GST-Hitters", "HIS-Hitters",
        "LuciferaseInhibitor", "DNABinder", "Chelator", "Frequent-Hitter",
        "Electrophilic", "Genotoxic-Carcinogenicity", "LD50-Oral",
        "Non-Genotoxic-Carcinogenicity", "Reactive-Unstable-Toxic", "Skin", "Toxicophore"
    ]
    for alert_name in structural_alerts_to_apply:
        try:
            results = mc.functional.alert_filter(
                mols=mols_list, alerts=[alert_name], n_jobs=n_jobs, progress=False
            )
            filter_results[alert_name] = results
        except Exception:
            filter_results[alert_name] = [False] * len(mols_list)

    # === Other Functional Filters ===
    try:
        filter_results["NIBR"] = mc.functional.nibr_filter(
            mols=mols_list, n_jobs=n_jobs, max_severity=10, progress=False)
    except Exception:
        filter_results["NIBR"] = [False] * len(mols_list)

    other_functional_filters = {
        "Bredt": (mc.functional.bredt_filter, {}),
        "MolecularGraph": (mc.functional.molecular_graph_filter, {"max_severity": 5}),
        "NumStereo": (mc.functional.num_stereo_center_filter, {"max_stereo_centers": 4, "max_undefined_stereo_centers": 2}),
        "Halogenicity": (mc.functional.halogenicity_filter, {"thresh_F": 6, "thresh_Cl": 3, "thresh_Br": 3}),
    }
    for filter_key, (func, params) in other_functional_filters.items():
        try:
            filter_results[filter_key] = func(mols=mols_list, n_jobs=n_jobs, progress=False, **params)
        except Exception:
            filter_results[filter_key] = [False] * len(mols_list)

    # --- Aggregate Results ---
    for name, result_list in filter_results.items():
        if len(result_list) == len(temp_df):
            temp_df[name] = result_list
        else:
            temp_df[name] = False

    # Categorize columns
    rule_cols = [col for col in rules_to_apply if col in temp_df.columns]
    structural_cols = [col for col in filter_results.keys() if col not in rules_to_apply and col in temp_df.columns]

    # Calculate pass counts and filter using pipe
    temp_df = temp_df.pipe(_calculate_pass_counts, rule_cols=rule_cols, structural_cols=structural_cols)
    passing_df = temp_df.pipe(_filter_by_thresholds, rule_threshold=rule_threshold, structural_threshold=structural_threshold)

    passing_smiles_set = set(passing_df[smiles_key].tolist())
    filtered_variants_output = [
        item for item in input_variants if item.get(smiles_key) in passing_smiles_set
    ]

    return filtered_variants_output, temp_df

def filter_by_pass_count(
    input_variants: List[Dict[str, Any]],
    rule_threshold: int = 13,
    structural_threshold: int = 27,
    smiles_key: str = 'smiles'
) -> tuple[List[Dict[str, Any]], pd.DataFrame | None]: # Modified return type hint
    """
    Filters a list of compounds based on the number of MedChem rules and structural alerts passed.
    Processes inputs in batches of 2500 molecules to reduce memory usage and then concatenates results.
    """
    if not input_variants:
        logger.warning("Received empty list for filtering. Returning empty list and None DataFrame.")
        return [], None

    total = len(input_variants)
    logger.info(f"Starting MedChem filtering for {total} input compounds in 2500-sized batches...")
    logger.info(f"Rule threshold >= {rule_threshold}, Structural threshold >= {structural_threshold}")

    batch_size = 2500
    all_filtered_variants: List[Dict[str, Any]] = []
    results_frames: List[pd.DataFrame] = []

    for batch_index, batch in enumerate(_yield_batches(input_variants, batch_size), start=1):
        start = (batch_index - 1) * batch_size
        end = min(start + len(batch), total)
        logger.info(f"Processing MedChem batch {batch_index}: items {start + 1}-{end} of {total}")

        filtered_batch, df_batch = _run_pass_count_on_batch(
            input_variants=batch,
            rule_threshold=rule_threshold,
            structural_threshold=structural_threshold,
            smiles_key=smiles_key,
        )

        if filtered_batch:
            all_filtered_variants.extend(filtered_batch)
        if df_batch is not None and not df_batch.empty:
            results_frames.append(df_batch)

        # Explicit GC to keep memory bounded on large runs
        gc.collect()

    combined_df = pd.concat(results_frames, ignore_index=True) if results_frames else None

    logger.info(
        f"MedChem filtering complete across batches: {len(all_filtered_variants)} compounds passed out of {total}."
    )
    return all_filtered_variants, combined_df


def _run_generative_design_on_batch(
    input_variants: List[Dict[str, Any]],
    smiles_key: str,
    ):
    if not input_variants:
        return [], pd.DataFrame(columns=[smiles_key, 'mol', 'rule_of_generative_design', 'rule_of_generative_design_strict', 'n_rules_pass', 'n_structural_pass'])

    smiles_list = [item.get(smiles_key) for item in input_variants]
    if not all(smiles_list):
        return [], None

    # Create DataFrame and process using pipe
    temp_df = (
        pd.DataFrame({smiles_key: smiles_list})
        .pipe(_add_molecule_objects, smiles_key=smiles_key)
        .pipe(_drop_invalid_molecules)
    )
    
    if temp_df.empty:
        return [], pd.DataFrame(columns=[smiles_key, 'mol', 'rule_of_generative_design', 'rule_of_generative_design_strict', 'n_rules_pass', 'n_structural_pass'])

    mols_list = temp_df['mol'].tolist()
    rules_to_apply = ["rule_of_generative_design", "rule_of_generative_design_strict"]
    for rule_name in rules_to_apply:
        if hasattr(mc.rules.basic_rules, rule_name):
            rule_func = getattr(mc.rules.basic_rules, rule_name)
            try:
                temp_df[rule_name] = [rule_func(mol) for mol in mols_list]
            except Exception:
                temp_df[rule_name] = [False] * len(mols_list)
        else:
            temp_df[rule_name] = [False] * len(mols_list)

    # Calculate pass counts and filter using pipe
    temp_df = temp_df.pipe(_calculate_pass_counts, rule_cols=rules_to_apply, structural_cols=[])
    temp_df['n_structural_pass'] = 0
    
    passing_df = temp_df[
        temp_df['rule_of_generative_design'].astype(bool) &
        temp_df['rule_of_generative_design_strict'].astype(bool)
    ].copy()

    passing_smiles = set(passing_df[smiles_key].tolist())
    filtered_variants_output = [item for item in input_variants if item.get(smiles_key) in passing_smiles]
    return filtered_variants_output, temp_df

def filter_by_generative_design(
    input_variants: List[Dict[str, Any]],
    smiles_key: str = 'smiles'
) -> tuple[List[Dict[str, Any]], pd.DataFrame | None]:
    """
    Filters compounds using only the generative design rules and keeps compounds
    that pass BOTH "rule_of_generative_design" and "rule_of_generative_design_strict".
    Processes inputs in batches of 2500 molecules to reduce memory usage and then concatenates results.
    """
    if not input_variants:
        logger.warning("Received empty list for generative design filtering. Returning empty list and None DataFrame.")
        return [], None

    total = len(input_variants)
    logger.info(f"Starting Generative Design MedChem filtering for {total} input compounds in 2500-sized batches...")

    batch_size = 2500
    all_filtered_variants: List[Dict[str, Any]] = []
    results_frames: List[pd.DataFrame] = []

    for batch_index, batch in enumerate(_yield_batches(input_variants, batch_size), start=1):
        start = (batch_index - 1) * batch_size
        end = min(start + len(batch), total)
        logger.info(f"Processing Generative Design batch {batch_index}: items {start + 1}-{end} of {total}")

        filtered_batch, df_batch = _run_generative_design_on_batch(batch, smiles_key)
        if filtered_batch:
            all_filtered_variants.extend(filtered_batch)
        if df_batch is not None and not df_batch.empty:
            results_frames.append(df_batch)
        gc.collect()

    combined_df = pd.concat(results_frames, ignore_index=True) if results_frames else None
    logger.info(
        f"Generative design filtering complete across batches: {len(all_filtered_variants)} compounds passed out of {total}."
    )
    return all_filtered_variants, combined_df


def generate_filter_plots(results_df: pd.DataFrame, plots_dir: Path):
    """
    Generates and saves heatmap and histograms for MedChem filter results.

    Args:
        results_df: DataFrame containing filter results (True/False) and pass counts
                    ('n_rules_pass', 'n_structural_pass'). Index should represent compounds.
        plots_dir: Path object for the directory where plots will be saved.
    """
    if results_df is None or results_df.empty:
        logger.warning("Received empty or None DataFrame for plotting. Skipping plot generation.")
        return
        
    logger.info(f"Generating filter plots in {plots_dir}...")
    plots_dir.mkdir(parents=True, exist_ok=True)

    # Identify rule and structural columns present in the DataFrame
    # These should match the categorization in filter_by_pass_count
    all_cols = set(results_df.columns)
    rules_to_apply = [
        "rule_of_five", "rule_of_ghose", "rule_of_veber", "rule_of_reos",
        "rule_of_chemaxon_druglikeness", "rule_of_egan", "rule_of_pfizer_3_75",
        "rule_of_gsk_4_400", "rule_of_oprea", "rule_of_xu", "rule_of_zinc",
        "rule_of_leadlike_soft", "rule_of_druglike_soft",
        "rule_of_generative_design", "rule_of_generative_design_strict"
    ]
    # Structural cols are everything else that isn't smiles, mol, or pass counts
    structural_cols = list(all_cols - set(rules_to_apply) - {'smiles', 'mol', 'n_rules_pass', 'n_structural_pass'})
    rule_cols = [col for col in rules_to_apply if col in all_cols]

    all_filter_cols = sorted(rule_cols + structural_cols) # Combine and sort for heatmap

    if not all_filter_cols:
        logger.warning("No filter result columns found in DataFrame. Skipping heatmap generation.")
    else:
        # --- Generate Heatmap ---
        try:
            logger.info("Generating filter heatmap...")
            # Prepare data for heatmap (transpose)
            # Ensure boolean type for heatmap
            heatmap_data = results_df[all_filter_cols].astype(bool).T 

            # Adjust figsize dynamically - make wider if many filters, taller if many compounds
            fig_width = max(12, len(results_df)*0.01) # Ensure minimum width
            fig_height = max(8, len(all_filter_cols)*0.3) # Taller based on number of filters
            
            f_h, ax_h = plt.subplots(figsize=(fig_width, fig_height ), constrained_layout=True)
            cmap = matplotlib.colors.ListedColormap(["#EF6262", "#1D5B79"], None) # Red=Fail, Blue=Pass

            sns.heatmap(
                heatmap_data,
                annot=False,
                ax=ax_h,
                xticklabels=False, 
                yticklabels=True,
                cbar=True,
                cmap=cmap,
                linewidths=0.1,
                linecolor='lightgray',
                cbar_kws={'ticks': [0.25, 0.75]}
            )

            # Configure color bar
            cbar = ax_h.collections[0].colorbar
            cbar.set_ticklabels(["Fail", "Pass"])

            # Add percentage labels to y-axis (filters)
            new_ylabels = []
            for t in ax_h.get_yticklabels():
                filter_name = t.get_text()
                if filter_name in results_df.columns:
                    # Ensure boolean conversion before sum for safety
                    perc = results_df[filter_name].astype(bool).sum() / len(results_df) * 100
                    new_ylabels.append(f"{filter_name} ({perc:.0f}%)")
                else:
                    new_ylabels.append(filter_name) # Should not happen if cols are correct
            ax_h.set_yticklabels(new_ylabels)

            ax_h.set_xlabel(f"Compounds (n={len(results_df)})", fontsize=12)
            ax_h.set_ylabel("MedChem Filters & Rules", fontsize=14)
            ax_h.set_title("MedChem Filter Pass/Fail Heatmap", fontsize=16)
            
            # Ensure plot elements fit
            # plt.tight_layout() # Removed - constrained_layout=True handles this

            heatmap_path = plots_dir / "filter_heatmap.png"
            plt.savefig(heatmap_path, dpi=150, bbox_inches='tight')
            plt.close(f_h) # Close figure to free memory
            logger.info(f"Saved heatmap to {heatmap_path}")
            # Explicitly delete large objects and collect garbage
            del heatmap_data, f_h, ax_h, cbar
            gc.collect()

        except Exception as e:
            logger.error(f"Failed to generate heatmap: {e}", exc_info=True)
            if 'f_h' in locals() and plt.fignum_exists(f_h.number): plt.close(f_h) # Ensure plot is closed on error
            gc.collect()


    # --- Generate Histograms ---
    # Rules Pass Count Histogram
    if 'n_rules_pass' in results_df.columns and not results_df['n_rules_pass'].empty:
        try:
            logger.info("Generating rules pass count histogram...")
            f_r, ax_r = plt.subplots(figsize=(10, 6))
            sns.histplot(data=results_df, x='n_rules_pass', discrete=True, ax=ax_r, stat="count") # Explicitly use count
            max_rules = len(rule_cols) if rule_cols else results_df['n_rules_pass'].max()
            ax_r.set_xticks(np.arange(0, max_rules + 1, step=max(1, max_rules // 10))) # Adjust ticks
            ax_r.set_title('Distribution of Passed MedChem Rules')
            ax_r.set_xlabel(f'Number of Rules Passed (out of {max_rules})')
            ax_r.set_ylabel('Number of Compounds')
            plt.tight_layout()
            rules_hist_path = plots_dir / "rules_pass_histogram.png"
            plt.savefig(rules_hist_path, dpi=100, bbox_inches='tight')
            plt.close(f_r)
            logger.info(f"Saved rules histogram to {rules_hist_path}")
            del f_r, ax_r
            gc.collect()
        except Exception as e:
            logger.error(f"Failed to generate rules histogram: {e}", exc_info=True)
            if 'f_r' in locals() and plt.fignum_exists(f_r.number): plt.close(f_r)
            gc.collect()
    else:
        logger.warning("Column 'n_rules_pass' not found or empty. Skipping rules histogram.")

    # Structural Pass Count Histogram
    if 'n_structural_pass' in results_df.columns and not results_df['n_structural_pass'].empty:
        try:
            logger.info("Generating structural/functional pass count histogram...")
            f_s, ax_s = plt.subplots(figsize=(10, 6))
            sns.histplot(data=results_df, x='n_structural_pass', discrete=True, ax=ax_s, stat="count") # Explicitly use count
            max_struct = len(structural_cols) if structural_cols else results_df['n_structural_pass'].max()
            ax_s.set_xticks(np.arange(0, max_struct + 1, step=max(1, max_struct // 10))) # Adjust ticks
            ax_s.set_title('Distribution of Passed Structural/Functional Filters')
            ax_s.set_xlabel(f'Number of Filters Passed (out of {max_struct})')
            ax_s.set_ylabel('Number of Compounds')
            plt.tight_layout()
            struct_hist_path = plots_dir / "structural_pass_histogram.png"
            plt.savefig(struct_hist_path, dpi=100, bbox_inches='tight')
            plt.close(f_s)
            logger.info(f"Saved structural histogram to {struct_hist_path}")
            del f_s, ax_s
            gc.collect()
        except Exception as e:
            logger.error(f"Failed to generate structural histogram: {e}", exc_info=True)
            if 'f_s' in locals() and plt.fignum_exists(f_s.number): plt.close(f_s)
            gc.collect()
    else:
         logger.warning("Column 'n_structural_pass' not found or empty. Skipping structural histogram.")

    logger.info("Finished generating filter plots.")


