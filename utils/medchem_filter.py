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
) -> List[Dict[str, Any]]:
    """
    Filters a list of compounds based on the number of MedChem rules and structural alerts passed.
    
    Args:
        input_variants: A list of dictionaries, where each dictionary represents a compound
                          and must contain at least a key for the SMILES string.
        rule_threshold: The minimum number of rules a compound must pass.
        structural_threshold: The minimum number of structural/functional filters a compound must pass.
        smiles_key: The key in the input dictionaries corresponding to the SMILES string.
        
    Returns:
        A list containing the dictionaries of the variants that passed the filtering criteria.
        Returns an empty list if input is empty or no compounds pass.
    """
    if not input_variants:
        logger.warning("Received empty list for filtering. Returning empty list.")
        return []

    logger.info(f"Starting MedChem filtering for {len(input_variants)} input compounds...")
    logger.info(f"Rule threshold >= {rule_threshold}, Structural threshold >= {structural_threshold}")

    # Extract SMILES and create a temporary DataFrame for processing
    smiles_list = [item.get(smiles_key) for item in input_variants]
    if not all(smiles_list):
        logger.error(f"Missing SMILES string for one or more input variants using key '{smiles_key}'. Cannot proceed.")
        # Optionally, filter out invalid entries and continue, but safer to stop.
        return [] # Or raise ValueError

    temp_df = pd.DataFrame({smiles_key: smiles_list})

    # --- Generate Molecule Objects ---
    logger.info("Generating RDKit molecules from SMILES...")
    temp_df['mol'] = dm.parallelized(dm.to_mol, temp_df[smiles_key].tolist(), n_jobs=-1, progress=True)
    original_len = len(temp_df)
    temp_df = temp_df.dropna(subset=['mol'])
    if len(temp_df) < original_len:
        logger.warning(f"Dropped {original_len - len(temp_df)} compounds due to SMILES parsing errors.")

    if temp_df.empty:
        logger.warning("No valid molecules remaining after parsing. Returning empty list.")
        return []

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

    logger.info(f"Returning {len(filtered_variants_output)} filtered variant dictionaries.")
    return filtered_variants_output

def filter_compounds(
    input_variants: List[Dict[str, Any]],
    rule_threshold: int = 13,
    structural_threshold: int = 27,
    smiles_key: str = 'smiles'
    ) -> List[Dict[str, Any]]:
    """
    Wrapper function to filter compounds based on pass counts.
    This provides a consistent entry point if needed.
    """
    logger.info("Using filter_compounds wrapper -> calling filter_by_pass_count.")
    return filter_by_pass_count(
        input_variants=input_variants,
        rule_threshold=rule_threshold,
        structural_threshold=structural_threshold,
        smiles_key=smiles_key
    )

def apply_medchem_filtering_to_variants(variants, output_dir):
    """
    Apply medchem filtering to variant SMILES.
    
    Args:
        variants: List of variant dictionaries with SMILES
        output_dir: Directory to save temporary files and results
        
    Returns:
        List of filtered variants
    """
    if not variants:
        logger.warning("No variants provided for filtering")
        return []

    try:
        # Import required functions
        from utils.molecule_processing import smiles_to_sdf
        from pathlib import Path
        
        # Create a temporary SDF file with all variants
        temp_sdf = Path(output_dir) / "temp_variants_for_filtering.sdf"
        if not smiles_to_sdf(variants, temp_sdf):
            logger.error("Failed to create temporary SDF file for filtering")
            return []
        
        # Apply MedChem filtering
        logger.info(f"Applying MedChem filtering to {len(variants)} variants...")
        filtered_df = filter_by_pass_count(temp_sdf, output_folder=output_dir)
        
        if filtered_df is None or filtered_df.empty:
            logger.warning("No variants passed MedChem filtering")
            return []
        
        # Create a mapping of SMILES to original variant data
        smiles_to_variant = {v['smiles']: v for v in variants}
        
        # Create a list for filtered variants
        filtered_variants = []
        
        # Check if SMILES column exists in filtered results
        smiles_col = None
        for possible_col in ['SMILES', 'smiles', 'canonical_smiles']:
            if possible_col in filtered_df.columns:
                smiles_col = possible_col
                break
        
        if not smiles_col:
            logger.error(f"Could not find SMILES column in filtered results. Available columns: {filtered_df.columns.tolist()}")
            return []
        
        # Match filtered compounds back to original variants
        for _, row in filtered_df.iterrows():
            smiles = row[smiles_col]
            if smiles in smiles_to_variant:
                variant = smiles_to_variant[smiles]
                # Add any additional properties from filtering if needed
                if 'filter_score' in row:
                    variant['filter_score'] = row['filter_score']
                filtered_variants.append(variant)
                logger.debug(f"Matched filtered variant: {variant.get('variant_id', 'unknown')} (Barcode: {variant.get('barcode', 'unknown')})")
        
        logger.info(f"MedChem filtering complete: {len(filtered_variants)} variants passed filtering out of {len(variants)}")
        return filtered_variants
    
    except Exception as e:
        logger.error(f"Error during MedChem filtering: {e}")
        return []
    
    finally:
        # Clean up temporary files
        if 'temp_sdf' in locals() and temp_sdf.exists():
            try:
                temp_sdf.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete temporary SDF file: {e}")

