# Drug Discovery Pipeline – Streamlit App for AI-Assisted Molecular Design

**Drug\_pipeline** is a web-based application that streamlines de novo drug design by integrating AI-driven molecule generation, medicinal chemistry filters, and molecular docking into one workflow. Built on Streamlit, it allows researchers to interactively configure runs, monitor progress in real-time, and visualize results for target protein sites. The pipeline automates the process of generating new chemical compounds for a given protein and evaluating their drug-likeness and binding potential.

## Features

* **AI Ligand Generation:** Supports pocket-based molecule generation via *DiffSBDD* (diffusion model) or *Pocket2Mol* (graph generative model). Generates candidate compounds in 3D for the specified binding site.
* **Interactive Configuration:** Intuitive UI to upload target structures (PDB), set binding site coordinates (or residues), choose generation model and parameters (number of compounds, rounds, etc.). Advanced settings (multi-round optimization, synthetic variant generation, etc.) are available for power users.
* **Real-time Monitoring:** Live console logs and status updates during pipeline execution – see generation progress, docking status, and any warnings/errors as they happen. A “Stop” option allows graceful termination of runs.
* **Automated Pipeline Steps:**
  ➔ *MedChem Filtering:* Applies medicinal chemistry rules and structural alerts to filter out undesirable compounds (e.g., PAINS, Lipinski’s rule of 5).
  ➔ *Pose Filtering:* (Full pipeline mode) Uses PoseBuster to eliminate chemically implausible ligand poses before docking.
  ➔ *Blind Docking Filter:* Boltz-1x filter to predict if a ligand can bind the target; removes compounds unlikely to fit the pocket.
  ➔ *Molecular Docking:* Automatically docks filtered compounds into the protein’s binding site using QuickVina 2 (AutoDock Vina) with NNScore2 rescoring. Captures best pose and binding score for each compound.
  ➔ *Retrosynthesis Analysis:* For top hits, generates potential synthetic routes or analogs via Synformer (Transformer-based retrosynthesis model) and can optionally re-dock those analogs to evaluate improvements.
* **Results Visualization:** After docking, view interactive plots and tables of results. The app displays each top compound’s structure (2D image and 3D pose), docking scores, and other properties. Users can expand details for each molecule (SMILES string, rule passes, etc.) and compare compounds.
* **Data Export:** Easily download results – e.g. a CSV of docking scores and SMILES, or SDF files of docked poses – for further analysis. The pipeline outputs are organized by run and round for convenient access.

## Installation

1. Clone the repository:
```bash
git clone https://github.com/sheepyrad/Drug_pipeline.git
cd drug_pipeline
```
2. Run the setup.sh

```bash
./setup.sh
```
3. Activate the conda environment

```bash
conda activate drug_pipeline
```

4. Install gmx_MMPBSA

```bash
pip install gmx_MMPBSA
```

5. Install pytorch

```bash
pip install torch==2.6.0+cu126 torchvision==0.21.0+cu126 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu126
pip install pyg-lib torch-scatter torch-sparse torch-cluster torch-spline-conv -f https://data.pyg.org/whl/torch-2.6.0+cu126.html
pip install torch-geometric
```
6. Install boltz

```bash
pip install boltz
```
7. Install synformer

```bash
cd src/synformer
pip install --no-deps -e .
```

## Usage

**Launch the Streamlit app:**

```bash
streamlit run app.py
```

2. Open your web browser and navigate to the URL shown in the terminal (usually http://localhost:8501)

3. Follow these steps in the application:

   a. **Configuration**:
      - Upload required files (PDB, checkpoint)
      - Set pipeline parameters
      - Configure docking settings

   b. **Execution**:
      - Start the pipeline
      - Monitor progress
      - View real-time logs

   c. **Results**:
      - View generated compounds
      - Analyze docking results
      - Export data

## Application Structure

```
drug_pipeline_app/
├── app.py                 # Main application file
├── pages/                 # Streamlit pages
│   ├── 01_configuration.py
│   ├── 02_execution.py
│   ├── 03_results.py
├── pipeline_quick_multiround.py  # Pipeline implementation
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## Requirements

- Python 3.8+
- CUDA-capable GPU (recommended for optimal performance)
- Dependencies listed in requirements.txt

## Environment Variables

The following environment variables can be set:

- `CUDA_VISIBLE_DEVICES`: GPU device indices to use
- `STREAMLIT_SERVER_PORT`: Custom port for the Streamlit server
- `STREAMLIT_SERVER_ADDRESS`: Custom address for the Streamlit server

## Troubleshooting

Common issues and solutions:

1. **GPU Not Detected**:
   - Ensure CUDA drivers are installed
   - Check CUDA_VISIBLE_DEVICES environment variable

2. **Memory Issues**:
   - Reduce the number of samples
   - Lower the exhaustiveness parameter
   - Clear browser cache

3. **File Upload Issues**:
   - Check file size limits
   - Verify file formats
   - Ensure proper file permissions
