# FYP Thesis Data Submission

This repository branch deposits the thesis figure data, plotting code, and Matplotlib-generated figure outputs under `Data/`.

The `Data/` folder stores the raw data used to plot the submitted thesis figures, together with the Python scripts used to regenerate the figures. Figure outputs in this deposit are drawn by Matplotlib from the included data files. Non-Python/code/data analysis plots are not stored in `Data/`.

## File Structure

- `Data/Figure7/`
  - `Figure7A/`: Boltz score trace for the top compound, average of top 10 compounds, and average of top 100 compounds.
  - `Figure7B/`: Cumulative number of compounds exceeding Boltz score thresholds of 0.5, 0.6, 0.7, and 0.8.
- `Data/Figure10/`: MM-GBSA binding energy analysis for selected compounds.
- `Data/Figure11/`: Compound 45 residue decomposition analysis.
- `Data/Figure12/`: Compound 45 CCK-8 cell viability plot.
- `Data/Figure13/`
  - `Figure13A/`: Python-generated log ZIKV NS5 titer bar plot.
  - `Figure13B/`: Python-generated log10 viral copies comparison at 50 uM and 100 uM.
- `Data/Figure14/`: Compound 45 ZIKV NS5 inhibition dose-response and IC50 plot.
- `Data/Supplementary Data S1/`: Top-100 unique Boltz compound pairwise Tanimoto similarity data and helper script for reporting the average pairwise Tanimoto similarity.

Each figure folder is intended to be self-contained for thesis submission: it includes the plotting script, the data needed by that script, and the submitted figure output files where applicable.
