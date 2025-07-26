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

1. **Clone the repository:**
   ```bash
   git clone https://github.com/sheepyrad/Drug_pipeline.git
   cd Drug_pipeline
   ```

2. **Run the setup script:**
   The setup script will automatically create the conda environment and install most dependencies:
   ```bash
   ./setup.sh
   ```

3. **Activate the conda environment:**
   ```bash
   conda activate drug_pipeline
   ```

4. **Install additional dependencies:**
   Install the remaining Python packages:
   ```bash
   pip install gmx_MMPBSA
   pip install torch==2.6.0+cu126 torchvision==0.21.0+cu126 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu126
   pip install pyg-lib torch-scatter torch-sparse torch-cluster torch-spline-conv -f https://data.pyg.org/whl/torch-2.6.0+cu126.html
   pip install torch-geometric lightning
   pip install boltz
   ```

5. **Install Synformer:**
   ```bash
   cd src/synformer
   pip install --no-deps -e .
   cd ../..
   ```

## Usage

**Launch the Streamlit app:**

```bash
streamlit run app.py
```

Open your web browser and navigate to the URL shown in the terminal (usually http://localhost:8501)

**Pipeline Workflow:**

1. **Configuration** (Page 1):
   - Upload your target protein structure (PDB file)
   - Set binding site coordinates or specify residues
   - Choose AI generation model (DiffSBDD or Pocket2Mol)
   - Configure generation parameters (number of compounds, rounds)
   - Set docking and filtering options

2. **Execution** (Page 2):
   - Start the pipeline run
   - Monitor real-time progress logs
   - View status updates for each pipeline stage
   - Option to stop execution if needed

3. **Results Analysis** (Pages 3-6):
   - **Basic Results** (Page 3): View summary tables and compound details
   - **Advanced Visualization** (Page 4): Interactive plots and 3D molecular viewers
   - **Similarity Search** (Page 5): Find similar compounds in databases
   - **Boltz Analysis** (Page 6): Advanced ML-based binding predictions
   - Export results (CSV, SDF files) for further analysis

## Quick Start Example

To test the pipeline with provided example data:

1. **Use example protein:**
   - Upload the provided test protein: `input/NS5.pdb` (Dengue virus NS5 polymerase)
   - Set a small number of samples (e.g., 10) for quick testing
   - Use default parameters for initial run

2. **Monitor and analyze:**
   - Watch the execution progress in real-time
   - Explore results in the visualization pages
   - Download outputs from `outputs/<run_name>/` directory

## Advanced Features

The pipeline includes several advanced analysis tools:

- **Similarity Search**: Find structurally similar compounds in chemical databases
- **Boltz Analysis**: Use ML models to predict binding affinity and pose quality
- **Multi-round Optimization**: Iteratively improve compound generation
- **Retrosynthesis Planning**: Generate synthetic routes for promising compounds

## Repository Structure

```
Drug_pipeline/
├── app.py                         # Main Streamlit application
├── pages/                         # Streamlit UI pages
│   ├── 01_configuration.py       # Basic configuration and file upload
│   ├── 02_execution.py           # Pipeline execution and monitoring
│   ├── 03_results.py             # Results visualization and analysis
│   ├── 04_visualize_results.py   # Advanced results visualization
│   ├── 05_similarity_search.py   # Molecular similarity search
│   └── 06_boltz_analysis.py      # Boltz model analysis
├── pipeline_quick_multiround.py  # Main pipeline implementation
├── utils/                         # Custom pipeline utilities
│   ├── ligand_generation.py      # AI molecule generation
│   ├── medchem_filter.py          # Medicinal chemistry filtering
│   ├── redocking.py               # Molecular docking utilities
│   ├── boltz_filter.py            # Boltz ML filtering
│   ├── retrosynformer.py          # Retrosynthesis analysis
│   ├── pose_evaluation.py         # Pose quality evaluation
│   ├── energy_minimization.py    # Energy minimization utilities
│   └── ...                       # Additional utility modules
├── src/                           # External dependencies (read-only)
│   ├── DiffSBDD/                  # Diffusion-based SBDD model
│   ├── Pocket2Mol/                # Pocket2Mol generation model
│   ├── synformer/                 # Retrosynthesis model
│   ├── Uni-Dock/                  # Docking software
│   └── cgflow/                    # Additional ML models
├── environment.yml                # Conda environment specification
├── setup.sh                      # Environment setup script
└── README.md                     # This documentation
```

## Requirements

- **Python**: 3.10+
- **Conda**: Anaconda or Miniconda
- **GPU**: CUDA-capable GPU recommended for optimal performance
- **Storage**: ~10 GB free disk space for dependencies and model checkpoints
- **Memory**: 16+ GB RAM recommended for large molecule datasets

## Contributing

Contributions are welcome! Please follow these guidelines:

1. **Read the coding guidelines:** See `CODING_GUIDELINES.md` for detailed style and structure requirements
2. **Respect the repository structure:** 
   - Do not modify files in `src/` (external dependencies)
   - Add new functionality to the `utils/` directory
   - Follow the existing naming conventions
3. **Test your changes:** Ensure new features work with the example data
4. **Documentation:** Update this README if you add new features or change workflows

For bug reports or feature requests, please open an issue in this repository.

## Troubleshooting

### Common Issues and Solutions

1. **Environment Setup Issues**:
   - Ensure Conda is installed and accessible
   - Check that CUDA drivers are compatible (if using GPU)
   - Verify sufficient disk space (~10 GB required)

2. **GPU and Memory Issues**:
   - Set `CUDA_VISIBLE_DEVICES` to specify GPU devices
   - Reduce the number of samples if running out of memory
   - Lower the exhaustiveness parameter for docking
   - Monitor GPU memory usage with `nvidia-smi`

3. **Pipeline Execution Problems**:
   - Check input file formats (PDB files should be valid)
   - Verify binding site coordinates are within the protein structure
   - Review execution logs for specific error messages
   - Ensure all dependencies are properly installed

4. **Streamlit Interface Issues**:
   - Clear browser cache if interface doesn't load properly
   - Check firewall settings for port 8501
   - Try using a different browser
   - Restart the Streamlit app if it becomes unresponsive

### Environment Variables

Useful environment variables for configuration:

- `CUDA_VISIBLE_DEVICES`: Specify which GPU devices to use
- `STREAMLIT_SERVER_PORT`: Custom port for the Streamlit server  
- `STREAMLIT_SERVER_ADDRESS`: Custom address for the Streamlit server
