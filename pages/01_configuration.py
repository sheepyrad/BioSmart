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
if "receptor_path_input" not in st.session_state:
    st.session_state.receptor_path_input = ""

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
if "program_choice_input" not in st.session_state:
    st.session_state.program_choice_input = "qvina"
if "scoring_function_input" not in st.session_state:
    st.session_state.scoring_function_input = "nnscore2"
if "exhaustiveness_input" not in st.session_state:
    st.session_state.exhaustiveness_input = 32
if "is_selfies_input" not in st.session_state:
    st.session_state.is_selfies_input = False
if "is_peptide_input" not in st.session_state:
    st.session_state.is_peptide_input = False
if "num_rounds_input" not in st.session_state:
    st.session_state.num_rounds_input = 1
if "top_n_input" not in st.session_state:
    st.session_state.top_n_input = 5
if "max_variants_input" not in st.session_state:
    st.session_state.max_variants_input = 5
if "output_dir_name_input" not in st.session_state:
    st.session_state.output_dir_name_input = "pipeline_output"
if "boltz_evaluation_method_input" not in st.session_state:
    st.session_state.boltz_evaluation_method_input = "combined"

# Box Generation Input
if "generate_box_residues_input" not in st.session_state:
    st.session_state.generate_box_residues_input = ""

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
            st.session_state.receptor_path_input = pending_config.get("receptor", st.session_state.receptor_path_input)

            if "center" in pending_config and len(pending_config["center"]) == 3:
                st.session_state.center_x = float(pending_config["center"][0])
                st.session_state.center_y = float(pending_config["center"][1])
                st.session_state.center_z = float(pending_config["center"][2])

            st.session_state.n_samples_input = int(pending_config.get("n_samples", st.session_state.n_samples_input))
            st.session_state.program_choice_input = pending_config.get("program_choice", st.session_state.program_choice_input)
            st.session_state.scoring_function_input = pending_config.get("scoring_function", st.session_state.scoring_function_input)
            st.session_state.exhaustiveness_input = int(pending_config.get("exhaustiveness", st.session_state.exhaustiveness_input))
            st.session_state.is_selfies_input = bool(pending_config.get("is_selfies", st.session_state.is_selfies_input))
            st.session_state.is_peptide_input = bool(pending_config.get("is_peptide", st.session_state.is_peptide_input))
            st.session_state.top_n_input = int(pending_config.get("top_n", st.session_state.top_n_input))
            st.session_state.max_variants_input = int(pending_config.get("max_variants", st.session_state.max_variants_input))
            st.session_state.num_rounds_input = int(pending_config.get("num_rounds", st.session_state.num_rounds_input))
            st.session_state.boltz_evaluation_method_input = pending_config.get("boltz_evaluation_method", st.session_state.boltz_evaluation_method_input)

            if "out_dir" in pending_config:
                st.session_state.output_dir_name_input = Path(pending_config["out_dir"]).name

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

    col1, col2 = st.columns(2)

    with col1:
        # PDB File upload
        st.subheader("PDB File")
        pdb_file = st.file_uploader( # No key needed for file uploader state? Streamlit handles it.
            "Upload PDB File",
            type=["pdb"],
            help="Upload the target protein PDB file",
            key="pdb_file_uploader" # Keep key if used elsewhere, e.g. reading content
        )

        # PDB Path Input - uses key 'pdb_path_input'
        st.text_input(
            "OR Enter PDB File Path *",
            placeholder="Path to PDB file on server",
            help="Specify the path to the PDB file on the server",
            key="pdb_path_input"
        )

    with col2:
        # Receptor File upload
        st.subheader("Receptor File")
        receptor_file = st.file_uploader( # No key needed for file uploader state?
            "Upload Receptor File",
            type=["pdbqt"],
            help="Upload the receptor file for docking (optional)",
             key="receptor_file_uploader" # Keep key if used elsewhere
        )

        # Receptor Path Input - uses key 'receptor_path_input'
        st.text_input(
            "OR Enter Receptor File Path",
            placeholder="Path to PDBQT file on server",
            help="Specify the path to the PDBQT receptor file on the server",
            key="receptor_path_input"
        )

    # Use widget keys directly to check state
    if not st.session_state.get("receptor_file_uploader") and not st.session_state.receptor_path_input:
        st.warning("⚠️ No receptor file uploaded or specified. Docking steps may be skipped or fail. Upload or specify a PDBQT receptor file if you want to perform docking.")

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

    # Common parameters
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
        # Docking Program Selectbox - uses key 'program_choice_input'
        st.selectbox(
            "Docking Program",
            options=["qvina"],
            # index=0, # No longer needed with key
            help="Select the docking program to use",
            key="program_choice_input"
        )

        # Scoring Function Selectbox - uses key 'scoring_function_input'
        st.selectbox(
            "Scoring Function",
            options=["nnscore2"],
            # index=0, # No longer needed with key
            help="Select the scoring function for docking",
            key="scoring_function_input"
        )

    # No need for "Save Basic Config" button if not using forms for state saving

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
        # Exhaustiveness Input - uses key 'exhaustiveness_input'
        st.number_input(
            "Exhaustiveness",
            min_value=1,
            max_value=100, # Adjust if needed
            step=1,
            help="Docking exhaustiveness parameter",
            key="exhaustiveness_input"
        )

        # SELFIES Checkbox - uses key 'is_selfies_input'
        st.checkbox(
            "Use SELFIES Representation",
            help="Use SELFIES molecular representation (if applicable model supports)",
            key="is_selfies_input"
        )

    with col15:
        # Peptide Checkbox - uses key 'is_peptide_input'
        st.checkbox(
            "Ligand is Peptide",
            help="Check if the ligand is a peptide (may affect downstream processing)",
            key="is_peptide_input"
        )

        # Number of Rounds Input - uses key 'num_rounds_input'
        st.number_input(
            "Number of Rounds",
            min_value=1,
            max_value=1000, # Sensible max?
            step=1,
            help="Number of pipeline rounds to run",
            key="num_rounds_input"
        )

    st.markdown("""<div class="form-header"><h3>Boltz-1x Filtering Configuration</h3></div>""", unsafe_allow_html=True)
    
    # Boltz-1x Evaluation Method Selection
    st.selectbox(
        "Boltz-1x Evaluation Method",
        options=["any_atom", "geometric_center", "majority_atoms", "bounding_box_overlap", "combined"],
        format_func=lambda x: {
            "any_atom": "Any Atom - Passes if ANY ligand atom is inside the docking box",
            "geometric_center": "Geometric Center - Passes if ligand center is inside the box", 
            "majority_atoms": "Majority Atoms - Passes if >50% of ligand atoms are inside",
            "bounding_box_overlap": "Bounding Box Overlap - Passes if >10% volume overlap",
            "combined": "Combined (Recommended) - Uses multiple criteria for robust evaluation"
        }[x],
        help="Method for evaluating whether predicted ligand positions are acceptable. 'Combined' is recommended as it balances sensitivity and specificity.",
        key="boltz_evaluation_method_input"
    )
    
    # Add detailed information about evaluation methods
    with st.expander("ℹ️ Detailed Evaluation Method Information"):
        st.markdown("""
        **Choose the evaluation method that best fits your research needs:**
        
        **🎯 Any Atom** - Most permissive approach
        - Passes if ANY ligand atom is inside the docking box
        - Good for initial screening and high sensitivity
        - May accept ligands that are mostly outside the target region
        
        **📍 Geometric Center** - Balanced approach  
        - Passes if the geometric center (centroid) of the ligand is inside the box
        - Good balance between sensitivity and specificity
        - Ensures the ligand is generally positioned in the target region
        
        **📊 Majority Atoms** - High specificity
        - Passes if more than 50% of ligand atoms are inside the docking box
        - Ensures significant binding site occupancy
        - May be too strict for large ligands or edge binding cases
        
        **📦 Bounding Box Overlap** - Shape-aware evaluation
        - Passes if more than 10% of ligand bounding box overlaps with docking box
        - Accounts for ligand shape and size
        - Good for irregularly shaped molecules
        
        **🎯 Combined (Recommended)** - Multi-criteria approach
        - Passes if: center inside OR >30% bounding box overlap OR >60% atoms inside
        - Robust across different ligand types and binding scenarios
        - Balances sensitivity and specificity effectively
        """)
        
        st.info("💡 **Recommendation**: Use 'Combined' for most applications as it provides robust filtering across various ligand shapes and binding modes while maintaining good specificity for the target region.")

    st.markdown("""<div class="form-header"><h3>Output Configuration</h3></div>""", unsafe_allow_html=True)

    col16, col17 = st.columns(2) # Use different column variables

    with col16:
        # Output Directory Name Input - uses key 'output_dir_name_input'
        st.text_input(
            "Output Directory Name *",
            help="Name of the output directory where results will be stored (relative to 'outputs/' folder)",
            key="output_dir_name_input"
        )

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
    config_ready_for_download = bool(st.session_state.get("output_dir_name_input"))
    config_json_data = ""
    download_filename = "pipeline_config.json" # Default filename
    if config_ready_for_download:
        # Build the config dict *for download* based on current widget states
        download_config = {}
        download_config["model"] = st.session_state.model_selection
        
        # Files (store paths from state)
        download_config["pdbfile"] = st.session_state.pdb_path_input
        download_config["receptor"] = st.session_state.receptor_path_input # May be empty

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
        download_config["program_choice"] = st.session_state.program_choice_input
        download_config["scoring_function"] = st.session_state.scoring_function_input
        download_config["center"] = [st.session_state.center_x, st.session_state.center_y, st.session_state.center_z]
        download_config["exhaustiveness"] = st.session_state.exhaustiveness_input
        download_config["is_selfies"] = st.session_state.is_selfies_input
        download_config["is_peptide"] = st.session_state.is_peptide_input
        download_config["top_n"] = st.session_state.top_n_input
        download_config["max_variants"] = st.session_state.max_variants_input
        download_config["num_rounds"] = st.session_state.num_rounds_input
        download_config["boltz_evaluation_method"] = st.session_state.boltz_evaluation_method_input
        
        # Use output dir name for filename and construct full path for config value
        output_dir_name_value = st.session_state.get("output_dir_name_input", "pipeline_output")
        download_config["out_dir"] = f"outputs/{output_dir_name_value}"
        download_filename = f"{output_dir_name_value}.json"

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

    # Validate output directory name
    output_dir_name_state = st.session_state.get("output_dir_name_input", "").strip()
    if not output_dir_name_state:
        error_messages.append("Please specify an Output Directory Name.")
        validation_error = True
    elif not re.match(r"^[a-zA-Z0-9_.-]+$", output_dir_name_state):
         error_messages.append("Output Directory Name contains invalid characters. Use only letters, numbers, underscore, dot, or hyphen.")
         validation_error = True


    if validation_error:
        for msg in error_messages:
            st.error(msg)
    else:
        # Check if output directory already exists
        project_root = Path(__file__).resolve().parent.parent
        output_path = project_root / "outputs" / output_dir_name_state
        if output_path.exists():
            st.error(f"Output directory 'outputs/{output_dir_name_state}' already exists. Please choose a different name.")
        else:
            # Create the final configuration dictionary
            config = {}
            
            # Create a temporary directory *only* if we have uploaded files to save
            temp_dir_path = None
            if pdb_file_state or st.session_state.get("receptor_file_uploader"):
                 temp_dir_path = Path(tempfile.mkdtemp())
                 logger.info(f"Created temp dir for uploads: {temp_dir_path}")


            # --- Populate config dictionary from session state ---
            config["model"] = current_model_final

            # Handle PDB file
            if pdb_file_state:
                pdb_save_path = temp_dir_path / pdb_file_state.name
                try:
                    with open(pdb_save_path, "wb") as f:
                        f.write(pdb_file_state.getbuffer())
                    config["pdbfile"] = str(pdb_save_path)
                    logger.info(f"Saved uploaded PDB to temp file: {pdb_save_path}")
                except Exception as e:
                    st.error(f"Failed to save uploaded PDB file: {e}")
                    logger.error(f"Failed to save uploaded PDB file: {e}", exc_info=True)
                    # Potentially stop config saving here?
            elif final_pdb_source: # Should be the validated path
                config["pdbfile"] = final_pdb_source
            
            # Handle Receptor file
            receptor_file_state = st.session_state.get("receptor_file_uploader")
            receptor_path_state = st.session_state.get("receptor_path_input", "")
            if receptor_file_state:
                 receptor_save_path = temp_dir_path / receptor_file_state.name
                 try:
                     with open(receptor_save_path, "wb") as f:
                         f.write(receptor_file_state.getbuffer())
                     config["receptor"] = str(receptor_save_path)
                     logger.info(f"Saved uploaded receptor to temp file: {receptor_save_path}")
                 except Exception as e:
                     st.error(f"Failed to save uploaded receptor file: {e}")
                     logger.error(f"Failed to save uploaded receptor file: {e}", exc_info=True)
            elif receptor_path_state and os.path.exists(receptor_path_state):
                 config["receptor"] = receptor_path_state
            elif receptor_path_state: # Path provided but doesn't exist
                 st.warning(f"Specified receptor path does not exist: {receptor_path_state}. It will not be included in the config.")
                 config["receptor"] = None # Explicitly set to None or omit key
            else:
                 config["receptor"] = None # No receptor specified

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
            config["program_choice"] = st.session_state.program_choice_input
            config["scoring_function"] = st.session_state.scoring_function_input
            config["center"] = [st.session_state.center_x, st.session_state.center_y, st.session_state.center_z]
            config["exhaustiveness"] = st.session_state.exhaustiveness_input
            config["is_selfies"] = st.session_state.is_selfies_input
            config["is_peptide"] = st.session_state.is_peptide_input
            config["top_n"] = st.session_state.top_n_input
            config["max_variants"] = st.session_state.max_variants_input
            config["num_rounds"] = st.session_state.num_rounds_input
            config["boltz_evaluation_method"] = st.session_state.boltz_evaluation_method_input
            config["out_dir"] = str(output_path) # Use the validated, absolute path


            # --- Save final configuration in session state ---
            st.session_state.pipeline_config = config
            st.success(f"Configuration saved successfully! Output will be in '{output_path}'. Proceed to the Execution page.")
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