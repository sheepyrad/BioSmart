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

def filter_by_pass_count(
    input_variants: List[Dict[str, Any]],
    rule_threshold: int = 13,
    structural_threshold: int = 27,
    smiles_key: str = 'smiles'
) -> tuple[List[Dict[str, Any]], pd.DataFrame | None]: # Modified return type hint
    """
    Filters a list of compounds based on the number of MedChem rules and structural alerts passed.
    
    Args:
        input_variants: A list of dictionaries, where each dictionary represents a compound
                          and must contain at least a key for the SMILES string.
        rule_threshold: The minimum number of rules a compound must pass.
        structural_threshold: The minimum number of structural/functional filters a compound must pass.
        smiles_key: The key in the input dictionaries corresponding to the SMILES string.
        
    Returns:
        A tuple containing:
          - List: The dictionaries of the variants that passed the filtering criteria.
          - DataFrame or None: A DataFrame containing all filter results and pass counts for
                                valid input molecules, or None if processing failed early.
    """
    if not input_variants:
        logger.warning("Received empty list for filtering. Returning empty list and None DataFrame.")
        return [], None

    logger.info(f"Starting MedChem filtering for {len(input_variants)} input compounds...")
    logger.info(f"Rule threshold >= {rule_threshold}, Structural threshold >= {structural_threshold}")

    # Extract SMILES and create a temporary DataFrame for processing
    smiles_list = [item.get(smiles_key) for item in input_variants]
    if not all(smiles_list):
        logger.error(f"Missing SMILES string for one or more input variants using key '{smiles_key}'. Cannot proceed.")
        # Optionally, filter out invalid entries and continue, but safer to stop.
        return [], None # Or raise ValueError

    temp_df = pd.DataFrame({smiles_key: smiles_list})

    # --- Generate Molecule Objects ---
    logger.info("Generating RDKit molecules from SMILES...")
    temp_df['mol'] = dm.parallelized(dm.to_mol, temp_df[smiles_key].tolist(), n_jobs=-1, progress=True)
    original_len = len(temp_df)
    temp_df = temp_df.dropna(subset=['mol'])
    if len(temp_df) < original_len:
        logger.warning(f"Dropped {original_len - len(temp_df)} compounds due to SMILES parsing errors.")

    if temp_df.empty:
        logger.warning("No valid molecules remaining after parsing. Returning empty list and empty DataFrame.")
        # Return empty dataframe matching potential structure but no rows
        return [], pd.DataFrame(columns=[smiles_key, 'mol', 'n_rules_pass', 'n_structural_pass']) 

    mols_list = temp_df["mol"].tolist()
    valid_smiles = temp_df[smiles_key].tolist() # Keep track of SMILES that were successfully parsed

    # --- Apply Filters and Rules ---
    logger.info(f"Applying filters and rules to {len(mols_list)} valid molecules...")
    n_jobs = -1
    filter_results = {}

    # === Rules ===
    logger.debug("--- Applying Medchem Rules ---")
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
            except Exception as e:
                logger.warning(f"  Rule '{rule_name}' failed: {e}. Assigning False.")
                filter_results[rule_name] = [False] * len(mols_list)
        else:
             logger.warning(f"Rule '{rule_name}' not found in medchem. Skipping.")


    # === Structural Alerts ===
    logger.debug("--- Applying Structural Alert Filters ---")
    structural_alerts_to_apply = [
        "Glaxo", "Dundee", "BMS", "PAINS", "SureChEMBL", "MLSMR", "Inpharmatica",
        "LINT", "Alarm-NMR", "AlphaScreen-Hitters", "GST-Hitters", "HIS-Hitters",
        "LuciferaseInhibitor", "DNABinder", "Chelator", "Frequent-Hitter",
        "Electrophilic", "Genotoxic-Carcinogenicity", "LD50-Oral",
        "Non-Genotoxic-Carcinogenicity", "Reactive-Unstable-Toxic", "Skin", "Toxicophore"
    ]
    for alert_name in structural_alerts_to_apply:
        try:
            # Assuming alert_filter returns True if NO alert is hit (i.e., molecule passes)
            # Check medchem documentation if this assumption is wrong.
            # Let's assume it returns True if it passes (no alert).
            results = mc.functional.alert_filter(
                mols=mols_list, alerts=[alert_name], n_jobs=n_jobs, progress=False
            )
            filter_results[alert_name] = results
        except Exception as e:
                logger.warning(f"  Alert '{alert_name}' failed: {e}. Assigning False.")
                filter_results[alert_name] = [False] * len(mols_list)

    # === Other Functional Filters ===
    logger.debug("--- Applying Other Functional Filters ---")
     # NIBR Filter - Assuming returns True if passes
    try:
        filter_results["NIBR"] = mc.functional.nibr_filter(
            mols=mols_list, n_jobs=n_jobs, max_severity=10, progress=False)
    except Exception as e:
        logger.warning(f"  NIBR filter failed: {e}. Assigning False.")
        filter_results["NIBR"] = [False] * len(mols_list)

    other_functional_filters = {
        "Bredt": (mc.functional.bredt_filter, {}),
        "MolecularGraph": (mc.functional.molecular_graph_filter, {"max_severity": 5}),
        # LillyDemerit uses SMILES, handle separately if needed or skip if mols are primary input
        # "LillyDemerit": (mc.functional.lilly_demerit_filter, {}),
        "NumStereo": (mc.functional.num_stereo_center_filter, {"max_stereo_centers": 4, "max_undefined_stereo_centers": 2}),
        "Halogenicity": (mc.functional.halogenicity_filter, {"thresh_F": 6, "thresh_Cl": 3, "thresh_Br": 3}),
    }
    for filter_key, (func, params) in other_functional_filters.items():
        try:
            # Assuming these functions return True if the molecule passes the filter
            filter_results[filter_key] = func(mols=mols_list, n_jobs=n_jobs, progress=False, **params)
        except Exception as e:
                logger.warning(f"  Filter '{filter_key}' failed: {e}. Assigning False.")
                filter_results[filter_key] = [False] * len(mols_list)


    # --- Aggregate Results ---
    logger.info("Aggregating filter results and calculating pass counts...")
    # Add results to the DataFrame
    for name, result_list in filter_results.items():
        if len(result_list) == len(temp_df):
            temp_df[name] = result_list
        else:
            logger.error(f"Length mismatch for filter '{name}'. Expected {len(temp_df)}, got {len(result_list)}. Skipping this filter.")
            # Assign False if length mismatch to avoid errors later
            if name not in temp_df.columns:
                 temp_df[name] = False


    # Categorize columns
    rule_cols = [col for col in rules_to_apply if col in temp_df.columns]
    # All other applied filters are considered 'structural/functional' for the count
    structural_cols = [col for col in filter_results.keys() if col not in rules_to_apply and col in temp_df.columns]

    logger.debug(f"Identified {len(rule_cols)} rule columns for count.")
    logger.debug(f"Identified {len(structural_cols)} structural/functional columns for count.")

    # Calculate pass counts
    if rule_cols:
        temp_df['n_rules_pass'] = temp_df[rule_cols].astype(bool).sum(axis=1)
    else:
        temp_df['n_rules_pass'] = 0
        logger.warning("No rule columns available for pass count.")

    if structural_cols:
        temp_df['n_structural_pass'] = temp_df[structural_cols].astype(bool).sum(axis=1)
    else:
        temp_df['n_structural_pass'] = 0
        logger.warning("No structural/functional columns available for pass count.")


    # --- Apply Thresholds ---
    passing_df = temp_df[
        (temp_df['n_rules_pass'] >= rule_threshold) &
        (temp_df['n_structural_pass'] >= structural_threshold)
    ].copy()

    passing_smiles = passing_df[smiles_key].tolist()
    logger.info(f"Filtering complete: {len(passing_smiles)} compounds passed the thresholds.")

    # --- Map back to original input format ---
    # Create a set for faster lookup
    passing_smiles_set = set(passing_smiles)
    filtered_variants_output = [
        item for item in input_variants if item.get(smiles_key) in passing_smiles_set
    ]

    logger.info(f"Returning {len(filtered_variants_output)} filtered variant dictionaries and the results DataFrame.")
    # Return both the filtered list and the full results dataframe
    return filtered_variants_output, temp_df # Modified return statement


def filter_by_generative_design(
    input_variants: List[Dict[str, Any]],
    smiles_key: str = 'smiles'
) -> tuple[List[Dict[str, Any]], pd.DataFrame | None]:
    """
    Filters compounds using only the generative design rules and keeps compounds
    that pass BOTH "rule_of_generative_design" and "rule_of_generative_design_strict".

    Args:
        input_variants: List of dictionaries containing at least a SMILES string under `smiles_key`.
        smiles_key: Key name for SMILES in the dictionaries.

    Returns:
        A tuple of (filtered_variants, results_df) where:
          - filtered_variants is a list of the original input dictionaries that passed both rules
          - results_df is a DataFrame with boolean columns for the two rules and pass counts
    """
    if not input_variants:
        logger.warning("Received empty list for generative design filtering. Returning empty list and None DataFrame.")
        return [], None

    logger.info(f"Starting Generative Design MedChem filtering for {len(input_variants)} input compounds...")

    # Extract SMILES and create a temporary DataFrame for processing
    smiles_list = [item.get(smiles_key) for item in input_variants]
    if not all(smiles_list):
        logger.error(f"Missing SMILES string for one or more input variants using key '{smiles_key}'. Cannot proceed.")
        return [], None

    temp_df = pd.DataFrame({smiles_key: smiles_list})

    # Generate RDKit molecules
    logger.info("Generating RDKit molecules from SMILES for generative design filtering...")
    temp_df['mol'] = dm.parallelized(dm.to_mol, temp_df[smiles_key].tolist(), n_jobs=-1, progress=True)
    original_len = len(temp_df)
    temp_df = temp_df.dropna(subset=['mol'])
    if len(temp_df) < original_len:
        logger.warning(f"Dropped {original_len - len(temp_df)} compounds due to SMILES parsing errors.")

    if temp_df.empty:
        logger.warning("No valid molecules remaining after parsing. Returning empty list and empty DataFrame.")
        return [], pd.DataFrame(columns=[smiles_key, 'mol', 'rule_of_generative_design', 'rule_of_generative_design_strict', 'n_rules_pass', 'n_structural_pass'])

    mols_list = temp_df['mol'].tolist()

    # Apply only the two generative design rules
    rules_to_apply = [
        "rule_of_generative_design",
        "rule_of_generative_design_strict",
    ]

    for rule_name in rules_to_apply:
        if hasattr(mc.rules.basic_rules, rule_name):
            rule_func = getattr(mc.rules.basic_rules, rule_name)
            try:
                temp_df[rule_name] = [rule_func(mol) for mol in mols_list]
            except Exception as e:
                logger.warning(f"  Rule '{rule_name}' failed: {e}. Assigning False.")
                temp_df[rule_name] = [False] * len(mols_list)
        else:
            logger.warning(f"Rule '{rule_name}' not found in medchem. Assigning False.")
            temp_df[rule_name] = [False] * len(mols_list)

    # Compute simple pass counts to maintain a compatible schema
    temp_df['n_rules_pass'] = temp_df[rules_to_apply].astype(bool).sum(axis=1)
    temp_df['n_structural_pass'] = 0  # Not applicable in this mode

    # Require BOTH rules to be True
    passing_df = temp_df[
        temp_df['rule_of_generative_design'].astype(bool) &
        temp_df['rule_of_generative_design_strict'].astype(bool)
    ].copy()

    passing_smiles = set(passing_df[smiles_key].tolist())
    filtered_variants_output = [item for item in input_variants if item.get(smiles_key) in passing_smiles]

    logger.info(f"Generative design filtering complete: {len(filtered_variants_output)} compounds passed both rules.")
    return filtered_variants_output, temp_df


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
    rules_to_apply = [ # Copy from filter_by_pass_count
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
                xticklabels=False,  # Hide compound labels on x-axis (can be too many)
                yticklabels=True,
                cbar=True,
                cmap=cmap,
                linewidths=0.1, # Add small lines between cells
                linecolor='lightgray',
                cbar_kws={'ticks': [0.25, 0.75]} # Center ticks in color segments
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

# Delete the old filter_compounds function and apply_medchem_filtering_to_variants
# As they are replaced by the updated filter_by_pass_count and direct calling from pipeline

# Keep filter_by_pass_count and generate_filter_plots defined above

