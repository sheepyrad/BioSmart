# Drug Discovery Pipeline – Streamlit App for AI-Assisted Molecular Design

**Drug\_pipeline** is a web-based application that streamlines de novo drug design by integrating AI-driven molecule generation, medicinal chemistry filters, and molecular docking into one workflow. Built on Streamlit, it allows researchers to interactively configure runs, monitor progress in real-time, and visualize results for target protein sites. The pipeline automates the process of generating new chemical compounds for a given protein and evaluating their drug-likeness and binding potential.

## Features

* **AI Ligand Generation:** Supports pocket-based molecule generation via *DiffSBDD* (diffusion model) or *Pocket2Mol* (graph generative model). Generates candidate compounds in 3D for the specified binding site.
* **Interactive Configuration:** Intuitive UI to upload target structures (PDB), set binding site coordinates (or residues), choose generation model and parameters (number of compounds, rounds, etc.). Advanced settings (multi-round optimization, synthetic variant generation, etc.) are available for power users.
* **Real-time Monitoring:** Live console logs and status updates during pipeline execution – see generation progress, docking status, and any warnings/errors as they happen. A “Stop” option allows graceful termination of runs.
* **Automated Pipeline Steps:**
  ➔ *MedChem Filtering:* Applies medicinal chemistry rules and structural alerts to filter out undesirable compounds (e.g., PAINS, Lipinski’s rule of 5).
  ➔ *Pose Filtering:* (Full pipeline mode) Uses PoseBuster to eliminate chemically implausible ligand poses before docking.
  ➔ *Blind Docking Filter:* (Quick mode) Boltz-1x ML filter to predict if a ligand can bind the target; removes compounds unlikely to fit the pocket.
  ➔ *Molecular Docking:* Automatically docks filtered compounds into the protein’s binding site using QuickVina 2 (AutoDock Vina) with NNScore2 rescoring. Captures best pose and binding score for each compound.
  ➔ *Retrosynthesis Analysis:* For top hits, generates potential synthetic routes or analogs via Synformer (Transformer-based retrosynthesis model) and can optionally re-dock those analogs to evaluate improvements.
* **Results Visualization:** After docking, view interactive plots and tables of results. The app displays each top compound’s structure (2D image and 3D pose), docking scores, and other properties. Users can expand details for each molecule (SMILES string, rule passes, etc.) and compare compounds.
* **Data Export:** Easily download results – e.g. a CSV of docking scores and SMILES, or SDF files of docked poses – for further analysis. The pipeline outputs are organized by run and round for convenient access.

## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/sheepyrad/Drug_pipeline.git  
   cd Drug_pipeline
   ```
2. **Set up the Conda environment:**
   Run the provided setup script to create a Conda environment and fetch required model files:

   ```bash
   ./setup.sh
   conda activate drug_pipeline
   ```

   *Requirements:* Anaconda/Miniconda, \~10 GB disk space (for dependencies and model checkpoints). The environment includes PyTorch (for ML models), RDKit and OpenMM (for chemistry ops), and Streamlit.
3. **One-time model data prep (Protenix):**
   *(Optional, for first-time use)* Download weights/cache for the Protenix model by running:

   ```bash
   cd src/Protenix  
   protenix predict --input examples/example.json --out_dir ./output --seeds 101  
   ```

   This will produce an output prediction (ignore it) and download necessary data. After completion, return to the repo root.

## Usage

**Launch the Streamlit app:**

```bash
streamlit run app.py
```

This opens the web interface in your browser (usually at **[http://localhost:8501](http://localhost:8501)**).

**Pipeline workflow via the UI:**

1. **Configuration:** On the "Basic Configuration" tab, upload your target protein structure (`.pdb`). *(Optional:* also upload a prepared receptor in `.pdbqt` format for docking, otherwise provide the PDBQT path if available). Specify the binding site either by listing key residues or by setting the grid box on the "Box Settings" tab (center coordinates and dimensions). Choose the molecule generation model (DiffSBDD or Pocket2Mol) and number of compounds to generate. Adjust any other parameters as needed (e.g., docking program, scoring function, number of rounds for iterative optimization).
2. **Run Pipeline:** Switch to the "Execution" page and start the run. The app will display live logs of each stage – generation, filtering, docking, etc. – with color-coded messages (INFO, WARNING, ERROR). You can monitor progress and stop the run early if needed.
3. **Results:** Once complete, go to the "Results" page. Here you can:

   * View a summary table of all docked compounds with their scores.
   * Click on a compound to inspect details: a 2D structure image and its 3D pose in the binding site (visualized with py3Dmol) are shown, along with properties like SMILES, filters passed, etc..
   * See distribution plots (e.g., score histograms) and filtering reports (how many rules each compound passed).
   * Download the results (CSV of scores, SDF of top poses, etc.) for offline analysis.

For a quick start, you can test the pipeline with the provided example protein (Dengue virus NS5 polymerase in `input/NS5.pdb`) and default settings – just upload the PDB, set a small number of samples (e.g., 10), and run. Example output files will be saved under `outputs/<your_run_name>/` for review.

## Repository Layout

```bash
Drug_pipeline/
├── app.py               # Streamlit app main script
├── pages/               # UI subpages for Streamlit
│   ├── 01_configuration.py   # File upload & parameter inputs
│   ├── 02_execution.py       # Pipeline execution and live log display
│   └── 03_results.py         # Visualization of results (tables, 3D viewer, etc.)
├── pipeline.py          # Full pipeline script (single-round, with PoseBuster & energy minimization)
├── pipeline_quick_multiround.py  # Quick iterative pipeline script (multi-round, faster, uses Protenix)
├── utils/               # Custom pipeline modules
│   ├── ligand_generation.py    # Calls DiffSBDD or Pocket2Mol for molecule gen.
│   ├── medchem_filter.py      # Medicinal chemistry filtering logic:contentReference[oaicite:234]{index=234}
│   ├── redocking.py           # Docking wrapper (calls VirtualFlow Unity):contentReference[oaicite:235]{index=235}
│   ├── pose_evaluation.py     # PoseBuster integration
│   ├── retrosynformer.py      # Runs Synformer retrosynthesis and processes outputs:contentReference[oaicite:236]{index=236}
│   ├── boltz_filter.py        # Uses Boltz-1x ML model to filter poses:contentReference[oaicite:237]{index=237}
│   └── ... (other helpers: energy_minimization, logging, etc.)
├── src/                # External dependencies (treated as read-only)
│   ├── DiffSBDD/        # Diffusion model for SBDD (external code + checkpoints)
│   ├── Pocket2Mol/      # Pocket2Mol model (external)
│   ├── synformer/       # Synformer retrosynthesis model (external + data) 
│   ├── VFU/             # Virtual Flow Unity (docking executables and config scripts)
│   └── LUDe_v2/         # Decoy generation utility (to be integrated)
├── tests/              # Unit tests for critical functions (e.g., docking):contentReference[oaicite:238]{index=238}
├── environment.yml     # Conda environment definition (packages and channels):contentReference[oaicite:239]{index=239}
├── requirements.txt    # Python package requirements (for pip-based install):contentReference[oaicite:240]{index=240}
├── setup.sh            # Setup script to configure environment and download models:contentReference[oaicite:241]{index=241}:contentReference[oaicite:242]{index=242}
├── README.md           # User guide (this file)
└── CODING_GUIDELINES.md # Contribution and code style guidelines
```

## Contributing and Support

Contributions are welcome! If you’d like to add features or improvements, please follow the style and structure outlined in **CODING\_GUIDELINES.md**. Notably, avoid modifying code under `src/` (external libraries); instead, extend or wrap functionality in the `utils/` modules.

For support or to report issues/bugs, please open an issue in this repository. You can also reach out via email (see Contact in README) for specific inquiries. We aim to respond and address issues promptly to make this pipeline robust and useful for the community.
