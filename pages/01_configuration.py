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
if "max_variants_input" not in st.session_state:
    st.session_state.max_variants_input = 5
if "output_dir_path_input" not in st.session_state:
    st.session_state.output_dir_path_input = "outputs/pipeline_output"
if "score_threshold_input" not in st.session_state:
    st.session_state.score_threshold_input = 0.7

# Boltz-2 Specific
if "boltz_pocket_residues_input" not in st.session_state:
    st.session_state.boltz_pocket_residues_input = ""

# Box Generation Input
if "generate_box_residues_input" not in st.session_state:
    st.session_state.generate_box_residues_input = ""

# MedChem Filter Thresholds
if "medchem_rule_threshold" not in st.session_state:
    st.session_state.medchem_rule_threshold = 13
if "medchem_structural_threshold" not in st.session_state:
    st.session_state.medchem_structural_threshold = 27

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
            st.session_state.top_n_input = int(pending_config.get("top_n", st.session_state.top_n_input))
            st.session_state.max_variants_input = int(pending_config.get("max_variants", st.session_state.max_variants_input))
            st.session_state.num_rounds_input = int(pending_config.get("num_rounds", st.session_state.num_rounds_input))
            st.session_state.score_threshold_input = float(pending_config.get("score_threshold", st.session_state.score_threshold_input))
            
            # Load Boltz-2 configuration
            st.session_state.boltz_pocket_residues_input = pending_config.get("boltz_pocket_residues", st.session_state.boltz_pocket_residues_input)

            # Load MedChem filter thresholds
            st.session_state.medchem_rule_threshold = int(pending_config.get("medchem_rule_threshold", st.session_state.medchem_rule_threshold))
            st.session_state.medchem_structural_threshold = int(pending_config.get("medchem_structural_threshold", st.session_state.medchem_structural_threshold))

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


def update_model_choice():
    """Function to update model choice based on form submission"""
    st.session_state.model_update_requested = True

st.title("⚙️ Pipeline Configuration")
st.markdown("""
    Configure the parameters for your drug discovery pipeline run.
    Required fields are marked with an asterisk (*).
""")

# Get current model from session state (using the selectbox key)
current_model = st.session_state.model_selection

# Model selection form
with st.form(key="model_selection_form", border=True):
    st.markdown("""<div class="form-header"><h3>Model Selection</h3></div>""", unsafe_allow_html=True)

    # Model selection - uses key 'model_selection'
    st.selectbox(
        "AI Model for Molecule Generation *",
        options=["diffsbdd", "pocket2mol"],
        format_func=lambda x: "DiffSBDD" if x == "diffsbdd" else "Pocket2Mol",
        # index is automatically handled by key binding if key exists
        key="model_selection",
        help="Select the AI model for generating molecules"
    )

    # Submit button for model selection
    model_submitted = st.form_submit_button("Update Model Selection", on_click=update_model_choice)

# Check if model update was requested and trigger rerun
if st.session_state.model_update_requested:
    st.session_state.model_update_requested = False
    st.rerun()

# Create tabs for better organization
tab1, tab2, tab3 = st.tabs(["Basic Configuration", "Box Settings", "Advanced Settings"])

# --- Forms no longer strictly needed for saving state, but kept for visual grouping ---
with tab1:
    st.markdown("""<div class="form-header"><h3>File Uploads and Parameters</h3></div>""", unsafe_allow_html=True)

    # Single PDB file upload section
    st.subheader("Target Protein PDB File")    
    
    # Add PDB indexing reminder
    st.warning("""
    **⚠️ Important PDB Indexing Requirement:**
    
    The input protein PDB file **must be 1-indexed** (residue numbering starts from 1). 
    If your PDB file uses non-standard indexing (e.g., starting from 0 or with gaps), 
    please use [pdb-tools](https://www.bonvinlab.org/pdb-tools/) to renumber it before uploading:
    
    ```bash
    pdb_reres -1 input.pdb > output_reindexed.pdb
    ```
    
    The pipeline does not currently support automatic renumbering of non-1-indexed PDB files.
    """)
    
    col1, col2 = st.columns(2)

    with col1:
        # PDB File upload
        pdb_file = st.file_uploader(
            "Upload PDB File",
            type=["pdb"],
            help="Upload the target protein PDB file",
            key="pdb_file_uploader"
        )

    with col2:
        # PDB Path Input - uses key 'pdb_path_input'
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
        st.error("⚠️ **Required**: Please upload a PDB file or specify a PDB file path. This file will be used for both molecule generation and docking.")

    st.markdown("""<div class="form-header"><h3>Model Parameters</h3></div>""", unsafe_allow_html=True)

    # Show model-specific parameters based on current selection
    if current_model == "diffsbdd":
        st.subheader("DiffSBDD Parameters")
        # Residue List Input - uses key 'diffsbdd_resi_list'
        st.text_input(
            "Residue List *",
            help="Space-separated residue identifiers (format: CHAIN:RESIDUE)",
            key="diffsbdd_resi_list"
        )

        # Sanitize Checkbox - uses key 'diffsbdd_sanitize'
        st.checkbox(
            "Sanitize Generated Molecules",
            help="Apply sanitization to generated molecules",
            key="diffsbdd_sanitize"
        )
    else:
        # Display a message for Pocket2Mol
        st.info("Pocket2Mol uses 3D pocket information instead of residue lists. The bounding box settings can be configured in the 'Box Settings' tab.")

    # Common parameters - simplified since Unidock handles program choice and scoring
    col3, col4 = st.columns(2)

    with col3:
        # Number of Samples Input - uses key 'n_samples_input'
        st.number_input(
            "Number of Samples *",
            min_value=1,
            max_value=500, # Adjust max if needed
            step=1,
            help="Number of compounds to generate",
            key="n_samples_input"
        )

    with col4:
        pass

with tab2:
    # --- Box Generation Expander (Moved outside the form) ---
    with st.expander("Generate Box from Residues (Experimental)"):
        st.markdown("Automatically calculate box center and dimensions based on selected residues.")
        st.caption("Grid generation logic adapted from code by Pritam Kumar Panda.")

        # Use the residue list from DiffSBDD input if available
        # Read directly from the widget state key
        default_residues_for_boxgen = ""
        if current_model == "diffsbdd":
            space_separated_residues = st.session_state.get("diffsbdd_resi_list", "")
            residue_parts = [res for res in space_separated_residues.split() if res.strip()]
            if residue_parts:
                # Use newline separated for the text_area display
                default_residues_for_boxgen = "\\n".join(residue_parts)

        # Residues Text Area - uses key 'generate_box_residues_input'
        st.text_area(
            "Residues for Box Generation",
            value=default_residues_for_boxgen, # Set initial value based on diffsbdd input
            help="Enter target residues in format 'Chain:ResidueNumber', one per line or space-separated (e.g., A:156). These residues will define the box boundaries.",
            key="generate_box_residues_input"
        )

        if st.button("Calculate and Populate Box Dimensions", key="generate_box_button"):
            pdb_content_for_gen = None
            # Prioritize uploaded file, then path
            pdb_file_state = st.session_state.get("pdb_file_uploader") # Use state key
            pdb_path_state = st.session_state.get("pdb_path_input")    # Use state key

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
                st.error("Please upload or specify a valid PDB file path in the 'Basic Configuration' tab first.")

            # Read residue list directly from widget state
            residues_for_boxgen_state = st.session_state.get("generate_box_residues_input", "")
            if pdb_content_for_gen and residues_for_boxgen_state:
                with st.spinner("Calculating box dimensions..."):
                    box_params = calculate_box_from_residues(pdb_content_for_gen, residues_for_boxgen_state)

                if box_params:
                    # Update session state keys DIRECTLY
                    st.session_state.center_x = float(box_params['center'][0])
                    st.session_state.center_y = float(box_params['center'][1])
                    st.session_state.center_z = float(box_params['center'][2])

                    calculated_size = box_params['size'] # Store size for reuse
                    if current_model == "diffsbdd":
                        st.session_state.diffsbdd_size_x = float(calculated_size[0])
                        st.session_state.diffsbdd_size_y = float(calculated_size[1])
                        st.session_state.diffsbdd_size_z = float(calculated_size[2])
                    else: # pocket2mol
                        # Update Pocket2Mol docking box sizes
                        st.session_state.pocket2mol_dock_size_x = float(calculated_size[0])
                        st.session_state.pocket2mol_dock_size_y = float(calculated_size[1])
                        st.session_state.pocket2mol_dock_size_z = float(calculated_size[2])

                        # Update the cubic generation box size (use max dimension)
                        st.session_state.pocket2mol_bbox_size = float(round(max(calculated_size)))

                    st.success("Box dimensions calculated and populated below.")
                    # Rerun is important here to make the number_input widgets update their displayed values
                    st.rerun()
                else:
                    st.error("Failed to calculate box dimensions.")
            elif not residues_for_boxgen_state:
                    st.warning("Please enter residues for box generation.")
    # --- End Box Generation Expander ---

    # --- Box Configuration Section (No form needed for state saving) ---
    st.markdown("""<div class="form-header"><h3>Box Configuration</h3></div>""", unsafe_allow_html=True)

    # Common center coordinates
    st.subheader("Center Coordinates (used for generation and/or docking)")
    col5, col6, col7 = st.columns(3)

    with col5:
        # Center X Input - uses key 'center_x'
        st.number_input("Center X", format="%.3f", key="center_x")
    with col6:
        # Center Y Input - uses key 'center_y'
        st.number_input("Center Y", format="%.3f", key="center_y")
    with col7:
        # Center Z Input - uses key 'center_z'
        st.number_input("Center Z", format="%.3f", key="center_z")

    # Model-specific box configurations
    if current_model == "diffsbdd":
        st.subheader("Docking Box Dimensions")
        st.info("DiffSBDD uses the residue list for molecule generation. These dimensions define the docking box.")

        col8, col9, col10 = st.columns(3)
        with col8:
            # Docking Size X Input - uses key 'diffsbdd_size_x'
            st.number_input(
                "Docking Size X",
                min_value=1.0,
                format="%.1f",
                key="diffsbdd_size_x"
            )
        with col9:
            # Docking Size Y Input - uses key 'diffsbdd_size_y'
            st.number_input(
                "Docking Size Y",
                min_value=1.0,
                 format="%.1f",
                key="diffsbdd_size_y"
            )
        with col10:
            # Docking Size Z Input - uses key 'diffsbdd_size_z'
            st.number_input(
                "Docking Size Z",
                min_value=1.0,
                 format="%.1f",
                key="diffsbdd_size_z"
            )

    else:  # pocket2mol
        # Generation box (bounding box) for Pocket2Mol
        st.subheader("Molecule Generation Box (Pocket2Mol)")
        st.info("This defines the cubic space where Pocket2Mol will generate molecules.")
        # Generation Box Size Input - uses key 'pocket2mol_bbox_size'
        st.number_input(
            "Generation Box Size",
            min_value=1.0,
            format="%.1f",
            help="Size of the cubic bounding box for Pocket2Mol generation (single value used for all dimensions)",
            key="pocket2mol_bbox_size"
        )

        # Docking box for Pocket2Mol
        st.subheader("Docking Box Dimensions (Pocket2Mol)")
        st.info("This defines the space where molecule docking will occur (can be different from generation box).")

        col11, col12, col13 = st.columns(3) # Use different column variables
        with col11:
            # Docking Size X Input - uses key 'pocket2mol_dock_size_x'
            st.number_input(
                "Docking Size X",
                min_value=1.0,
                format="%.1f",
                key="pocket2mol_dock_size_x"
            )
        with col12:
            # Docking Size Y Input - uses key 'pocket2mol_dock_size_y'
            st.number_input(
                "Docking Size Y",
                min_value=1.0,
                format="%.1f",
                key="pocket2mol_dock_size_y"
            )
        with col13:
            # Docking Size Z Input - uses key 'pocket2mol_dock_size_z'
            st.number_input(
                "Docking Size Z",
                min_value=1.0,
                format="%.1f",
                key="pocket2mol_dock_size_z"
            )

    # No need for "Save Box Config" button

with tab3:
    st.markdown("""<div class="form-header"><h3>Advanced Parameters</h3></div>""", unsafe_allow_html=True)

    col14, col15 = st.columns(2) # Use different column variables

    with col14:
        # Exhaustiveness Input - uses key 'exhaustiveness_level_input'
        st.selectbox(
            "Exhaustiveness Level",
            options=["fast", "balance", "detail"],
            format_func=lambda x: {
                "fast": "Fast (128) - Quick docking for screening",
                "balance": "Balance (384) - Good balance of speed and accuracy", 
                "detail": "Detail (512) - Thorough search for final results"
            }[x],
            help="Select the exhaustiveness level for docking. Higher levels provide more thorough search but take longer.",
            key="exhaustiveness_level_input"
        )

    with col15:
        # Number of Rounds Input - uses key 'num_rounds_input'
        st.number_input(
            "Number of Rounds",
            min_value=1,
            max_value=1000, # Sensible max?
            step=1,
            help="Number of pipeline rounds to run",
            key="num_rounds_input"
        )

    st.markdown("""<div class="form-header"><h3>Retrosynthesis Filtering Configuration</h3></div>""", unsafe_allow_html=True)

    col_score, col_empty = st.columns(2)
    with col_score:
        # Score Threshold Input - uses key 'score_threshold_input'
        st.number_input(
            "Retrosynthesis Score Threshold",
            min_value=0.0,
            max_value=1.0,
            step=0.1,
            format="%.1f",
            help="Minimum retrosynthesis score threshold for filtering variants. Only variants with scores >= this threshold will proceed to MedChem filtering. Higher values are more restrictive.",
            key="score_threshold_input"
        )

    st.markdown("""<div class="form-header"><h3>Boltz-2 Filtering Configuration</h3></div>""", unsafe_allow_html=True)

    st.info("Boltz-2 filtering predicts protein-ligand structures and evaluates binding affinity. The filter uses spatial evaluation (any ligand atom within the docking box) and provides affinity predictions with confidence scores.")
    
    # Boltz-2 pocket constraints configuration
    st.text_input(
        "Pocket Constraint Residues (comma-separated)",
        placeholder="e.g., 156,158,202,204",
        help="Enter residue numbers (1-indexed) to define pocket constraints for Boltz-2. These residues will be used to guide the protein-ligand binding prediction. Leave empty to use no constraints.",
        key="boltz_pocket_residues_input"
    )
    
    st.caption("""
    **Pocket Constraints:** Specify key residues that define the binding pocket for Boltz-2 structure prediction. 
    These should be residue numbers (1-indexed) that are important for ligand binding. 
    The constraints help guide the structural prediction to focus on the correct binding site.
    """)
    
    st.info("💡 **Tip:** You can use the same residues from your DiffSBDD residue list or docking box generation residues as pocket constraints.")

    st.markdown("""<div class="form-header"><h3>MedChem Filtering Configuration</h3></div>""", unsafe_allow_html=True)

    st.info("MedChem filtering evaluates compounds against medicinal chemistry rules and structural alerts. Compounds must pass the minimum number of specified filters to proceed to docking.")
    
    col_medchem1, col_medchem2 = st.columns(2)
    
    with col_medchem1:
        st.number_input(
            "Minimum Rules Passed",
            min_value=0,
            max_value=20,
            step=1,
            help="Minimum number of medicinal chemistry rules a compound must pass (e.g., Lipinski's Rule of 5, Ghose, Veber, etc.). Default: 13 out of ~15 total rules.",
            key="medchem_rule_threshold"
        )
    
    with col_medchem2:
        st.number_input(
            "Minimum Structural Filters Passed",
            min_value=0,
            max_value=40,
            step=1,
            help="Minimum number of structural/functional filters a compound must pass (e.g., PAINS, Glaxo alerts, NIBR filter, etc.). Default: 27 out of ~30 total filters.",
            key="medchem_structural_threshold"
        )
    
    st.caption("""
    **Filter Categories:**
    - **Rules:** Druglikeness rules (Lipinski, Ghose, Veber, REOS, etc.)
    - **Structural Filters:** Alert filters (PAINS, Glaxo, BMS, etc.) and functional filters (NIBR, Bredt, etc.)
    
    Higher thresholds are more restrictive and will filter out more compounds. Lower thresholds are more permissive.
    """)

    st.markdown("""<div class="form-header"><h3>Output Configuration</h3></div>""", unsafe_allow_html=True)

    col16, col17 = st.columns(2) # Use different column variables

    with col16:
        # Output Directory Path Input - uses key 'output_dir_path_input'
        st.text_input(
            "Output Directory Path *",
            help="Path to the output directory where results will be stored. Can be absolute (e.g., '/home/user/results') or relative to project root (e.g., 'outputs/my_experiment')",
            key="output_dir_path_input"
        )
        
        # Add helpful information about path formats
        st.caption("""
        **Path Examples:**
        - Relative: `outputs/my_experiment` (relative to project root)
        - Absolute: `/home/user/drug_discovery_results`
        - With subdirectories: `outputs/experiments/2024/january`
        """)

        # Top N Input - uses key 'top_n_input'
        st.number_input(
            "Top N Compounds",
            min_value=1,
            max_value=100, # Adjust if needed
            step=1,
            help="Number of top compounds to select/process per round",
            key="top_n_input"
        )

    with col17:
        # Max Variants Input - uses key 'max_variants_input'
        st.number_input(
            "Maximum Variants per Compound",
            min_value=1,
            max_value=50, # Adjust if needed
            step=1,
            help="Maximum number of variants to generate/process per compound (if applicable)",
            key="max_variants_input"
        )

    # No need for "Save Advanced Config" button

# --- Manage Configuration Section (Download/Upload) ---
st.header("Manage Configuration")

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
        else: # pocket2mol
            download_config["bbox_size"] = st.session_state.pocket2mol_bbox_size
            download_config["box_size"] = [ # Docking box for pocket2mol
                st.session_state.pocket2mol_dock_size_x,
                st.session_state.pocket2mol_dock_size_y,
                st.session_state.pocket2mol_dock_size_z
            ]

        # Common parameters
        download_config["n_samples"] = st.session_state.n_samples_input
        download_config["center"] = [st.session_state.center_x, st.session_state.center_y, st.session_state.center_z]
        download_config["exhaustiveness_level"] = st.session_state.exhaustiveness_level_input
        download_config["top_n"] = st.session_state.top_n_input
        download_config["max_variants"] = st.session_state.max_variants_input
        download_config["num_rounds"] = st.session_state.num_rounds_input
        download_config["score_threshold"] = st.session_state.score_threshold_input
        
        # Add Boltz-2 configuration
        download_config["boltz_pocket_residues"] = st.session_state.boltz_pocket_residues_input
        
        # Add MedChem filter thresholds
        download_config["medchem_rule_threshold"] = st.session_state.medchem_rule_threshold
        download_config["medchem_structural_threshold"] = st.session_state.medchem_structural_threshold
        
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

# --- Finalize Configuration Section ---
st.header("Finalize Configuration")
finalize_container = st.container()
with finalize_container:
    finalize_col1, finalize_col2 = st.columns([3, 1]) # Adjust column ratio if needed
    with finalize_col2:
        finalize_submitted = st.button("Finalize & Save All Configuration", type="primary", use_container_width=True)

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
            else:  # pocket2mol
                config["bbox_size"] = st.session_state.pocket2mol_bbox_size
                # Docking box for Pocket2Mol
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
            config["max_variants"] = st.session_state.max_variants_input
            config["num_rounds"] = st.session_state.num_rounds_input
            config["score_threshold"] = st.session_state.score_threshold_input
            
            # Add Boltz-2 configuration
            config["boltz_pocket_residues"] = st.session_state.boltz_pocket_residues_input
            
            # Add MedChem filter thresholds
            config["medchem_rule_threshold"] = st.session_state.medchem_rule_threshold
            config["medchem_structural_threshold"] = st.session_state.medchem_structural_threshold
            
            config["out_dir"] = str(output_path) # Use the validated, absolute path


            # --- Save final configuration in session state ---
            st.session_state.pipeline_config = config
            st.success(f"Configuration saved successfully! Output will be in '{output_path}'. Proceed to the Execution page.")
            
            # Show the resolved path if it's different from what the user entered
            if str(output_path) != output_dir_path_state:
                st.info(f"Resolved path: `{output_path}`")
            
            logger.info(f"Finalized pipeline config: {config}")
            # We might want to store the temp_dir_path if files were uploaded,
            # so they can be cleaned up later, but managing temp dirs across sessions/pages is tricky.
            # For now, rely on OS tmp cleanup? Or pass path via session state?
            # If passing, store: st.session_state.temp_upload_dir = str(temp_dir_path)


# --- Visualization Section ---
# Add visualization section if PDB is available (uploaded or path)
# Define state variables again for clarity before the check
pdb_file_state = st.session_state.get("pdb_file_uploader")
pdb_path_state = st.session_state.get("pdb_path_input")
current_vis_model = st.session_state.model_selection # Use the current model selection

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
    st.markdown("---") # Separator
    st.write("### Protein Structure Visualization")

    if current_vis_model == "diffsbdd":
        st.write("Selected residues (from input field) are highlighted in red. Docking box (from settings below) shown in blue.")
    else:  # pocket2mol
        st.write("Pocket2Mol generation box (from settings below) shown in green. Docking box (also from settings below) shown in blue.")

    # Get current box parameters directly from session state keys
    center_vis = [st.session_state.center_x, st.session_state.center_y, st.session_state.center_z]
    box_size_vis = None
    bbox_size_vis = None

    if current_vis_model == "diffsbdd":
        # Parse residue list for DiffSBDD directly from its state key
        selected_residues_vis = parse_residue_list(st.session_state.diffsbdd_resi_list)
        box_size_vis = [
            st.session_state.diffsbdd_size_x,
            st.session_state.diffsbdd_size_y,
            st.session_state.diffsbdd_size_z
        ]
    else:  # pocket2mol
        selected_residues_vis = None
        # Pocket2Mol uses different keys for docking box vs generation box
        box_size_vis = [ # Docking box
            st.session_state.pocket2mol_dock_size_x,
            st.session_state.pocket2mol_dock_size_y,
            st.session_state.pocket2mol_dock_size_z
        ]
        bbox_size_vis = st.session_state.pocket2mol_bbox_size # Generation box size

    try:
        # Create visualization with appropriate box
        view, html = visualize_protein_residues(
            pdb_content_for_vis,
            selected_residues=selected_residues_vis,
            center=center_vis,
            box_size=box_size_vis,
            bbox_size=bbox_size_vis
        )

        # Display the visualization using HTML component
        components.html(html, height=600, width=800)

        # Add some helpful instructions
        st.caption("""
        **Controls:**
        - Rotate: Click and drag
        - Zoom: Scroll wheel
        - Pan: Right click and drag
        - Reset view: Double click

        **Visualization Guide:**
        - Protein backbone: Light gray cartoon
        - Selected residues (DiffSBDD only): Red cartoon and sticks
        - Docking box: Blue transparent box with wireframe
        - Pocket2Mol generation box: Green cubic box with wireframe (Pocket2Mol only)
        """)
    except Exception as e:
        st.error(f"Error generating protein visualization: {e}")
        logger.error(f"Error during py3Dmol visualization: {e}", exc_info=True)


# --- Display Current Finalized Configuration ---
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