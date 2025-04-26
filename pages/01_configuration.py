import streamlit as st
import os
from pathlib import Path
import tempfile
import py3Dmol
import re
import streamlit.components.v1 as components
import logging

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

# Initialize session state variables
if "pipeline_config" not in st.session_state:
    st.session_state.pipeline_config = None

if "stop_pipeline" not in st.session_state:
    st.session_state.stop_pipeline = False

if "model_choice" not in st.session_state:
    st.session_state.model_choice = "diffsbdd"

# Flag to trigger rerun after model selection update
if "model_update_requested" not in st.session_state:
    st.session_state.model_update_requested = False

# Default values for model-specific parameters
if "diffsbdd_params" not in st.session_state:
    st.session_state.diffsbdd_params = {
        "resi_list": "A:719 A:770 A:841 A:856 A:887 A:888",
        "sanitize": True,
        "size_x": 40,
        "size_y": 40, 
        "size_z": 40
    }

if "pocket2mol_params" not in st.session_state:
    st.session_state.pocket2mol_params = {
        "bbox_size": 23.0
    }

def parse_residue_list(resi_list):
    """Parse residue list string into a list of chain and residue numbers"""
    residues = []
    for res in resi_list.split():
        if ':' in res:
            chain, num = res.split(':')
            residues.append((chain, int(num)))
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

def visualize_protein_residues(pdb_content, selected_residues=None, center=None, box_size=None, bbox_size=None, show_both_boxes=False):
    """Create a py3Dmol visualization of the protein with highlighted residues and docking box"""
    view = py3Dmol.view(width=800, height=600)
    view.addModel(pdb_content, "pdb")
    
    # Set up the basic protein visualization
    view.setStyle({'cartoon': {'color': 'lightgray'}})
    
    # Highlight selected residues
    if selected_residues:
        for chain, resnum in selected_residues:
            view.addStyle({
                'chain': chain,
                'resi': resnum
            }, {
                'cartoon': {'color': 'red'},
                'stick': {'color': 'red'},
                'labels': {'fontColor': 'black', 'showResname': True}
            })
    
    # Add docking box if parameters are provided
    if center and box_size:
        add_box(view, center=center, dimensions=box_size, color='blue')
    
    # Add Pocket2Mol generation box if parameters are provided
    if center and bbox_size:
        dimensions = [bbox_size, bbox_size, bbox_size]
        add_box(view, center=center, dimensions=dimensions, color='green')
    
    view.zoomTo()
    
    # Get the HTML representation
    html = view._make_html()
    
    # Return both the view object and HTML
    return view, html

def update_model_choice():
    """Function to update model choice based on form submission"""
    st.session_state.model_choice = st.session_state.model_selection
    st.session_state.model_update_requested = True # Set flag instead of calling rerun

st.title("⚙️ Pipeline Configuration")
st.markdown("""
    Configure the parameters for your drug discovery pipeline run.
    Required fields are marked with an asterisk (*).
""")

# Get current model from session state
current_model = st.session_state.model_choice

# Model selection form
with st.form(key="model_selection_form", border=True):
    st.markdown("""<div class="form-header"><h3>Model Selection</h3></div>""", unsafe_allow_html=True)
    
    # Model selection without on_change callback
    model_choice = st.selectbox(
        "AI Model for Molecule Generation *",
        options=["diffsbdd", "pocket2mol"],
        format_func=lambda x: "DiffSBDD" if x == "diffsbdd" else "Pocket2Mol",
        index=0 if current_model == "diffsbdd" else 1,
        key="model_selection",
        help="Select the AI model for generating molecules"
    )
    
    # Submit button for model selection
    model_submitted = st.form_submit_button("Update Model Selection", on_click=update_model_choice)

# Check if model update was requested and trigger rerun
if st.session_state.model_update_requested:
    st.session_state.model_update_requested = False # Reset flag
    st.rerun()

# Create tabs for better organization
tab1, tab2, tab3 = st.tabs(["Basic Configuration", "Box Settings", "Advanced Settings"])

# Using Streamlit form with the recommended best practices
with tab1:
    with st.form(key="basic_config_form", border=True):
        st.markdown("""<div class="form-header"><h3>File Uploads and Parameters</h3></div>""", unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            # PDB File upload
            st.subheader("PDB File")
            pdb_file = st.file_uploader(
                "Upload PDB File",
                type=["pdb"],
                help="Upload the target protein PDB file"
            )
            
            pdb_path_input = st.text_input(
                "OR Enter PDB File Path",
                value="",
                placeholder="Path to PDB file on server",
                help="Specify the path to the PDB file on the server"
            )
        
        with col2:
            # Receptor File upload
            st.subheader("Receptor File")
            receptor_file = st.file_uploader(
                "Upload Receptor File",
                type=["pdbqt"],
                help="Upload the receptor file for docking (optional)"
            )
            
            receptor_path_input = st.text_input(
                "OR Enter Receptor File Path",
                value="",
                placeholder="Path to PDBQT file on server",
                help="Specify the path to the PDBQT receptor file on the server"
            )
        
        if not receptor_file and not receptor_path_input:
            st.warning("⚠️ No receptor file uploaded or specified. Docking steps may be skipped or fail. Upload or specify a PDBQT receptor file if you want to perform docking.")
        
        st.markdown("""<div class="form-header"><h3>Model Parameters</h3></div>""", unsafe_allow_html=True)
        
        # Show model-specific parameters based on current selection
        if current_model == "diffsbdd":
            st.subheader("DiffSBDD Parameters")
            resi_list = st.text_input(
                "Residue List *",
                value=st.session_state.diffsbdd_params["resi_list"],
                help="Space-separated residue identifiers (format: CHAIN:RESIDUE)",
                key="diffsbdd_resi_list"
            )
            
            sanitize = st.checkbox(
                "Sanitize Generated Molecules",
                value=st.session_state.diffsbdd_params["sanitize"],
                help="Apply sanitization to generated molecules",
                key="diffsbdd_sanitize"
            )
            
            # Store values in session state
            st.session_state.diffsbdd_params["resi_list"] = resi_list
            st.session_state.diffsbdd_params["sanitize"] = sanitize
        else:
            # Display a message for Pocket2Mol
            st.info("Pocket2Mol uses 3D pocket information instead of residue lists. The bounding box settings can be configured in the 'Box Settings' tab.")
        
        # Common parameters
        col3, col4 = st.columns(2)
        
        with col3:
            n_samples = st.number_input(
                "Number of Samples",
                min_value=1,
                max_value=500,
                value=5,
                help="Number of compounds to generate"
            )
        
        with col4:
            program_choice = st.selectbox(
                "Docking Program",
                options=["qvina"],
                index=0,
                help="Select the docking program to use"
            )
            
            scoring_function = st.selectbox(
                "Scoring Function",
                options=["nnscore2"],
                index=0,
                help="Select the scoring function for docking"
            )

        # Submit button for this form
        basic_config_submitted = st.form_submit_button("Save Basic Configuration", use_container_width=True)

with tab2:
    with st.form(key="box_config_form", border=True):
        st.markdown("""<div class="form-header"><h3>Box Configuration</h3></div>""", unsafe_allow_html=True)
        
        # Common center coordinates
        st.subheader("Center Coordinates (used for both generation and docking)")
        col5, col6, col7 = st.columns(3)
        
        with col5:
            center_x = st.number_input("Center X", value=114.817, format="%.3f")
        with col6:
            center_y = st.number_input("Center Y", value=75.602, format="%.3f")
        with col7:
            center_z = st.number_input("Center Z", value=82.416, format="%.3f")
        
        # Model-specific box configurations
        if current_model == "diffsbdd":
            st.subheader("Docking Box Dimensions")
            st.info("DiffSBDD uses residue list for molecule generation, so only docking box dimensions are needed.")
            
            col8, col9, col10 = st.columns(3)
            with col8:
                size_x = st.number_input(
                    "Docking Size X", 
                    value=st.session_state.diffsbdd_params["size_x"], 
                    min_value=1,
                    key="diffsbdd_size_x"
                )
            with col9:
                size_y = st.number_input(
                    "Docking Size Y", 
                    value=st.session_state.diffsbdd_params["size_y"], 
                    min_value=1,
                    key="diffsbdd_size_y"
                )
            with col10:
                size_z = st.number_input(
                    "Docking Size Z", 
                    value=st.session_state.diffsbdd_params["size_z"], 
                    min_value=1,
                    key="diffsbdd_size_z"
                )
            
            # Store values in session state
            st.session_state.diffsbdd_params["size_x"] = size_x
            st.session_state.diffsbdd_params["size_y"] = size_y
            st.session_state.diffsbdd_params["size_z"] = size_z
            
        else:  # pocket2mol
            # Initialize docking box params if not in session state
            if "pocket2mol_docking_box" not in st.session_state:
                st.session_state.pocket2mol_docking_box = {
                    "size_x": 38,
                    "size_y": 70,
                    "size_z": 58
                }
            
            # Generation box (bounding box) for Pocket2Mol
            st.subheader("Molecule Generation Box")
            st.info("This defines the cubic space where Pocket2Mol will generate molecules")
            bbox_size = st.number_input(
                "Generation Box Size", 
                value=st.session_state.pocket2mol_params["bbox_size"], 
                min_value=1.0, 
                format="%.1f",
                help="Size of the cubic bounding box for Pocket2Mol generation (single value used for all dimensions)",
                key="pocket2mol_bbox_size"
            )
            
            # Store value in session state
            st.session_state.pocket2mol_params["bbox_size"] = bbox_size
            
            # Docking box for Pocket2Mol
            st.subheader("Docking Box Dimensions")
            st.info("This defines the space where molecule docking will occur (can be different from generation box)")
            
            col8, col9, col10 = st.columns(3)
            with col8:
                dock_size_x = st.number_input(
                    "Docking Size X", 
                    value=st.session_state.pocket2mol_docking_box["size_x"], 
                    min_value=1,
                    key="pocket2mol_dock_size_x"
                )
            with col9:
                dock_size_y = st.number_input(
                    "Docking Size Y", 
                    value=st.session_state.pocket2mol_docking_box["size_y"], 
                    min_value=1,
                    key="pocket2mol_dock_size_y"
                )
            with col10:
                dock_size_z = st.number_input(
                    "Docking Size Z", 
                    value=st.session_state.pocket2mol_docking_box["size_z"], 
                    min_value=1,
                    key="pocket2mol_dock_size_z"
                )
            
            # Store values in session state
            st.session_state.pocket2mol_docking_box["size_x"] = dock_size_x
            st.session_state.pocket2mol_docking_box["size_y"] = dock_size_y 
            st.session_state.pocket2mol_docking_box["size_z"] = dock_size_z
        
        # Submit button for this form
        box_config_submitted = st.form_submit_button("Save Box Configuration", use_container_width=True)

with tab3:
    with st.form(key="advanced_config_form", border=True):
        st.markdown("""<div class="form-header"><h3>Advanced Parameters</h3></div>""", unsafe_allow_html=True)
        
        col7, col8 = st.columns(2)
        
        with col7:
            exhaustiveness = st.number_input(
                "Exhaustiveness",
                min_value=1,
                max_value=100,
                value=32,
                help="Docking exhaustiveness parameter"
            )
            
            is_selfies = st.checkbox(
                "Use SELFIES Representation",
                value=False,
                help="Use SELFIES molecular representation"
            )
        
        with col8:
            is_peptide = st.checkbox(
                "Ligand is Peptide",
                value=False,
                help="Check if the ligand is a peptide"
            )
            
            num_rounds = st.number_input(
                "Number of Rounds",
                min_value=1,
                max_value=100000,
                value=1,
                help="Number of pipeline rounds to run"
            )
        
        st.markdown("""<div class="form-header"><h3>Output Configuration</h3></div>""", unsafe_allow_html=True)
        
        col9, col10 = st.columns(2)
        
        with col9:
            output_dir_name = st.text_input(
                "Output Directory Name",
                value="pipeline_output",
                help="Name of the output directory where results will be stored"
            )
            
            top_n = st.number_input(
                "Top N Compounds",
                min_value=1,
                max_value=100,
                value=5,
                help="Number of top compounds to process"
            )
        
        with col10:
            max_variants = st.number_input(
                "Maximum Variants per Compound",
                min_value=1,
                max_value=20,
                value=5,
                help="Maximum number of variants to generate per compound"
            )
        
        # Submit button for advanced settings
        advanced_config_submitted = st.form_submit_button("Save Advanced Configuration", use_container_width=True)

# Finalize configuration button - placed outside of the forms
finalize_container = st.container()
with finalize_container:
    finalize_col1, finalize_col2 = st.columns([3, 1])
    with finalize_col2:
        finalize_submitted = st.button("Finalize & Save All Configuration", type="primary", use_container_width=True)

# Handle form submission
if basic_config_submitted or box_config_submitted or advanced_config_submitted or finalize_submitted:
    # Check if both forms have been submitted or if the finalize button was clicked
    all_forms_submitted = finalize_submitted
    
    # Validate required fields
    validation_error = False
    
    if not pdb_file and not pdb_path_input:
        st.error("Please either upload a PDB file or specify a file path")
        validation_error = True
    
    # Validate model-specific required fields
    if current_model == "diffsbdd" and not st.session_state.diffsbdd_params["resi_list"]:
        st.error("Please fill in the residue list for DiffSBDD")
        validation_error = True
    
    if not validation_error:
        # Check if output directory already exists
        project_root = Path(__file__).parent.parent 
        output_path = project_root / "outputs" / output_dir_name
        if output_path.exists():
            st.error(f"Output directory '{output_dir_name}' already exists. Please choose a different name.")
        else:
            # Create temporary directory for file uploads if needed
            temp_dir = Path(tempfile.mkdtemp())
            
            # Save uploaded files
            config = {}
            pdb_content = None
            
            # Set model choice
            config["model"] = current_model
            
            # Always use default checkpoint path for DiffSBDD
            if current_model == "diffsbdd":
                config["checkpoint"] = "src/DiffSBDD/checkpoints/crossdocked_fullatom_cond.ckpt"
            
            # Handle PDB file (either uploaded or path)
            if pdb_file:
                pdb_path = temp_dir / pdb_file.name
                with open(pdb_path, "wb") as f:
                    f.write(pdb_file.getbuffer())
                config["pdbfile"] = str(pdb_path)
                pdb_content = pdb_file.getvalue().decode('utf-8')
            elif pdb_path_input:
                config["pdbfile"] = pdb_path_input
                try:
                    with open(pdb_path_input, "r") as f:
                        pdb_content = f.read()
                except FileNotFoundError:
                    st.error(f"PDB file not found at path: {pdb_path_input}")
            
            # Handle receptor file if uploaded or path specified
            if receptor_file:
                receptor_path = temp_dir / receptor_file.name
                with open(receptor_path, "wb") as f:
                    f.write(receptor_file.getbuffer())
                config["receptor"] = str(receptor_path)
                st.success(f"Receptor file '{receptor_file.name}' saved successfully!")
            elif receptor_path_input:
                config["receptor"] = receptor_path_input
                if not os.path.exists(receptor_path_input):
                    st.warning(f"Receptor file not found at path: {receptor_path_input}. Please verify the path is correct.")
                else:
                    st.success(f"Receptor file path '{receptor_path_input}' specified successfully!")
            
            # Add model-specific parameters
            if current_model == "diffsbdd":
                config.update({
                    "resi_list": st.session_state.diffsbdd_params["resi_list"],
                    "sanitize": st.session_state.diffsbdd_params["sanitize"],
                    "box_size": [
                        st.session_state.diffsbdd_params["size_x"], 
                        st.session_state.diffsbdd_params["size_y"], 
                        st.session_state.diffsbdd_params["size_z"]
                    ]
                })
            else:  # pocket2mol
                config.update({
                    "bbox_size": st.session_state.pocket2mol_params["bbox_size"],
                    "box_size": [
                        st.session_state.pocket2mol_docking_box["size_x"],
                        st.session_state.pocket2mol_docking_box["size_y"],
                        st.session_state.pocket2mol_docking_box["size_z"]
                    ]
                })
            
            # Add common parameters
            config.update({
                "n_samples": n_samples,
                "program_choice": program_choice,
                "scoring_function": scoring_function,
                "center": [center_x, center_y, center_z],
                "exhaustiveness": exhaustiveness,
                "is_selfies": is_selfies,
                "is_peptide": is_peptide,
                "top_n": top_n,
                "max_variants": max_variants,
                "num_rounds": num_rounds,
                "out_dir": str(output_path)
            })
            
            # Save configuration in session state if finalized or if all individual forms were submitted
            if all_forms_submitted:
                st.session_state.pipeline_config = config
                st.success("Configuration saved successfully! Proceed to the Execution page to run the pipeline.")

# Add visualization section if PDB is uploaded or path is specified
if pdb_file is not None or (pdb_path_input and os.path.exists(pdb_path_input)):
    st.write("### Protein Structure Visualization")
    
    if current_model == "diffsbdd":
        st.write("Selected residues are highlighted in red. Docking box shown in blue.")
    else:  # pocket2mol
        st.write("Pocket2Mol generation box shown in green. Docking box shown in blue.")
    
    # Read PDB content
    if pdb_file is not None:
        pdb_content = pdb_file.getvalue().decode('utf-8')
    else:
        try:
            with open(pdb_path_input, 'r') as f:
                pdb_content = f.read()
        except Exception as e:
            st.error(f"Error reading PDB file: {str(e)}")
            pdb_content = None
    
    if pdb_content:
        # Get current box parameters
        center = [center_x, center_y, center_z]
        
        if current_model == "diffsbdd":
            # Parse residue list for DiffSBDD
            selected_residues = parse_residue_list(st.session_state.diffsbdd_params["resi_list"])
            box_size = [
                st.session_state.diffsbdd_params["size_x"],
                st.session_state.diffsbdd_params["size_y"],
                st.session_state.diffsbdd_params["size_z"]
            ]
            bbox_size_val = None
        else:  # pocket2mol
            selected_residues = None
            # For Pocket2Mol, show both docking box and generation box
            box_size = [
                st.session_state.pocket2mol_docking_box["size_x"],
                st.session_state.pocket2mol_docking_box["size_y"],
                st.session_state.pocket2mol_docking_box["size_z"]
            ]
            bbox_size_val = st.session_state.pocket2mol_params["bbox_size"]
        
        # Create visualization with appropriate box
        view, html = visualize_protein_residues(
            pdb_content, 
            selected_residues=selected_residues, 
            center=center, 
            box_size=box_size,
            bbox_size=bbox_size_val
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
        - Selected residues (DiffSBDD only): Red cartoon and sticks with labels
        - Docking box: Blue transparent box with wireframe
        - Pocket2Mol generation box: Green cubic box with wireframe (Pocket2Mol only)
        """)

# Display current configuration
if st.session_state.pipeline_config is not None:
    st.header("Current Configuration")
    
    # Add stop button if pipeline is running
    if st.session_state.get("pipeline_status", {}).get("running", False):
        if st.button("Stop Pipeline", type="secondary", key="stop_button"):
            st.session_state.stop_pipeline = True
            st.warning("Stopping pipeline execution... Please wait.")
    
    st.json(st.session_state.pipeline_config) 