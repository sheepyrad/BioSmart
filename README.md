# Drug Discovery Pipeline Streamlit Application

A web-based interface for running and monitoring the drug discovery pipeline, built with Streamlit.

## Features

- **Interactive Configuration**: Easy-to-use interface for setting up pipeline parameters
- **Real-time Monitoring**: Track pipeline progress and view logs in real-time
- **Results Visualization**: 
  - 2D and 3D molecular structure visualization
  - Interactive plots and charts
  - Comprehensive results dashboard
- **Data Export**: Export results in various formats (CSV, statistics)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/sheepyrad/AI_drug_discovery.git
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
4. Setup Protenix
This step is to download the checkpoints and ccd_cache for Protenix

```bash
cd src/Protenix
protenix predict --input examples/example.json --out_dir  ./output --seeds 101
```
After it finishes, the /output directory should contain predictions of Protenix

## Usage

1. Start the Streamlit application:
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

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## Citation

If you use this software in your research, please cite:

```bibtex
@software{drug_pipeline_app,
  author = {Your Name},
  title = {Drug Discovery Pipeline Application},
  year = {2024},
  url = {https://github.com/yourusername/drug_pipeline_app}
}
```

## Contact

For support or questions, please open an issue on the GitHub repository or contact [your@email.com]. 
