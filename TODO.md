# Plan for Pipeline Enhancements: MedChem Filtering & Decoy Generation

## Overview

This plan outlines the steps to modify the `pipeline_quick_multiround.py` script to incorporate two major enhancements:
1.  **Updated MedChem Filtering:** Replace the current filtering logic with a pass-count based approach similar to the one used in `notebooks/run_fda_filter_on_docked.py`.
2.  **Decoy Generation and Docking:** Integrate logic adapted from the LUDe Streamlit application (`src/LUDe_v2/LUDe_streamlit_v2.py`) to generate decoys for initially generated active compounds and subsequently dock these decoys.

## 1. MedChem Filtering Update

### Objective
Replace the existing `utils.medchem_filter.generative_filter` function with a new implementation that filters compounds based on the number of rules and structural alerts passed.

### Steps

1.  **Modify `utils/medchem_filter.py`:**
    *   **Rename/Replace Function:** Rename the existing `generative_filter` or create a new function (e.g., `filter_by_pass_count`). This function will replace the core logic previously used.
    *   **Input:** The function should accept a list of SMILES strings or molecule objects (or potentially an SDF file path).
    *   **Core Logic (Adapt from `run_fda_filter_on_docked.py`):**
        *   Load/Generate RDKit molecule objects from input SMILES. Handle parsing errors.
        *   Define the lists of `rules_to_apply` (e.g., Ro5, Ghose) and `structural_alerts_to_apply` (e.g., PAINS, Glaxo, NIBR) using the `medchem` library.
        *   Apply each rule and alert filter to the molecules, storing boolean results (True=Pass, False=Fail).
        *   Calculate `n_rules_pass` and `n_structural_pass` for each molecule by summing the boolean results.
        *   Define **Thresholds**: Set the minimum pass counts required (e.g., `rule_threshold = 13`, `struct_threshold = 27`). These could be hardcoded initially or passed as arguments.
        *   **Filtering:** Select only those molecules where `n_rules_pass >= rule_threshold` AND `n_structural_pass >= struct_threshold`.
    *   **Output:** The function should return a list containing the SMILES strings (or full data dictionaries/DataFrames including IDs and SMILES) of the molecules that *passed* the filtering thresholds.
    *   **Dependencies:** Ensure `medchem`, `pandas`, `numpy`, `rdkit`, `datamol` are imported and used correctly within this utility script.

2.  **Integrate into `pipeline_quick_multiround.py`:**
    *   Locate the call to `apply_medchem_filtering_to_variants` (which previously called `generative_filter`).
    *   Replace this call with a call to the new filtering function (e.g., `filter_by_pass_count`).
    *   Ensure the input passed to the new function is correct (likely the `all_variants` list or an SDF derived from it).
    *   Update the variable assignment (`filtered_variants = ...`) to correctly handle the output format of the new function (a list of passing variants).
    *   Adjust logging messages to reflect the new filtering method.

## Conclusion

These changes will enhance the pipeline by implementing a more standard MedChem filtering approach.