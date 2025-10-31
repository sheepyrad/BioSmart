import streamlit as st
import os
from pathlib import Path
import tempfile
import py3Dmol
import re
import streamlit.components.v1 as components
import logging
import numpy as np  # Added for grid generation
from Bio.PDB import PDBParser, PDBIO  # Added for grid generation
from io import StringIO # Added for grid generation
import json # Added for config download/upload

# Set up logging
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Pipeline Configuration",
    page_icon="⚙️",
    layout="wide"
)

# Add custom CSS for full-width layout and better form styling
st.markdown("""
    <style>
    .main {
        padding: 0rem 1rem;
    }
    .stApp {
        max-width: 100%;
        margin: 0 auto;
    }
    .block-container {
        max-width: 100%;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    .st-emotion-cache-1v0mbdj {
        width: 100%;
    }
    /* Add custom styling for forms */
    .stForm {
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .form-header {
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# --- Initialize session state keys for widgets and control flow ---
# This centralizes default values and ensures keys exist.

# Core settings
if "pipeline_config" not in st.session_state:
    st.session_state.pipeline_config = None # Stores the *finalized* config
if "stop_pipeline" not in st.session_state:
    st.session_state.stop_pipeline = False
if "model_selection" not in st.session_state:
    st.session_state.model_selection = "diffsbdd" # Key for the model selectbox
if "model_update_requested" not in st.session_state:
    st.session_state.model_update_requested = False

# File Inputs (paths stored here, file objects handled temporarily)
if "pdb_path_input" not in st.session_state:
    st.session_state.pdb_path_input = ""

# DiffSBDD Specific
if "diffsbdd_resi_list" not in st.session_state:
    st.session_state.diffsbdd_resi_list = "A:719 A:770 A:841 A:856 A:887 A:888"
if "diffsbdd_sanitize" not in st.session_state:
    st.session_state.diffsbdd_sanitize = True
if "diffsbdd_size_x" not in st.session_state:
    st.session_state.diffsbdd_size_x = 40.0
if "diffsbdd_size_y" not in st.session_state:
    st.session_state.diffsbdd_size_y = 40.0
if "diffsbdd_size_z" not in st.session_state:
    st.session_state.diffsbdd_size_z = 40.0

# Pocket2Mol Specific
if "pocket2mol_bbox_size" not in st.session_state:
    st.session_state.pocket2mol_bbox_size = 23.0
if "pocket2mol_dock_size_x" not in st.session_state:
    st.session_state.pocket2mol_dock_size_x = 38.0
if "pocket2mol_dock_size_y" not in st.session_state:
    st.session_state.pocket2mol_dock_size_y = 70.0
if "pocket2mol_dock_size_z" not in st.session_state:
    st.session_state.pocket2mol_dock_size_z = 58.0

# Common Center Coordinates
if "center_x" not in st.session_state:
    st.session_state.center_x = 114.817
if "center_y" not in st.session_state:
    st.session_state.center_y = 75.602
if "center_z" not in st.session_state:
    st.session_state.center_z = 82.416

# Common Basic/Advanced Params
if "n_samples_input" not in st.session_state:
    st.session_state.n_samples_input = 5
if "exhaustiveness_level_input" not in st.session_state:
    st.session_state.exhaustiveness_level_input = "balance"
if "num_rounds_input" not in st.session_state:
    st.session_state.num_rounds_input = 1
if "top_n_input" not in st.session_state:
    st.session_state.top_n_input = 5
if "output_dir_path_input" not in st.session_state:
    st.session_state.output_dir_path_input = "outputs/pipeline_output"
if "score_threshold_input" not in st.session_state:
    st.session_state.score_threshold_input = 0.7

# Boltz-2 Specific
if "boltz_pocket_residues_input" not in st.session_state:
    st.session_state.boltz_pocket_residues_input = ""
if "msa_path_input" not in st.session_state:
    st.session_state.msa_path_input = "/home/conrad_hku/Drug_pipeline/msa/NS5_full.a3m"

# Box Generation Input
if "generate_box_residues_input" not in st.session_state:
    st.session_state.generate_box_residues_input = ""

# MedChem Filter - Only generative design mode supported

# CGFlow Specific
if "cgflow_checkpoint_path" not in st.session_state:
    st.session_state.cgflow_checkpoint_path = "src/cgflow/result/opt/unidock_qed/NS5/250812_160000/model_state.pt"
if "cgflow_config_path" not in st.session_state:
    st.session_state.cgflow_config_path = "src/cgflow/configs/opt/NS5.yaml"

# --- Control flow for applying loaded config ---
if "_apply_loaded_config_on_next_run" not in st.session_state:
    st.session_state._apply_loaded_config_on_next_run = False
if "_pending_loaded_config" not in st.session_state:
    st.session_state._pending_loaded_config = None

# --- Apply pending loaded config (Runs *before* widgets are drawn) ---
if st.session_state._apply_loaded_config_on_next_run:
    pending_config = st.session_state._pending_loaded_config
    apply_success = False
    if pending_config:
        try:
            logger.info(f"Applying pending loaded configuration: {pending_config}")
            # Directly update session state keys from loaded config
            st.session_state.model_selection = pending_config.get("model", st.session_state.model_selection)
            current_model_loaded = st.session_state.model_selection

            st.session_state.pdb_path_input = pending_config.get("pdbfile", st.session_state.pdb_path_input)
            # Note: receptor field in config will be the same as pdbfile, so no separate handling needed

            if "center" in pending_config and len(pending_config["center"]) == 3:
                st.session_state.center_x = float(pending_config["center"][0])
                st.session_state.center_y = float(pending_config["center"][1])
                st.session_state.center_z = float(pending_config["center"][2])

            st.session_state.n_samples_input = int(pending_config.get("n_samples", st.session_state.n_samples_input))
            st.session_state.exhaustiveness_level_input = pending_config.get("exhaustiveness_level", st.session_state.exhaustiveness_level_input)
            # Handle top_n - use max_variants if present for backward compatibility
            if "top_n" in pending_config:
                st.session_state.top_n_input = int(pending_config.get("top_n"))
            elif "max_variants" in pending_config:
                st.session_state.top_n_input = int(pending_config.get("max_variants"))
            # Otherwise keep existing value
            st.session_state.num_rounds_input = int(pending_config.get("num_rounds", st.session_state.num_rounds_input))
            st.session_state.score_threshold_input = float(pending_config.get("score_threshold", st.session_state.score_threshold_input))
            
            # Load Boltz-2 configuration
            st.session_state.boltz_pocket_residues_input = pending_config.get("boltz_pocket_residues", st.session_state.boltz_pocket_residues_input)
            st.session_state.msa_path_input = pending_config.get("msa_path", st.session_state.msa_path_input)

            # MedChem filter mode is now always generative (backward compatibility: ignore old threshold settings)

            if "out_dir" in pending_config:
                st.session_state.output_dir_path_input = pending_config["out_dir"]

            if current_model_loaded == "diffsbdd":
                st.session_state.diffsbdd_resi_list = pending_config.get("resi_list", st.session_state.diffsbdd_resi_list)
                st.session_state.diffsbdd_sanitize = bool(pending_config.get("sanitize", st.session_state.diffsbdd_sanitize))
                if "box_size" in pending_config and len(pending_config["box_size"]) == 3:
                    st.session_state.diffsbdd_size_x = float(pending_config["box_size"][0])
                    st.session_state.diffsbdd_size_y = float(pending_config["box_size"][1])
                    st.session_state.diffsbdd_size_z = float(pending_config["box_size"][2])
            elif current_model_loaded == "pocket2mol":
                st.session_state.pocket2mol_bbox_size = float(pending_config.get("bbox_size", st.session_state.pocket2mol_bbox_size))
                if "box_size" in pending_config and len(pending_config["box_size"]) == 3:
                    st.session_state.pocket2mol_dock_size_x = float(pending_config["box_size"][0])
                    st.session_state.pocket2mol_dock_size_y = float(pending_config["box_size"][1])
                    st.session_state.pocket2mol_dock_size_z = float(pending_config["box_size"][2])
            elif current_model_loaded == "cgflow":
                st.session_state.cgflow_checkpoint_path = pending_config.get("checkpoint", st.session_state.cgflow_checkpoint_path)
                st.session_state.cgflow_config_path = pending_config.get("cgflow_config", st.session_state.cgflow_config_path)

            apply_success = True
            st.success("Configuration loaded successfully and fields updated. Review and finalize.")

        except (ValueError, TypeError, IndexError, KeyError) as e:
            logger.error(f"Error applying loaded configuration: {e}", exc_info=True)
            st.error(f"Error applying loaded configuration: {e}. Please check the file format.")
        except Exception as e: # Catch other potential errors
            logger.error(f"Unexpected error applying loaded configuration: {e}", exc_info=True)
            st.error(f"Unexpected error applying loaded configuration: {e}")

    # Reset flag and pending data regardless of success
    st.session_state._apply_loaded_config_on_next_run = False
    st.session_state._pending_loaded_config = None

# --- Helper Functions (Unchanged) ---
def parse_residue_list(resi_list):
    """Parse residue list string into a list of chain and residue numbers"""
    residues = []
    # Handle potential None or empty string gracefully
    if resi_list:
        for res in resi_list.split():
            if ':' in res:
                chain, num = res.split(':')
                try:
                    residues.append((chain, int(num)))
                except ValueError:
                    logger.warning(f"Could not parse residue number: {num} in {res}")
    return residues

def add_box(view, center=[0,0,0], dimensions=[10,10,10], color='blue', opacity=0.4, add_wireframe=True):
    """Adds a box to a py3Dmol view object.
    
    Parameters
    ----------
    view : py3Dmol.view
        The py3Dmol view object to add the box to
    center : list of float, default [0,0,0]
        The x,y,z coordinates of the box center in Angstroms
    dimensions : list of float, default [10,10,10]
        The width, height, depth of the box in Angstroms
    color : str, default 'blue'
        The color of the box
    opacity : float, default 0.4
        The opacity of the box (0.0 to 1.0)
    add_wireframe : bool, default True
        Whether to add a wireframe outline of the box
    """
    # Add transparent box
    view.addBox({
        'center': {'x': center[0], 'y': center[1], 'z': center[2]},
        'dimensions': {'w': dimensions[0], 'h': dimensions[1], 'd': dimensions[2]},
        'color': color,
        'opacity': opacity
    })
    
    # Add wireframe box if requested
    if add_wireframe:
        view.addBox({
            'center': {'x': center[0], 'y': center[1], 'z': center[2]},
            'dimensions': {'w': dimensions[0], 'h': dimensions[1], 'd': dimensions[2]},
            'color': color,
            'wireframe': True
        })

def calculate_box_from_residues(pdb_content_str, residue_list_str, buffer=5.0):
    """
    Generate grid configuration based on PDB content and targeted residues.
    Adapted from code by Pritam Kumar Panda.

    Args:
        pdb_content_str (str): The content of the PDB file as a string.
        residue_list_str (str): Space-separated residue identifiers (e.g., "A:123 B:456"). Can also handle newline-separated.
        buffer (float): Buffer distance to add around the min/max coordinates.

    Returns:
        dict: Dictionary containing 'center' and 'size' lists, or None if error.
    """
    try:
        # Use StringIO to treat the string as a file
        pdb_file_handle = StringIO(pdb_content_str)
        
        # Parse the PDB file
        parser = PDBParser(QUIET=True)
        structure = parser.get_structure('protein', pdb_file_handle)

        # Handle both space and newline separated input for residues
        residues_to_target = parse_residue_list(residue_list_str.replace('\\n', ' '))
        if not residues_to_target:
            st.error('Invalid or empty residue list provided for box generation.')
            return None

        coords = []
        found_residues = set()

        # Extract coordinates of specified residues
        for model in structure: # Iterate through models
            for chain in model: # Iterate through chains
                for res in chain.get_residues():
                    # Check if the residue tuple (chain_id, res_id) is in our target list
                    res_id_tuple = (chain.id, res.id[1])
                    if res_id_tuple in residues_to_target:
                        found_residues.add(res_id_tuple)
                        for atom in res:
                            coords.append(atom.coord)
        
        # Verify all requested residues were found
        missing_residues = set(residues_to_target) - found_residues
        if missing_residues:
            st.warning(f"Could not find coordinates for residues: {', '.join([f'{c}:{r}' for c,r in missing_residues])}")

        if not coords:
            st.error('No atomic coordinates found for the specified residues.')
            return None

        coords = np.array(coords)
        min_coords = coords.min(axis=0) - buffer
        max_coords = coords.max(axis=0) + buffer

        center = (min_coords + max_coords) / 2.0
        size = max_coords - min_coords

        # Ensure minimum size to avoid issues with single points/atoms
        min_dimension = 1.0 
        size = np.maximum(size, min_dimension)

        return {
            'center': center.tolist(),
            'size': size.tolist()
        }

    except Exception as e:
        st.error(f"Error during grid box generation: {str(e)}")
        logger.error(f"Error calculating box from residues: {e}", exc_info=True)
        return None

def visualize_protein_residues(pdb_content, selected_residues=None, center=None, box_size=None, bbox_size=None):
    """Create a py3Dmol visualization of the protein with highlighted residues and docking box"""
    view = py3Dmol.view(width=800, height=600)
    view.addModel(pdb_content, "pdb")

    # Set up the basic protein visualization
    view.setStyle({'cartoon': {'color': 'lightgray'}})

    # Highlight selected residues
    if selected_residues:
        for chain, resnum in selected_residues:
            try:
                # Use integer for resi if possible
                resnum_int = int(resnum)
                view.addStyle({
                    'chain': chain,
                    'resi': resnum_int
                }, {
                    'cartoon': {'color': 'red'},
                    'stick': {'color': 'red'},
                })
                view.addLabel(f"{chain}:{resnum_int}", {'fontColor':'black', 'backgroundColor': 'lightgray', 'showBackground': True}, {'chain': chain, 'resi': resnum_int})
            except ValueError:
                logger.warning(f"Could not parse resnum as integer for visualization: {resnum} in chain {chain}")


    # Add docking box if parameters are provided
    if center and box_size and all(isinstance(x, (int, float)) for x in box_size) and len(box_size)==3:
        add_box(view, center=center, dimensions=box_size, color='blue')

    # Add Pocket2Mol generation box if parameters are provided
    if center and bbox_size and isinstance(bbox_size, (int, float)):
        dimensions = [bbox_size, bbox_size, bbox_size]
        add_box(view, center=center, dimensions=dimensions, color='green')

    view.zoomTo()

    # Critical: render before generating HTML
    view.render()

    # Get the HTML representation
    html = view._make_html()

    # Return both the view object and HTML
    return view, html


st.title("⚙️ Pipeline Configuration")
st.markdown("""
    Configure the parameters for your drug discovery pipeline run.
    Required fields are marked with an asterisk (*).
""")

# Track previous model selection to detect changes
if "previous_model_selection" not in st.session_state:
    st.session_state.previous_model_selection = st.session_state.get("model_selection", "diffsbdd")

# ============================================================================
# SECTION 1: MODEL SELECTION
# ============================================================================
st.markdown("---")
st.header("🤖 Step 1: Select AI Model")
selected_model = st.selectbox(
    "AI Model for Molecule Generation *",
    options=["diffsbdd", "pocket2mol", "cgflow"],
    format_func=lambda x: {"diffsbdd": "DiffSBDD", "pocket2mol": "Pocket2Mol", "cgflow": "CGFlow (finetuned)"}[x],
    key="model_selection",
    help="Select the AI model for generating molecules. Changing this will update available parameters below."
)

# Check if model changed and apply defaults
if selected_model != st.session_state.previous_model_selection:
    # Apply cgflow-specific defaults on model change
    if selected_model == "cgflow":
        st.session_state.pocket2mol_dock_size_x = 20.0
        st.session_state.pocket2mol_dock_size_y = 20.0
        st.session_state.pocket2mol_dock_size_z = 20.0
        if "cgflow_checkpoint_path" not in st.session_state:
            st.session_state.cgflow_checkpoint_path = "src/cgflow/result/opt/unidock_qed/NS5/250812_160000/model_state.pt"
        if "cgflow_config_path" not in st.session_state:
            st.session_state.cgflow_config_path = "src/cgflow/configs/opt/NS5.yaml"
    # Update previous model selection
    st.session_state.previous_model_selection = selected_model

# Get current model from session state (using the selectbox key)
current_model = st.session_state.model_selection

# ============================================================================
# SECTION 2: PDB FILE INPUT
# ============================================================================
st.markdown("---")
st.header("📁 Step 2: Target Protein Structure")

# Add PDB indexing reminder
st.info("""
**⚠️ Important:** The input protein PDB file **must be 1-indexed** (residue numbering starts from 1). 
If your PDB file uses non-standard indexing, use [pdb-tools](https://www.bonvinlab.org/pdb-tools/) to renumber it: `pdb_reres -1 input.pdb > output_reindexed.pdb`
""")

col1, col2 = st.columns(2)
with col1:
    pdb_file = st.file_uploader(
        "Upload PDB File",
        type=["pdb"],
        help="Upload the target protein PDB file",
        key="pdb_file_uploader"
    )
with col2:
    st.text_input(
        "OR Enter PDB File Path *",
        placeholder="Path to PDB file on server",
        help="Specify the path to the PDB file on the server",
        key="pdb_path_input"
    )

# Check if PDB file is provided (required)
pdb_file_state = st.session_state.get("pdb_file_uploader")
pdb_path_state = st.session_state.get("pdb_path_input", "")

if not pdb_file_state and not pdb_path_state:
    st.error("⚠️ **Required**: Please upload a PDB file or specify a PDB file path.")

# ============================================================================
# SECTION 3: MODEL-SPECIFIC PARAMETERS
# ============================================================================
st.markdown("---")
st.header("⚙️ Step 3: Model Configuration")

if current_model == "diffsbdd":
    st.subheader("DiffSBDD Parameters")
    st.text_input(
        "Residue List *",
        help="Space-separated residue identifiers (format: CHAIN:RESIDUE, e.g., 'A:719 A:770 A:841')",
        key="diffsbdd_resi_list"
    )
    st.checkbox(
        "Sanitize Generated Molecules",
        help="Apply sanitization to generated molecules",
        key="diffsbdd_sanitize"
    )
elif current_model == "pocket2mol":
    st.info("Pocket2Mol uses 3D pocket information. Configure the bounding box in the Box Settings section below.")
elif current_model == "cgflow":
    st.subheader("CGFlow Configuration")
    st.text_input(
        "Checkpoint Path (.pt) *",
        help="Path to the fine-tuned CGFlow checkpoint file on the server",
        key="cgflow_checkpoint_path"
    )
    st.text_input(
        "Config Path (.yaml) *",
        help="Path to the CGFlow YAML configuration file on the server",
        key="cgflow_config_path"
    )

# ============================================================================
# SECTION 4: GENERATION PARAMETERS
# ============================================================================
st.markdown("---")
st.header("🧪 Step 4: Generation Settings")

st.number_input(
    "Number of Samples to Generate *",
    min_value=1,
    max_value=50000,
    step=1,
    help="Number of compounds to generate per round",
    key="n_samples_input"
)

# ============================================================================
# SECTION 5: BOX CONFIGURATION
# ============================================================================
st.markdown("---")
st.header("📦 Step 5: Binding Site Box Configuration")

if current_model == "cgflow":
    st.info("CGFlow uses a fine-tuned target pocket. Only docking box configuration is needed below.")
else:
    # Box Generation Tool
    with st.expander("🔧 Auto-Generate Box from Residues", expanded=False):
        st.markdown("Automatically calculate box center and dimensions based on selected residues.")
        st.caption("Grid generation logic adapted from code by Pritam Kumar Panda.")
        
        # Pre-fill with DiffSBDD residues if available
        default_residues_for_boxgen = ""
        if current_model == "diffsbdd":
            space_separated_residues = st.session_state.get("diffsbdd_resi_list", "")
            residue_parts = [res for res in space_separated_residues.split() if res.strip()]
            if residue_parts:
                default_residues_for_boxgen = "\\n".join(residue_parts)
        
        st.text_area(
            "Residues for Box Generation",
            value=default_residues_for_boxgen,
            help="Enter target residues in format 'Chain:ResidueNumber', one per line or space-separated (e.g., A:156).",
            key="generate_box_residues_input"
        )
        
        if st.button("Calculate and Populate Box Dimensions", key="generate_box_button"):
            pdb_content_for_gen = None
            pdb_file_state = st.session_state.get("pdb_file_uploader")
            pdb_path_state = st.session_state.get("pdb_path_input")
            
            if pdb_file_state is not None:
                try:
                    pdb_content_for_gen = pdb_file_state.getvalue().decode('utf-8')
                    logger.info("Using uploaded PDB for box generation.")
                except Exception as e:
                    st.error(f"Error reading uploaded PDB file: {e}")
            elif pdb_path_state and os.path.exists(pdb_path_state):
                try:
                    with open(pdb_path_state, 'r') as f:
                        pdb_content_for_gen = f.read()
                    logger.info(f"Using PDB file from path {pdb_path_state} for box generation.")
                except Exception as e:
                    st.error(f"Error reading PDB file from path: {e}")
            else:
                st.error("Please upload or specify a valid PDB file path first.")
            
            residues_for_boxgen_state = st.session_state.get("generate_box_residues_input", "")
            if pdb_content_for_gen and residues_for_boxgen_state:
                with st.spinner("Calculating box dimensions..."):
                    box_params = calculate_box_from_residues(pdb_content_for_gen, residues_for_boxgen_state)
                
                if box_params:
                    st.session_state.center_x = float(box_params['center'][0])
                    st.session_state.center_y = float(box_params['center'][1])
                    st.session_state.center_z = float(box_params['center'][2])
                    
                    calculated_size = box_params['size']
                    if current_model == "diffsbdd":
                        st.session_state.diffsbdd_size_x = float(calculated_size[0])
                        st.session_state.diffsbdd_size_y = float(calculated_size[1])
                        st.session_state.diffsbdd_size_z = float(calculated_size[2])
                    else:  # pocket2mol
                        st.session_state.pocket2mol_dock_size_x = float(calculated_size[0])
                        st.session_state.pocket2mol_dock_size_y = float(calculated_size[1])
                        st.session_state.pocket2mol_dock_size_z = float(calculated_size[2])
                        st.session_state.pocket2mol_bbox_size = float(round(max(calculated_size)))
                    
                    st.success("✅ Box dimensions calculated and populated below!")
                    st.rerun()
                else:
                    st.error("Failed to calculate box dimensions.")
            elif not residues_for_boxgen_state:
                st.warning("Please enter residues for box generation.")

# Center Coordinates
st.subheader("Box Center Coordinates")
col_center1, col_center2, col_center3 = st.columns(3)
with col_center1:
    st.number_input("Center X", format="%.3f", key="center_x")
with col_center2:
    st.number_input("Center Y", format="%.3f", key="center_y")
with col_center3:
    st.number_input("Center Z", format="%.3f", key="center_z")

# Model-specific box dimensions
if current_model == "diffsbdd":
    st.subheader("Docking Box Dimensions")
    st.caption("DiffSBDD uses the residue list for molecule generation. These dimensions define the docking box.")
    col_box1, col_box2, col_box3 = st.columns(3)
    with col_box1:
        st.number_input("Docking Size X", min_value=1.0, format="%.1f", key="diffsbdd_size_x")
    with col_box2:
        st.number_input("Docking Size Y", min_value=1.0, format="%.1f", key="diffsbdd_size_y")
    with col_box3:
        st.number_input("Docking Size Z", min_value=1.0, format="%.1f", key="diffsbdd_size_z")
elif current_model == "pocket2mol":
    st.subheader("Molecule Generation Box (Pocket2Mol)")
    st.caption("Cubic space where Pocket2Mol will generate molecules.")
    st.number_input(
        "Generation Box Size",
        min_value=1.0,
        format="%.1f",
        help="Single value used for all dimensions (cubic box)",
        key="pocket2mol_bbox_size"
    )
    st.subheader("Docking Box Dimensions")
    st.caption("Space where molecule docking will occur (can differ from generation box).")
    col_box1, col_box2, col_box3 = st.columns(3)
    with col_box1:
        st.number_input("Docking Size X", min_value=1.0, format="%.1f", key="pocket2mol_dock_size_x")
    with col_box2:
        st.number_input("Docking Size Y", min_value=1.0, format="%.1f", key="pocket2mol_dock_size_y")
    with col_box3:
        st.number_input("Docking Size Z", min_value=1.0, format="%.1f", key="pocket2mol_dock_size_z")
elif current_model == "cgflow":
    st.subheader("Docking Box Dimensions")
    st.caption("Box used for docking generated molecules.")
    col_box1, col_box2, col_box3 = st.columns(3)
    with col_box1:
        st.number_input("Docking Size X", min_value=1.0, format="%.1f", key="pocket2mol_dock_size_x")
    with col_box2:
        st.number_input("Docking Size Y", min_value=1.0, format="%.1f", key="pocket2mol_dock_size_y")
    with col_box3:
        st.number_input("Docking Size Z", min_value=1.0, format="%.1f", key="pocket2mol_dock_size_z")

# ============================================================================
# SECTION 6: DOCKING PARAMETERS
# ============================================================================
st.markdown("---")
st.header("🎯 Step 6: Docking Configuration")

col_dock1, col_dock2 = st.columns(2)
with col_dock1:
    st.selectbox(
        "Docking Exhaustiveness Level",
        options=["fast", "balance", "detail"],
        format_func=lambda x: {
            "fast": "Fast (128) - Quick screening",
            "balance": "Balance (384) - Balanced speed/accuracy", 
            "detail": "Detail (512) - Thorough search"
        }[x],
        help="Higher levels provide more thorough search but take longer.",
        key="exhaustiveness_level_input"
    )
with col_dock2:
    st.number_input(
        "Number of Pipeline Rounds",
        min_value=1,
        max_value=1000,
        step=1,
        help="Number of rounds to run the pipeline iteratively",
        key="num_rounds_input"
    )

# ============================================================================
# SECTION 7: FILTERING PARAMETERS
# ============================================================================
st.markdown("---")
st.header("🔍 Step 7: Filtering Configuration")

# Retrosynthesis Filtering
with st.expander("Retrosynthesis Filtering", expanded=True):
    st.number_input(
        "Retrosynthesis Score Threshold",
        min_value=0.0,
        max_value=1.0,
        step=0.1,
        format="%.1f",
        help="Minimum score threshold for variants to proceed to MedChem filtering. Higher = more restrictive.",
        key="score_threshold_input"
    )

# MedChem Filtering
with st.expander("MedChem Filtering", expanded=True):
    st.info("Evaluates compounds against medicinal chemistry rules. Uses generative design filtering - compounds must pass BOTH generative design rules.")

# Boltz-2 Filtering
with st.expander("Boltz-2 Structure Prediction", expanded=False):
    st.info("Predicts protein-ligand structures and evaluates binding affinity. Provides annotations only (no filtering).")
    st.text_input(
        "Pocket Constraint Residues (comma-separated)",
        placeholder="e.g., 156,158,202,204",
        help="Residue numbers (1-indexed) to guide binding prediction. Leave empty for no constraints.",
        key="boltz_pocket_residues_input"
    )
    st.text_input(
        "MSA File Path (.a3m)",
        placeholder="/path/to/alignment.a3m",
        help="Absolute path to precomputed MSA in A3M format for Boltz-2.",
        key="msa_path_input"
    )
    st.caption("💡 **Tip:** Use the same residues from your DiffSBDD residue list as pocket constraints.")

# ============================================================================
# SECTION 8: PIPELINE EXECUTION PARAMETERS
# ============================================================================
st.markdown("---")
st.header("⚡ Step 8: Pipeline Execution Settings")

st.number_input(
    "Top Variants per Compound",
    min_value=1,
    max_value=50,
    step=1,
    help="Maximum number of variants to extract per compound after retrosynthesis",
    key="top_n_input"
)

# ============================================================================
# SECTION 9: OUTPUT CONFIGURATION (Less Important - Moved Later)
# ============================================================================
st.markdown("---")
st.header("💾 Step 9: Output Settings")

st.text_input(
    "Output Directory Path *",
    help="Path where results will be stored. Can be absolute or relative to project root.",
    key="output_dir_path_input"
)
st.caption("**Examples:** `outputs/my_experiment` (relative) or `/home/user/results` (absolute)")

# ============================================================================
# SECTION 10: VISUALIZATION
# ============================================================================
st.markdown("---")
st.header("🔬 Step 10: Structure Visualization")

# Get PDB content for visualization
pdb_file_state = st.session_state.get("pdb_file_uploader")
pdb_path_state = st.session_state.get("pdb_path_input")
current_vis_model = st.session_state.model_selection

pdb_content_for_vis = None
if pdb_file_state is not None:
    try:
        pdb_content_for_vis = pdb_file_state.getvalue().decode('utf-8')
    except Exception as e:
        st.error(f"Error reading uploaded PDB for visualization: {e}")
elif pdb_path_state and os.path.exists(pdb_path_state):
    try:
        with open(pdb_path_state, 'r') as f:
            pdb_content_for_vis = f.read()
    except Exception as e:
        st.error(f"Error reading PDB file from path for visualization: {e}")

if pdb_content_for_vis:
    if current_vis_model == "diffsbdd":
        st.write("Selected residues are highlighted in **red**. Docking box shown in **blue**.")
    elif current_vis_model == "pocket2mol":
        st.write("Pocket2Mol generation box shown in **green**. Docking box shown in **blue**.")
    else:
        st.write("Docking box shown in **blue**.")
    
    # Get current box parameters
    center_vis = [st.session_state.center_x, st.session_state.center_y, st.session_state.center_z]
    box_size_vis = None
    bbox_size_vis = None
    
    if current_vis_model == "diffsbdd":
        selected_residues_vis = parse_residue_list(st.session_state.diffsbdd_resi_list)
        box_size_vis = [
            st.session_state.diffsbdd_size_x,
            st.session_state.diffsbdd_size_y,
            st.session_state.diffsbdd_size_z
        ]
    elif current_vis_model == "pocket2mol":
        selected_residues_vis = None
        box_size_vis = [
            st.session_state.pocket2mol_dock_size_x,
            st.session_state.pocket2mol_dock_size_y,
            st.session_state.pocket2mol_dock_size_z
        ]
        bbox_size_vis = st.session_state.pocket2mol_bbox_size
    else:  # cgflow
        selected_residues_vis = None
        box_size_vis = [
            st.session_state.pocket2mol_dock_size_x,
            st.session_state.pocket2mol_dock_size_y,
            st.session_state.pocket2mol_dock_size_z
        ]
        bbox_size_vis = None
    
    try:
        view, html = visualize_protein_residues(
            pdb_content_for_vis,
            selected_residues=selected_residues_vis,
            center=center_vis,
            box_size=box_size_vis,
            bbox_size=bbox_size_vis
        )
        components.html(html, height=600, width=800)
        st.caption("""
        **Controls:** Rotate (click+drag) | Zoom (scroll) | Pan (right-click+drag) | Reset (double-click)
        """)
    except Exception as e:
        st.error(f"Error generating protein visualization: {e}")
        logger.error(f"Error during py3Dmol visualization: {e}", exc_info=True)
else:
    st.info("Upload or specify a PDB file above to see the structure visualization.")

# ============================================================================
# SECTION 11: CONFIGURATION MANAGEMENT
# ============================================================================
st.markdown("---")
st.header("💾 Configuration Management")

col_dl, col_ul = st.columns(2)

with col_dl:
    # Download button - Create config dynamically from current state for download
    # Disable if required fields (like output dir name) are missing
    config_ready_for_download = bool(st.session_state.get("output_dir_path_input"))
    config_json_data = ""
    download_filename = "pipeline_config.json" # Default filename
    if config_ready_for_download:
        # Build the config dict *for download* based on current widget states
        download_config = {}
        download_config["model"] = st.session_state.model_selection
        
        # Files (store paths from state) - use PDB file for both generation and docking
        pdb_path = st.session_state.pdb_path_input
        download_config["pdbfile"] = pdb_path
        download_config["receptor"] = pdb_path  # Use same file as receptor

        # Model specific
        if download_config["model"] == "diffsbdd":
             download_config["checkpoint"] = "src/DiffSBDD/checkpoints/crossdocked_fullatom_cond.ckpt"
             download_config["resi_list"] = st.session_state.diffsbdd_resi_list
             download_config["sanitize"] = st.session_state.diffsbdd_sanitize
             download_config["box_size"] = [
                 st.session_state.diffsbdd_size_x, 
                 st.session_state.diffsbdd_size_y, 
                 st.session_state.diffsbdd_size_z
             ]
        elif download_config["model"] == "pocket2mol": # pocket2mol
            download_config["bbox_size"] = st.session_state.pocket2mol_bbox_size
            download_config["box_size"] = [ # Docking box for pocket2mol
                st.session_state.pocket2mol_dock_size_x,
                st.session_state.pocket2mol_dock_size_y,
                st.session_state.pocket2mol_dock_size_z
            ]
        else:
            # cgflow presets
            download_config["checkpoint"] = st.session_state.cgflow_checkpoint_path
            download_config["cgflow_config"] = st.session_state.cgflow_config_path
            # Docking box for CGFlow
            download_config["box_size"] = [
                st.session_state.pocket2mol_dock_size_x,
                st.session_state.pocket2mol_dock_size_y,
                st.session_state.pocket2mol_dock_size_z
            ]

        # Common parameters
        download_config["n_samples"] = st.session_state.n_samples_input
        download_config["center"] = [st.session_state.center_x, st.session_state.center_y, st.session_state.center_z]
        download_config["exhaustiveness_level"] = st.session_state.exhaustiveness_level_input
        download_config["top_n"] = st.session_state.top_n_input
        download_config["num_rounds"] = st.session_state.num_rounds_input
        download_config["score_threshold"] = st.session_state.score_threshold_input
        
        # Add Boltz-2 configuration
        download_config["boltz_pocket_residues"] = st.session_state.boltz_pocket_residues_input
        download_config["msa_path"] = st.session_state.msa_path_input
        
        # Use output dir path for config value and extract name for filename
        output_dir_path_value = st.session_state.get("output_dir_path_input", "outputs/pipeline_output")
        download_config["out_dir"] = output_dir_path_value
        # Extract just the directory name for the filename
        output_dir_name = Path(output_dir_path_value).name
        download_filename = f"{output_dir_name}.json"

        try:
            config_json_data = json.dumps(download_config, indent=4)
        except Exception as e:
            st.error(f"Error preparing configuration for download: {e}")
            config_ready_for_download = False # Disable download if preparation fails
    
    st.download_button(
        label="Download Current Settings as JSON",
        data=config_json_data,
        file_name=download_filename, # Use dynamic filename
        mime="application/json",
        key="download_config_button",
        use_container_width=True,
        disabled=not config_ready_for_download,
        help="Download the current settings from the UI fields as a JSON configuration file."
    )

with col_ul:
    uploaded_config_file = st.file_uploader(
        "Load Configuration from JSON",
        type="json",
        key="upload_config_file",
        help="Upload a configuration JSON file."
    )
    # Add button to trigger population
    if st.button("Populate Form from Uploaded JSON", key="populate_button"):
        if st.session_state.upload_config_file is not None:
            try:
                # Seek to the beginning of the file before reading
                st.session_state.upload_config_file.seek(0)
                loaded_config = json.load(st.session_state.upload_config_file)
                logger.info(f"Storing uploaded configuration via button: {loaded_config}")

                # Store the loaded config and set flag for next run
                st.session_state._pending_loaded_config = loaded_config
                st.session_state._apply_loaded_config_on_next_run = True

                # Trigger rerun to apply the config
                st.rerun()

            except json.JSONDecodeError:
                st.error("Invalid JSON file uploaded. Please upload a valid configuration file.")
                st.session_state._apply_loaded_config_on_next_run = False
                st.session_state._pending_loaded_config = None
            except Exception as e:
                st.error(f"Error processing uploaded configuration file: {e}")
                logger.error(f"Error processing upload via button: {e}", exc_info=True)
                st.session_state._apply_loaded_config_on_next_run = False
                st.session_state._pending_loaded_config = None
        else:
            st.warning("Please upload a JSON configuration file first.")

# ============================================================================
# SECTION 12: FINALIZE CONFIGURATION
# ============================================================================
st.markdown("---")
st.header("✅ Finalize Configuration")

st.info("""
**Ready to run?** Review all settings above, then click the button below to save your configuration.
You'll be able to proceed to the Execution page once the configuration is finalized.
""")

finalize_submitted = st.button("✨ Finalize & Save All Configuration", type="primary", use_container_width=True)

# Handle finalization submission
if finalize_submitted:
    # Validate required fields using widget keys
    validation_error = False
    error_messages = []

    # Check PDB source
    pdb_file_state = st.session_state.get("pdb_file_uploader") # Get the UploadedFile object
    pdb_path_state = st.session_state.get("pdb_path_input", "")
    final_pdb_source = None # Will store the path to be used

    if pdb_file_state:
        final_pdb_source = f"uploaded:{pdb_file_state.name}" # Indicate uploaded source
    elif pdb_path_state and os.path.exists(pdb_path_state):
         final_pdb_source = pdb_path_state
    elif pdb_path_state: # Path provided but doesn't exist
        error_messages.append(f"PDB file path specified does not exist: {pdb_path_state}")
        validation_error = True
    else:
        error_messages.append("Please either upload a PDB file or specify a valid file path.")
        validation_error = True

    # Validate model-specific required fields
    current_model_final = st.session_state.model_selection
    if current_model_final == "diffsbdd" and not st.session_state.get("diffsbdd_resi_list", "").strip():
        error_messages.append("Please fill in the residue list for DiffSBDD.")
        validation_error = True

    # Validate output directory path
    output_dir_path_state = st.session_state.get("output_dir_path_input", "").strip()
    if not output_dir_path_state:
        error_messages.append("Please specify an Output Directory Path.")
        validation_error = True
    else:
        # Convert to Path object for validation
        try:
            output_path = Path(output_dir_path_state)
            
            # If it's a relative path, make it relative to the project root
            if not output_path.is_absolute():
                project_root = Path(__file__).resolve().parent.parent
                output_path = project_root / output_path
            
            # Resolve the path to handle any .. or . components
            output_path = output_path.resolve()
            
            # Validate that the parent directory exists or can be created
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
            except (OSError, PermissionError) as e:
                error_messages.append(f"Cannot create parent directories for output path: {e}")
                validation_error = True
                
        except (OSError, ValueError) as e:
            error_messages.append(f"Invalid output directory path: {e}")
            validation_error = True


    if validation_error:
        for msg in error_messages:
            st.error(msg)
    else:
        # Check if output directory already exists
        if output_path.exists():
            st.error(f"Output directory '{output_path}' already exists. Please choose a different path.")
        else:
            # Create the final configuration dictionary
            config = {}
            
            # Create a temporary directory *only* if we have uploaded files to save
            temp_dir_path = None
            if pdb_file_state:
                 temp_dir_path = Path(tempfile.mkdtemp())
                 logger.info(f"Created temp dir for uploads: {temp_dir_path}")

            # --- Populate config dictionary from session state ---
            config["model"] = current_model_final

            # Handle PDB file (used for both generation and docking)
            if pdb_file_state:
                pdb_save_path = temp_dir_path / pdb_file_state.name
                try:
                    with open(pdb_save_path, "wb") as f:
                        f.write(pdb_file_state.getbuffer())
                    config["pdbfile"] = str(pdb_save_path)
                    config["receptor"] = str(pdb_save_path)  # Use same file as receptor
                    logger.info(f"Saved uploaded PDB to temp file: {pdb_save_path}")
                except Exception as e:
                    st.error(f"Failed to save uploaded PDB file: {e}")
                    logger.error(f"Failed to save uploaded PDB file: {e}", exc_info=True)
            elif final_pdb_source: # Should be the validated path
                config["pdbfile"] = final_pdb_source
                config["receptor"] = final_pdb_source  # Use same file as receptor

            # Add model-specific parameters
            if current_model_final == "diffsbdd":
                config["checkpoint"] = "src/DiffSBDD/checkpoints/crossdocked_fullatom_cond.ckpt"
                config["resi_list"] = st.session_state.diffsbdd_resi_list
                config["sanitize"] = st.session_state.diffsbdd_sanitize
                config["box_size"] = [
                    st.session_state.diffsbdd_size_x,
                    st.session_state.diffsbdd_size_y,
                    st.session_state.diffsbdd_size_z
                ]
            elif current_model_final == "pocket2mol":
                config["bbox_size"] = st.session_state.pocket2mol_bbox_size
                # Docking box for Pocket2Mol
                config["box_size"] = [
                    st.session_state.pocket2mol_dock_size_x,
                    st.session_state.pocket2mol_dock_size_y,
                    st.session_state.pocket2mol_dock_size_z
                ]
            else:  # cgflow
                # Default CGFlow settings; not exposed in UI per requirements
                config["checkpoint"] = st.session_state.cgflow_checkpoint_path
                config["cgflow_config"] = st.session_state.cgflow_config_path
                # Docking box for CGFlow (reuses docking keys)
                config["box_size"] = [
                    st.session_state.pocket2mol_dock_size_x,
                    st.session_state.pocket2mol_dock_size_y,
                    st.session_state.pocket2mol_dock_size_z
                ]

            # Add common parameters
            config["n_samples"] = st.session_state.n_samples_input
            config["center"] = [st.session_state.center_x, st.session_state.center_y, st.session_state.center_z]
            config["exhaustiveness_level"] = st.session_state.exhaustiveness_level_input
            config["top_n"] = st.session_state.top_n_input
            config["num_rounds"] = st.session_state.num_rounds_input
            config["score_threshold"] = st.session_state.score_threshold_input
            
            # Add Boltz-2 configuration
            config["boltz_pocket_residues"] = st.session_state.boltz_pocket_residues_input
            config["msa_path"] = st.session_state.msa_path_input
            
            config["out_dir"] = str(output_path) # Use the validated, absolute path


            # --- Save final configuration in session state ---
            st.session_state.pipeline_config = config
            st.success(f"Configuration saved successfully! Output will be in '{output_path}'. Proceed to the Execution page.")
            
            # Show the resolved path if it's different from what the user entered
            if str(output_path) != output_dir_path_state:
                st.info(f"Resolved path: `{output_path}`")
            
            logger.info(f"Finalized pipeline config: {config}")

# ============================================================================
# SECTION 13: FINALIZED CONFIGURATION DISPLAY
# ============================================================================
if st.session_state.get("pipeline_config") is not None:
    st.markdown("---") # Separator
    st.header("Current Finalized Configuration")

    # Add stop button if pipeline is running (check status from potentially different page)
    # It might be better to handle the stop button only on the execution page.
    # if st.session_state.get("pipeline_status", {}).get("running", False):
    #     if st.button("Stop Pipeline", type="secondary", key="stop_button_config_page"): # Unique key
    #         st.session_state.stop_pipeline = True
    #         st.warning("Stop request sent. Monitor the Execution page.")

    # Display config using st.expander
    with st.expander("View Finalized Configuration JSON", expanded=False):
        st.json(st.session_state.pipeline_config) 