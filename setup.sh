#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define variables
CONDA_ENV_NAME="sbdd_env"
# REPO_URL="https://github.com/sheepyrad/Drug_pipeline.git" # Removed, assuming script is run inside repo
# REPO_DIR="Drug_pipeline" # Removed, assuming script is run inside repo
ENV_YAML="environment.yml"

# --- Helper Functions ---
echo_step() {
    echo "----------------------------------------"
    echo "STEP: $1"
    echo "----------------------------------------"
}

check_command() {
    if ! command -v $1 &> /dev/null
    then
        echo "Error: $1 is not installed or not in PATH. Please install it and try again."
        exit 1
    fi
}

# --- Main Setup Logic ---

# 0. Check prerequisites
echo_step "Checking prerequisites (conda, wget)"
# check_command git # Removed git check
check_command conda
check_command wget
echo "Prerequisites found."

# 1. Clone the repository (Removed)
# echo_step "Cloning the repository from $REPO_URL" # Removed
# if [ -d "$REPO_DIR" ]; then # Removed
#     echo "Directory $REPO_DIR already exists. Skipping clone." # Removed
# else # Removed
#     git clone "$REPO_URL" # Removed
# fi # Removed
# cd "$REPO_DIR" # Removed
# echo "Changed directory to $(pwd)" # Removed

# 2. Create the conda environment
echo_step "Creating conda environment '$CONDA_ENV_NAME' from $ENV_YAML"
if conda env list | grep -q "^$CONDA_ENV_NAME "; then
    echo "Conda environment '$CONDA_ENV_NAME' already exists. Skipping creation."
    echo "To recreate it, first run: conda env remove -n $CONDA_ENV_NAME --all -y"
elif [ -f "$ENV_YAML" ]; then
    conda env create -f "$ENV_YAML"
else
    echo "Error: $ENV_YAML not found in $(pwd). Cannot create environment."
    exit 1
fi

# 3. Activate the conda environment (Informational - script needs sourcing or manual activation)
# Note: Activation within a script doesn't persist after the script exits.
# The user needs to run `conda activate sbdd_d24h` manually after the script finishes.
echo_step "Activate the conda environment"
echo "Please run 'conda activate $CONDA_ENV_NAME' after this script completes."

# Setup DiffSBDD
echo_step "Setting up DiffSBDD"
if [ -d "src/DiffSBDD" ]; then
    cd src/DiffSBDD
    echo "Changed directory to $(pwd)"

    # 4. Download DiffSBDD checkpoint
    DIFFSBDD_CKPT_URL="https://zenodo.org/record/8183747/files/crossdocked_fullatom_cond.ckpt"
    DIFFSBDD_CKPT_DIR="checkpoints"
    DIFFSBDD_CKPT_FILE="$DIFFSBDD_CKPT_DIR/crossdocked_fullatom_cond.ckpt"

    echo "Downloading DiffSBDD checkpoint to $DIFFSBDD_CKPT_DIR"
    mkdir -p "$DIFFSBDD_CKPT_DIR"
    if [ -f "$DIFFSBDD_CKPT_FILE" ]; then
        echo "DiffSBDD checkpoint already exists. Skipping download."
    else
        wget -O "$DIFFSBDD_CKPT_FILE" "$DIFFSBDD_CKPT_URL"
    fi
    cd ../.. # Go back to the root of the repo
    echo "Changed directory back to $(pwd)"
else
    echo "Warning: Directory src/DiffSBDD not found. Skipping DiffSBDD setup."
fi

# Setup synformer
echo_step "Setting up synformer"
if [ -d "src/synformer" ]; then
    cd src/synformer
    echo "Changed directory to $(pwd)"

    # 5. Install synformer locally
    echo "Installing synformer (editable mode, no dependencies) into $CONDA_ENV_NAME environment"
    # Ensure pip is from the conda env using conda run
    conda run -n $CONDA_ENV_NAME pip install --no-deps -e .

    # 6. Create synformer data directories
    SYNFORMER_DATA_DIR="data"
    SYNFORMER_PROCESSED_DIR="$SYNFORMER_DATA_DIR/processed/comp_2048"
    SYNFORMER_WEIGHTS_DIR="$SYNFORMER_DATA_DIR/trained_weights"

    echo "Creating synformer data directories"
    mkdir -p "$SYNFORMER_PROCESSED_DIR"
    mkdir -p "$SYNFORMER_WEIGHTS_DIR"

    # 7. Download synformer processed files
    FPINDEX_URL="https://huggingface.co/whgao/synformer/resolve/main/fpindex.pkl?download=true"
    MATRIX_URL="https://huggingface.co/whgao/synformer/resolve/main/matrix.pkl?download=true"
    FPINDEX_FILE="$SYNFORMER_PROCESSED_DIR/fpindex.pkl"
    MATRIX_FILE="$SYNFORMER_PROCESSED_DIR/matrix.pkl"

    echo "Downloading synformer processed files to $SYNFORMER_PROCESSED_DIR"
    if [ -f "$FPINDEX_FILE" ]; then
        echo "fpindex.pkl already exists. Skipping download."
    else
        wget -O "$FPINDEX_FILE" "$FPINDEX_URL"
    fi
    if [ -f "$MATRIX_FILE" ]; then
        echo "matrix.pkl already exists. Skipping download."
    else
        wget -O "$MATRIX_FILE" "$MATRIX_URL"
    fi

    # 8. Download synformer checkpoint
    SYNFORMER_CKPT_URL="https://huggingface.co/whgao/synformer/resolve/main/sf_ed_default.ckpt?download=true"
    SYNFORMER_CKPT_FILE="$SYNFORMER_WEIGHTS_DIR/sf_ed_default.ckpt"

    echo "Downloading synformer checkpoint to $SYNFORMER_WEIGHTS_DIR"
    if [ -f "$SYNFORMER_CKPT_FILE" ]; then
        echo "Synformer checkpoint already exists. Skipping download."
    else
        wget -O "$SYNFORMER_CKPT_FILE" "$SYNFORMER_CKPT_URL"
    fi

    cd ../.. # Go back to the root of the repo
    echo "Changed directory back to $(pwd)"
else
    echo "Warning: Directory src/synformer not found. Skipping synformer setup."
fi

# Setup VFU
echo_step "Setting up VFU executables"
if [ -d "src/VFU/executables" ]; then
    cd src/VFU/executables
    echo "Changed directory to $(pwd)"

    # 9. Make VFU executables executable
    echo "Making files in $(pwd) executable"
    chmod +x *
    # Add specific checks or compilation steps if needed here

    cd ../../.. # Go back to the root of the repo
    echo "Changed directory back to $(pwd)"
elif [ -d "src/VFU" ]; then
     echo "Warning: Directory src/VFU/executables not found, but src/VFU exists."
else
    echo "Warning: Directory src/VFU not found. Skipping VFU setup."
fi

# Setup Pocket2Mol
echo_step "Setting up Pocket2Mol"
if [ -d "src/Pocket2Mol/ckpt" ]; then
    cd src/Pocket2Mol/ckpt
    echo "Changed directory to $(pwd)"

    # 10. Download the model checkpoint
    echo "Downloading Pocket2Mol checkpoint to $(pwd)"

    POCKET2MOL_CKPT_FILE="pretrained_Pocket2Mol.pt"
    if [ -f "$POCKET2MOL_CKPT_FILE" ]; then
        echo "Pocket2Mol checkpoint already exists. Skipping download."
    else
        gdown --id 1WaoEj9RDG4VEcyHEmgsjbh958txm1W6x
    fi

    cd ../../.. # Go back to the root of the repo
    echo "Changed directory back to $(pwd)"
else
    echo "Warning: Directory src/Pocket2Mol/ckpt not found. Skipping Pocket2Mol setup."
fi

# Setup Protenix
echo_step "Setting up Protenix"
if [ -d "src/Protenix" ]; then
    cd src/Protenix
    echo "Changed directory to $(pwd)"

    # 11. Install Protenix
    echo "Installing Protenix  into $CONDA_ENV_NAME environment"

echo "----------------------------------------"
echo "Setup script finished."
echo "IMPORTANT: Activate the environment by running: conda activate $CONDA_ENV_NAME"
echo "----------------------------------------" 