#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define variables
ENV_DIR="conda_files"

# --- Helper Functions ---
echo_step() {
    echo "=========================================="
    echo "STEP: $1"
    echo "=========================================="
}

check_command() {
    if ! command -v $1 &> /dev/null
    then
        echo "Error: $1 is not installed or not in PATH. Please install it and try again."
        exit 1
    fi
}

create_env_if_not_exists() {
    local env_name=$1
    local env_file=$2
    
    if conda env list | grep -q "^$env_name "; then
        echo "Conda environment '$env_name' already exists. Skipping creation."
        echo "To recreate it, first run: conda env remove -n $env_name --all -y"
    elif [ -f "$env_file" ]; then
        echo "Creating conda environment '$env_name' from $env_file"
        conda env create -f "$env_file"
    else
        echo "Error: $env_file not found. Cannot create environment."
        exit 1
    fi
}

# --- Main Setup Logic ---

# 0. Check prerequisites
echo_step "Checking prerequisites (conda, wget, git)"
check_command conda
check_command wget
check_command git
echo "Prerequisites found."

# 1. Create DiffSBDD environment
echo_step "Setting up DiffSBDD environment"
create_env_if_not_exists "diffsbdd-env" "$ENV_DIR/diffsbdd.yml"

# Setup DiffSBDD
if [ -d "src/DiffSBDD" ]; then
    cd src/DiffSBDD
    echo "Changed directory to $(pwd)"

    # Download DiffSBDD checkpoint
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

# 2. Create Pocket2Mol environment and setup
echo_step "Setting up Pocket2Mol environment"

# Clone Pocket2Mol if not exists
if [ ! -d "src/Pocket2Mol" ]; then
    echo "Cloning Pocket2Mol repository"
    cd src
    git clone https://github.com/pengxingang/Pocket2Mol.git
    cd ..
fi

create_env_if_not_exists "pocket2mol-env" "$ENV_DIR/pocket2mol.yml"

# Setup Pocket2Mol checkpoint
if [ -d "src/Pocket2Mol/ckpt" ]; then
    cd src/Pocket2Mol/ckpt
    echo "Changed directory to $(pwd)"

    # Download the model checkpoint using gdown
    echo "Downloading Pocket2Mol checkpoint to $(pwd)"
    POCKET2MOL_CKPT_FILE="pretrained_Pocket2Mol.pt"
    if [ -f "$POCKET2MOL_CKPT_FILE" ]; then
        echo "Pocket2Mol checkpoint already exists. Skipping download."
    else
        # Install gdown in the pocket2mol environment and use it
        conda run -n pocket2mol-env pip install gdown
        conda run -n pocket2mol-env gdown 1WaoEj9RDG4VEcyHEmgsjbh958txm1W6x
    fi

    cd ../../.. # Go back to the root of the repo
    echo "Changed directory back to $(pwd)"
else
    echo "Warning: Directory src/Pocket2Mol/ckpt not found. Skipping Pocket2Mol setup."
fi

# # 3. Create CGFlow environment and setup
# echo_step "Setting up CGFlow environment"

# # Clone CGFlow if not exists
# if [ ! -d "src/cgflow" ]; then
#     echo "Cloning CGFlow repository"
#     cd src
#     git clone https://github.com/tsa87/cgflow.git
#     cd ..
# fi

# create_env_if_not_exists "cgflow-env" "$ENV_DIR/cgflow.yml"

# # Setup CGFlow
# if [ -d "src/cgflow" ]; then
#     cd src/cgflow
#     echo "Changed directory to $(pwd)"

#     # Install PyTorch packages separately and independently
#     echo "Installing PyTorch 2.6.0..."
#     conda run -n cgflow-env pip install torch==2.6.0 --find-links https://data.pyg.org/whl/torch-2.6.0+cu124.html
    
#     echo "Installing PyTorch Geometric..."
#     conda run -n cgflow-env pip install torch-geometric>=2.4.0
    
#     echo "Installing PyTorch Scatter..."
#     conda run -n cgflow-env pip install torch-scatter>=2.1.2 --find-links https://data.pyg.org/whl/torch-2.6.0+cu124.html
    
#     echo "Installing PyTorch Sparse..."
#     conda run -n cgflow-env pip install torch-sparse>=0.6.18 --find-links https://data.pyg.org/whl/torch-2.6.0+cu124.html
    
#     echo "Installing PyTorch Cluster..."
#     conda run -n cgflow-env pip install torch-cluster>=1.6.3 --find-links https://data.pyg.org/whl/torch-2.6.0+cu124.html

#     # Install CGFlow in editable mode
#     echo "Installing CGFlow in editable mode..."
#     conda run -n cgflow-env pip install -e '.[extra]'
    
#     echo "Installing Uni-Dock tools..."
#     conda run -n cgflow-env pip install git+https://github.com/dptech-corp/Uni-Dock.git#subdirectory=unidock_tools

#     # Create data directories and download data
#     echo "Setting up CGFlow data directories"
#     mkdir -p experiments/data/complex
#     cd experiments/data/complex
    
#     if [ ! -f "plinder_15A.zip" ]; then
#         echo "Downloading plinder data"
#         curl -L -o plinder_15A.zip https://figshare.com/ndownloader/files/54405473
#         unzip plinder_15A.zip
#     fi
    
#     cd ../
#     if [ ! -f "LIT-PCBA.tar.gz" ]; then
#         echo "Downloading LIT-PCBA data"
#         curl -L -o LIT-PCBA.tar.gz https://figshare.com/ndownloader/files/54411395
#         tar -xzvf LIT-PCBA.tar.gz
#     fi

#     mkdir -p envs
#     cd envs
#     if [ ! -f "stock.tar.gz" ]; then
#         echo "Downloading stock environment data"
#         conda run -n cgflow-env gdown 11EXcLEFzpD430ML0gt5Lwnx65PQfHIVP
#         tar -xzvf stock.tar.gz
#     fi

#     cd ../../ # back to cgflow root
#     mkdir -p weights
#     cd weights
#     if [ ! -f "cgflow_weights.tar.gz" ]; then
#         echo "Downloading CGFlow weights"
#         conda run -n cgflow-env gdown 1UpdOxfMVdALdAPpzG_dXF72diP2AbHOl
#     fi

#     cd ../../../.. # Go back to the root of the repo
#     echo "Changed directory back to $(pwd)"
# else
#     echo "Warning: Directory src/cgflow not found. Skipping CGFlow setup."
# fi

# 4. Create Synformer environment
echo_step "Setting up Synformer environment"
create_env_if_not_exists "synformer-env" "$ENV_DIR/synformer.yml"

# Setup synformer
if [ -d "src/synformer" ]; then
    cd src/synformer
    echo "Changed directory to $(pwd)"

    # Install synformer locally
    echo "Installing synformer (editable mode, no dependencies) into synformer-env environment"
    conda run -n synformer-env pip install --no-deps -e .

    # Create synformer data directories
    SYNFORMER_DATA_DIR="data"
    SYNFORMER_PROCESSED_DIR="$SYNFORMER_DATA_DIR/processed/comp_2048"
    SYNFORMER_WEIGHTS_DIR="$SYNFORMER_DATA_DIR/trained_weights"

    echo "Creating synformer data directories"
    mkdir -p "$SYNFORMER_PROCESSED_DIR"
    mkdir -p "$SYNFORMER_WEIGHTS_DIR"

    # Download synformer processed files
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

    # Download synformer checkpoint
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

# 5. Create Boltz environment
echo_step "Setting up Boltz environment"
create_env_if_not_exists "boltz-env" "$ENV_DIR/boltz.yml"

# 6. Create Uni-dock environment
echo_step "Setting up Uni-dock environment"
create_env_if_not_exists "unidock-env" "$ENV_DIR/unidock.yml"

# 7. Create Uni-GBSA environment
echo_step "Setting up Uni-GBSA environment"
create_env_if_not_exists "unigbsa-env" "$ENV_DIR/unigbsa.yml"

# Setup VFU
echo_step "Setting up VFU executables"
if [ -d "src/VFU/executables" ]; then
    cd src/VFU/executables
    echo "Changed directory to $(pwd)"

    # Make VFU executables executable
    echo "Making files in $(pwd) executable"
    chmod +x *

    cd ../../.. # Go back to the root of the repo
    echo "Changed directory back to $(pwd)"
elif [ -d "src/VFU" ]; then
     echo "Warning: Directory src/VFU/executables not found, but src/VFU exists."
else
    echo "Warning: Directory src/VFU not found. Skipping VFU setup."
fi

echo "=========================================="
echo "Setup script finished."
echo "=========================================="
echo "Created the following conda environments:"
echo "  - diffsbdd-env     (for DiffSBDD)"
echo "  - pocket2mol-env   (for Pocket2Mol)"
# echo "  - cgflow-env       (for CGFlow)"
echo "  - synformer-env    (for Synformer)"
echo "  - boltz-env        (for Boltz)"
echo "  - unidock-env      (for Uni-dock)"
echo "  - unigbsa-env      (for Uni-GBSA)"
echo ""
echo "To activate an environment, use:"
echo "  conda activate <environment-name>"
echo ""
echo "Please refer to README.md for next steps"
echo "==========================================" 