import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import py3Dmol
from rdkit import Chem
from rdkit.Chem import Draw
from rdkit.Chem import AllChem
import base64
import io
import os
import json
import time
import streamlit.components.v1 as components

# Function to render molecule
def render_mol(smiles, width=400, height=300):
    """Render molecule using RDKit"""
    try:
        if smiles is None or pd.isna(smiles) or smiles == "":
            st.warning("No valid SMILES string provided")
            return None
            
        # Clean the SMILES string
        smiles = str(smiles).strip()
        
        # Try to generate the molecule
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            st.warning(f"Could not parse SMILES: {smiles}")
            return None
            
        # Generate 2D coordinates if they don't exist
        if mol.GetNumConformers() == 0:
            AllChem.Compute2DCoords(mol)
            
        # Create the image
        img = Draw.MolToImage(mol, size=(width, height))
        return img
    except Exception as e:
        st.error(f"Error rendering molecule: {str(e)}")
        return None

def display_molecule(sdf_path):
    """Display a molecule from an SDF file using RDKit"""
    try:
        # Read the SDF file
        suppl = Chem.SDMolSupplier(str(sdf_path))
        if suppl is None or len(suppl) == 0:
            st.warning("No molecules found in the SDF file.")
            return
        
        # Get the first molecule (SDF files can contain multiple molecules)
        mol = suppl[0]
        if mol is None:
            st.warning("Failed to load molecule from SDF file.")
            return
        
        # Generate 2D coordinates if they don't exist
        if mol.GetNumConformers() == 0:
            AllChem.Compute2DCoords(mol)
        
        # Create the image
        img = Draw.MolToImage(mol)
        
        # Display the image
        st.image(img, caption="Molecular Structure", use_container_width=True)
        
        # Display additional information if available
        props = mol.GetPropsAsDict()
        if props:
            with st.expander("Molecule Properties"):
                st.json(props)
                
    except Exception as e:
        st.error(f"Error displaying molecule: {str(e)}")
        import traceback
        st.code(traceback.format_exc())

def create_auto_scrolling_text_area(content, height=400):
    """Create an auto-scrolling text area using HTML and JavaScript with syntax highlighting"""
    # Escape HTML special characters
    content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # Add syntax highlighting for common log patterns
    content = content.replace("ERROR", '<span style="color: #ff6b6b;">ERROR</span>')
    content = content.replace("WARNING", '<span style="color: #ffd93d;">WARNING</span>')
    content = content.replace("INFO", '<span style="color: #6bff6b;">INFO</span>')
    content = content.replace("DEBUG", '<span style="color: #6b6bff;">DEBUG</span>')
    
    # Add syntax highlighting for pipeline stages
    stages = [
        "Running ligand generation",
        "Running retrosynthesis",
        "Starting batch filtering",
        "Starting docking",
        "Pipeline completed successfully",
        "STARTING ROUND",
        "COMPLETED ROUND"
    ]
    
    for stage in stages:
        content = content.replace(stage, f'<span style="color: #ffa500;">{stage}</span>')
    
    html = f"""
        <div style="
            height: {height}px;
            overflow-y: auto;
            border: 1px solid #2e2e2e;
            border-radius: 4px;
            padding: 12px;
            background-color: #1e1e1e;
            color: #d4d4d4;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 14px;
            line-height: 1.5;
            margin-bottom: 20px;
        ">
            <pre id="log-content" style="margin: 0; white-space: pre-wrap; padding-bottom: 20px;">{content}</pre>
        </div>
        <script>
            // Function to scroll to bottom
            function scrollToBottom() {{
                var element = document.getElementById('log-content');
                var container = element.parentElement;
                container.scrollTop = container.scrollHeight;
                // Add a small delay to ensure the scroll happens after content is rendered
                setTimeout(() => {{
                    container.scrollTop = container.scrollHeight;
                }}, 100);
            }}
            
            // Initial scroll
            scrollToBottom();
            
            // Set up a mutation observer to watch for content changes
            var observer = new MutationObserver(function(mutations) {{
                scrollToBottom();
            }});
            
            observer.observe(document.getElementById('log-content'), {{
                childList: true,
                characterData: true,
                subtree: true
            }});
            
            // Also scroll on window resize
            window.addEventListener('resize', scrollToBottom);
        </script>
    """
    return components.html(html, height=height)

def read_log_file(log_path):
    """Read a log file with error handling"""
    try:
        if not Path(log_path).exists():
            return None
            
        with open(log_path, 'r') as f:
            return f.read()
    except Exception as e:
        st.error(f"Error reading log file {log_path}: {str(e)}")
        return None

def read_json_file(file_path):
    """Read and parse a JSON file with error handling"""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Error reading JSON file {file_path}: {str(e)}")
        return None

def get_directory_tree(path, prefix="", is_last=True, max_depth=3, current_depth=0):
    """Generate a tree-like structure of the directory with depth limit"""
    output = []
    path = Path(path)
    
    # Create the directory if it doesn't exist
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        st.warning(f"Error creating directory {path}: {e}")
        return ["Error creating directory"]
    
    # Add current directory
    output.append(f"{prefix}{'└── ' if is_last else '├── '}{path.name}/")
    
    # Stop if we've reached max depth
    if current_depth >= max_depth:
        return output
    
    # Prepare prefix for children
    child_prefix = prefix + ('    ' if is_last else '│   ')
    
    try:
        # Get all items in directory
        items = sorted(list(path.iterdir()), key=lambda x: (not x.is_dir(), x.name))
        
        # Process each item
        for i, item in enumerate(items):
            is_last_item = i == len(items) - 1
            
            if item.is_dir():
                # Recursively process directories
                output.extend(get_directory_tree(item, child_prefix, is_last_item, max_depth, current_depth + 1))
            else:
                # Add files
                output.append(f"{child_prefix}{'└── ' if is_last_item else '├── '}{item.name}")
    except Exception as e:
        st.warning(f"Error reading directory {path}: {e}")
        output.append(f"{child_prefix}Error reading directory: {str(e)}")
    
    return output

# Function to load results
def load_results(output_dir):
    """Load results from the output directory"""
    output_dir = Path(output_dir)
    results = {
        "tracking_report": None
    }
    
    # Load tracking report
    tracking_file = output_dir / "master_tracking" / "master_compound_tracking_report.csv"
    
    if tracking_file.exists():
        try:
            results["tracking_report"] = pd.read_csv(tracking_file)
            st.success("Successfully loaded tracking report.")
        except Exception as e:
            st.error(f"Error reading tracking report: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
    else:
        st.warning(f"Tracking report not found at: {tracking_file}")
        # Check if there are any round-specific tracking reports
        possible_rounds = [1, 2, 3, 4, 5]  # Assuming max 5 rounds
        for round_num in possible_rounds:
            round_tracking = output_dir / f"round_{round_num}" / f"round_{round_num}_tracking_report.csv"
            if round_tracking.exists():
                st.info(f"Found round-specific tracking report: {round_tracking}")
                try:
                    results["tracking_report"] = pd.read_csv(round_tracking)
                    st.success(f"Loaded tracking report from round {round_num}.")
                    break
                except Exception as e:
                    st.error(f"Error reading round tracking report: {str(e)}")
    
    return results

# Function to display 3D structure
def render_3d_structure(ligand_file, receptor_file=None):
    """
    Render 3D structure of ligand and optionally receptor using py3Dmol
    
    Args:
        ligand_file: Path to ligand structure file (PDBQT, PDB, or SDF)
        receptor_file: Optional path to receptor structure file (PDBQT or PDB)
    
    Returns:
        HTML string for embedding in Streamlit
    """
    try:
        view = py3Dmol.view(width=800, height=600)
        
        # Handle different ligand file formats
        ligand_path = Path(ligand_file)
        
        if ligand_path.suffix.lower() == '.sdf':
            # Handle SDF files using RDKit to convert to PDB format
            try:
                from rdkit import Chem
                from rdkit.Chem import AllChem
                
                # Read SDF and convert to PDB format
                suppl = Chem.SDMolSupplier(str(ligand_path))
                mol = next(suppl)
                
                if mol is not None:
                    # Add hydrogens and generate 3D coordinates if needed
                    mol = Chem.AddHs(mol)
                    if mol.GetNumConformers() == 0:
                        AllChem.EmbedMolecule(mol, randomSeed=42)
                        AllChem.UFFOptimizeMolecule(mol)
                    
                    # Convert to PDB format
                    pdb_block = Chem.MolToPDBBlock(mol)
                    view.addModel(pdb_block, 'pdb')
                    view.setStyle({'model': 0}, {'stick': {'colorscheme': 'greenCarbon', 'radius': 0.2}})
                else:
                    st.error("Could not read molecule from SDF file")
                    return None
                    
            except ImportError:
                st.error("RDKit is required to display SDF files")
                return None
            except Exception as e:
                st.error(f"Error processing SDF file: {e}")
                return None
                
        else:
            # Handle PDBQT and PDB files directly
            with open(ligand_file) as f:
                ligand_data = f.read()
            
            # Determine file format for py3Dmol
            ligand_format = 'pdbqt' if ligand_path.suffix.lower() == '.pdbqt' else 'pdb'
            
            # Add ligand model
            view.addModel(ligand_data, ligand_format)
            view.setStyle({'model': 0}, {'stick': {'colorscheme': 'greenCarbon', 'radius': 0.2}})
        
        # Add receptor if provided
        if receptor_file and Path(receptor_file).exists():
            with open(receptor_file) as f:
                receptor_data = f.read()
            
            # Determine format for receptor
            receptor_format = 'pdbqt' if str(receptor_file).lower().endswith('.pdbqt') else 'pdb'
            
            # Add receptor as separate model
            view.addModel(receptor_data, receptor_format)
            view.setStyle({'model': 1}, {'cartoon': {'color': 'spectrum', 'opacity': 0.8}})
            
            # Add binding site surface
            view.addSurface(py3Dmol.VDW, {'opacity': 0.3, 'color': 'lightblue'}, {'model': 1})
        
        # Set view options
        view.zoomTo()
        view.setBackgroundColor('white')
        
        # Add labels and improve visualization
        view.addLabel("Ligand", {'position': {'x': 0, 'y': 0, 'z': 0}, 'backgroundColor': 'green', 'fontColor': 'white'})
        
        return view._make_html()
    
    except Exception as e:
        st.error(f"Error rendering 3D structure: {e}")
        return None

def render_unidock_result_3d(result_file_path, receptor_file=None):
    """
    Render Unidock docking result in 3D with multiple poses if available
    
    Args:
        result_file_path: Path to Unidock result file (SDF or PDBQT)
        receptor_file: Optional path to receptor file
        
    Returns:
        HTML string for embedding in Streamlit
    """
    try:
        result_path = Path(result_file_path)
        
        if not result_path.exists():
            st.error(f"Result file not found: {result_path}")
            return None
            
        view = py3Dmol.view(width=800, height=600)
        
        if result_path.suffix.lower() == '.sdf':
            # Handle SDF files with multiple poses
            try:
                from rdkit import Chem
                from rdkit.Chem import AllChem
                
                suppl = Chem.SDMolSupplier(str(result_path))
                pose_count = 0
                
                for i, mol in enumerate(suppl):
                    if mol is not None:
                        pose_count += 1
                        # Convert to PDB format
                        pdb_block = Chem.MolToPDBBlock(mol)
                        view.addModel(pdb_block, 'pdb')
                        
                        # Style each pose differently
                        if i == 0:
                            # Best pose in green
                            view.setStyle({'model': i}, {'stick': {'colorscheme': 'greenCarbon', 'radius': 0.3}})
                        else:
                            # Other poses in different colors
                            colors = ['cyanCarbon', 'magentaCarbon', 'yellowCarbon', 'orangeCarbon']
                            color = colors[min(i-1, len(colors)-1)]
                            view.setStyle({'model': i}, {'stick': {'colorscheme': color, 'radius': 0.2, 'opacity': 0.7}})
                
                if pose_count == 0:
                    st.error("No valid poses found in SDF file")
                    return None
                    
            except ImportError:
                st.error("RDKit is required to display SDF files")
                return None
            except Exception as e:
                st.error(f"Error processing SDF file: {e}")
                return None
                
        elif result_path.suffix.lower() == '.pdbqt':
            # Handle PDBQT files with multiple models
            with open(result_path) as f:
                pdbqt_data = f.read()
            
            # Split into individual models if multiple exist
            models = pdbqt_data.split('MODEL')
            
            for i, model_data in enumerate(models):
                if model_data.strip():
                    if i > 0:  # Skip the first empty split
                        model_data = 'MODEL' + model_data
                    
                    view.addModel(model_data, 'pdbqt')
                    
                    # Style each model
                    if i == 1:  # First actual model (best pose)
                        view.setStyle({'model': i-1}, {'stick': {'colorscheme': 'greenCarbon', 'radius': 0.3}})
                    else:
                        colors = ['cyanCarbon', 'magentaCarbon', 'yellowCarbon', 'orangeCarbon']
                        color = colors[min(i-2, len(colors)-1)] if i > 1 else 'cyanCarbon'
                        view.setStyle({'model': i-1}, {'stick': {'colorscheme': color, 'radius': 0.2, 'opacity': 0.7}})
        
        # Add receptor if provided
        receptor_model_index = view.getNumModels()
        if receptor_file and Path(receptor_file).exists():
            with open(receptor_file) as f:
                receptor_data = f.read()
            
            receptor_format = 'pdbqt' if str(receptor_file).lower().endswith('.pdbqt') else 'pdb'
            view.addModel(receptor_data, receptor_format)
            view.setStyle({'model': receptor_model_index}, {
                'cartoon': {'color': 'spectrum', 'opacity': 0.8},
                'line': {'hidden': True}
            })
            
            # Add binding site surface around ligands
            view.addSurface(py3Dmol.VDW, {
                'opacity': 0.2, 
                'color': 'lightblue'
            }, {'model': receptor_model_index})
        
        # Set view options
        view.zoomTo()
        view.setBackgroundColor('white')
        
        # Add informative labels
        view.addLabel("Best Pose", {
            'position': {'x': 0, 'y': 0, 'z': 5}, 
            'backgroundColor': 'green', 
            'fontColor': 'white',
            'fontSize': 12
        })
        
        return view._make_html()
        
    except Exception as e:
        st.error(f"Error rendering Unidock result: {e}")
        return None

def create_interactive_3d_viewer(result_data, output_dir_path):
    """
    Create an interactive 3D viewer for docking results with pose selection
    
    Args:
        result_data: Dictionary containing docking result information
        output_dir_path: Path to output directory
        
    Returns:
        None (displays in Streamlit)
    """
    try:
        variant_id = result_data.get('variant_id', result_data.get('compound_id', 'Unknown'))
        barcode = result_data.get('barcode', 'Unknown')
        round_num = result_data.get('round', 1)
        
        # Try to find result files
        result_file = result_data.get('result_file')
        
        # Look for receptor file
        receptor_file = None
        possible_receptor_paths = [
            output_dir_path / f"round_{round_num}" / "workflow_results" / "receptor_prepared.pdbqt",
            output_dir_path.parent / "input" / "receptor.pdbqt",
            output_dir_path.parent / "input" / "receptor.pdb"
        ]
        
        for receptor_path in possible_receptor_paths:
            if receptor_path.exists():
                receptor_file = receptor_path
                break
        
        if result_file and Path(result_file).exists():
            st.markdown("### 🧬 3D Molecular Visualization")
            
            # Create tabs for different views
            tab1, tab2, tab3 = st.tabs(["📊 Docking Result", "🔬 Ligand Only", "📋 Information"])
            
            with tab1:
                st.markdown("**Docking Result with Receptor**")
                if receptor_file:
                    html_content = render_unidock_result_3d(result_file, receptor_file)
                    if html_content:
                        components.html(html_content, height=600, width=800)
                        st.caption("🟢 Best pose | 🔵🟣🟡🟠 Alternative poses | 🌈 Protein receptor")
                    else:
                        st.error("Failed to render 3D structure")
                else:
                    st.warning("Receptor file not found. Showing ligand only.")
                    html_content = render_unidock_result_3d(result_file)
                    if html_content:
                        components.html(html_content, height=600, width=800)
            
            with tab2:
                st.markdown("**Ligand Structure Only**")
                html_content = render_unidock_result_3d(result_file)
                if html_content:
                    components.html(html_content, height=600, width=800)
                    st.caption("🟢 Best pose | 🔵🟣🟡🟠 Alternative poses")
            
            with tab3:
                st.markdown("**File Information**")
                file_info = {
                    "Result File": str(Path(result_file).name),
                    "File Size": f"{Path(result_file).stat().st_size / 1024:.1f} KB",
                    "File Type": Path(result_file).suffix.upper(),
                    "Receptor File": str(Path(receptor_file).name) if receptor_file else "Not found"
                }
                
                if "pose_count" in result_data:
                    file_info["Pose Count"] = result_data["pose_count"]
                
                if "all_scores" in result_data and result_data["all_scores"]:
                    try:
                        all_scores_str = str(result_data["all_scores"])
                        if all_scores_str.startswith('[') and all_scores_str.endswith(']'):
                            import ast
                            all_scores = ast.literal_eval(all_scores_str)
                            file_info["Score Range"] = f"{min(all_scores):.2f} to {max(all_scores):.2f}"
                    except:
                        pass
                
                st.json(file_info)
                
                # Download buttons
                col1, col2 = st.columns(2)
                with col1:
                    with open(result_file, 'rb') as f:
                        file_data = f.read()
                    st.download_button(
                        "📥 Download Result File",
                        data=file_data,
                        file_name=Path(result_file).name,
                        mime="application/octet-stream",
                        key=f"download_result_{variant_id}"
                    )
                
                with col2:
                    if receptor_file and Path(receptor_file).exists():
                        with open(receptor_file, 'rb') as f:
                            receptor_data = f.read()
                        st.download_button(
                            "📥 Download Receptor",
                            data=receptor_data,
                            file_name=Path(receptor_file).name,
                            mime="application/octet-stream",
                            key=f"download_receptor_{variant_id}"
                        )
        else:
            st.warning("No 3D structure file available for this result")
            
    except Exception as e:
        st.error(f"Error creating 3D viewer: {e}")
        import traceback
        st.code(traceback.format_exc())

# Function to create downloadable link
def get_download_link(df, filename, text):
    """Create a download link for a dataframe"""
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    href = f'<a href="data:file/csv;base64,{b64}" download="{filename}">{text}</a>'
    return href

# -----------------------------------------------------------------------------
# Helper for Boltz-1x CIF loading and 3D visualisation  
# -----------------------------------------------------------------------------


def load_boltz_cif(output_root: Path, round_num, barcode):
    """Locate the first CIF file generated by Boltz-1x for a given variant.

    Returns path if found else None."""
    try:
        pred_dir = (
            output_root
            / f"round_{round_num}"
            / "Boltz_result"
            / barcode
            / "predictions"
            / "input"
        )
        if pred_dir.exists():
            cif_file = pred_dir / "input_model_0.cif"
            if cif_file.exists():
                return cif_file
    except Exception:
        pass
    return None


def render_boltz_cif(cif_path: Path):
    """Render a Boltz-1x CIF file with py3Dmol highlighting ligand (chain B)."""
    try:
        with open(cif_path) as fh:
            cif_data = fh.read()
        view = py3Dmol.view(width=800, height=600)
        view.addModel(cif_data, "cif")
        # Protein cartoon default
        view.setStyle({"chain": "A"}, {"cartoon": {"color": "spectrum"}})
        # Ligand sticks chain B
        view.setStyle({"chain": "B"}, {"stick": {"colorscheme": "greenCarbon"}})
        view.zoomTo()
        return view._make_html()
    except Exception as exc:
        return f"Failed to render CIF: {exc}"

# Page configuration
st.set_page_config(
    page_title="Pipeline Results",
    page_icon="📊",
    layout="wide"
)

# Add custom CSS for full-width layout
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
    </style>
""", unsafe_allow_html=True)

# Initialize session state variables
if "results" not in st.session_state:
    st.session_state.results = None

if "pipeline_config" not in st.session_state:
    st.session_state.pipeline_config = None

if "selected_view" not in st.session_state:
    st.session_state.selected_view = "Summary"

# Add a refresh flag to enable auto-refreshing for ongoing pipelines
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = False

st.title("📊 Results Dashboard")

# Add information about 3D visualization capabilities
with st.expander("🧬 3D Visualization Features", expanded=False):
    st.markdown("""
    **Available 3D Visualization Features:**
    
    🎯 **Docking Results Visualization**
    - Interactive 3D viewer for Unidock docking results
    - Multiple pose visualization with color coding
    - Receptor-ligand complex visualization
    - Support for SDF and PDBQT file formats
    
    🟢 **Best Pose** - Highlighted in green with thicker representation
    🔵🟣🟡🟠 **Alternative Poses** - Color-coded for easy identification
    🌈 **Protein Receptor** - Cartoon representation with binding site surface
    
    **Supported File Formats:**
    - SDF files (Unidock output with multiple poses)
    - PDBQT files (AutoDock/Vina format)
    - PDB files (Protein Data Bank format)
    
    **Interactive Controls:**
    - Zoom, rotate, and pan the 3D structure
    - Toggle between different visualization modes
    - Download structure files for external analysis
    """)
    
    # Check if required libraries are available
    try:
        import py3Dmol
        from rdkit import Chem
        st.success("✅ All required libraries (py3Dmol, RDKit) are available for 3D visualization")
    except ImportError as e:
        st.warning(f"⚠️ Some libraries missing for full 3D functionality: {e}")
        st.info("Install missing libraries with: `pip install py3Dmol rdkit`")

# Check if configuration exists
if not st.session_state.pipeline_config:
    st.warning("Please configure and run the pipeline first!")
    st.info("Go to the **Configure & Run** page to set up and launch a pipeline.")
    st.stop()

# Get the output directory path
output_dir = Path(st.session_state.pipeline_config.get("out_dir", ""))
output_dir_path = Path(output_dir) if output_dir else None

# Validate output directory
if not output_dir_path or not output_dir_path.exists():
    st.error(f"Output directory not found: {output_dir_path}")
    st.info("Please check if the pipeline has started running.")
    st.stop()

# Load results if available
if output_dir_path:
    with st.spinner("Loading results..."):
        try:
            results = load_results(output_dir_path)
            if results is None:
                st.error("Failed to load results")
                st.info("The pipeline may still be initializing or hasn't created any results files yet.")
            elif results.get("tracking_report") is None:
                st.warning("No tracking report found. The pipeline may still be in the initial stages.")
                
                # Check if there are any log files that can provide status information
                log_file = output_dir_path / "logs" / "quick_pipeline.log"
                if log_file.exists():
                    st.info("Pipeline log file found. Showing recent log entries:")
                    try:
                        with open(log_file, 'r') as f:
                            log_content = f.read()
                        
                        # Show the last 20 lines of the log
                        log_lines = log_content.splitlines()
                        if len(log_lines) > 20:
                            recent_logs = "\n".join(log_lines[-20:])
                        else:
                            recent_logs = log_content
                        
                        st.code(recent_logs, language="log")
                        
                        # Add auto-refresh option for ongoing pipelines
                        st.session_state.auto_refresh = st.checkbox(
                            "Auto-refresh data (every 30 seconds)",
                            value=st.session_state.auto_refresh,
                            key="auto_refresh_log_exists"
                        )
                        
                        if st.session_state.auto_refresh:
                            st.info("Auto-refresh enabled. The dashboard will update automatically.")
                            # Use JavaScript to auto-refresh the page
                            auto_refresh_js = """
                            <script>
                                setTimeout(function(){
                                    document.querySelector("button[kind=secondaryFormSubmit]").click();
                                }, 30000);
                            </script>
                            """
                            st.markdown(auto_refresh_js, unsafe_allow_html=True)
                    except Exception as e:
                        st.error(f"Error reading log file: {e}")
                else:
                    st.info("No log file found. The pipeline may not have started yet.")
            else:
                st.session_state.results = results
                st.success("Data loaded successfully!")
                
                # Check if the pipeline is still running by examining timestamps
                if "timestamp" in results["tracking_report"].columns:
                    try:
                        latest_timestamp = pd.to_datetime(results["tracking_report"]["timestamp"].max())
                        current_time = pd.to_datetime(pd.Timestamp.now())
                        time_diff = (current_time - latest_timestamp).total_seconds()
                        
                        # If the latest update was less than 5 minutes ago, consider the pipeline still running
                        if time_diff < 300:  # 5 minutes in seconds
                            st.info("Pipeline appears to be actively running. Data may continue to update.")
                            # Offer auto-refresh option
                            st.session_state.auto_refresh = st.checkbox(
                                "Auto-refresh data (every 30 seconds)",
                                value=st.session_state.auto_refresh,
                                key="auto_refresh_active_pipeline"
                            )
                            
                            if st.session_state.auto_refresh:
                                auto_refresh_js = """
                                <script>
                                    setTimeout(function(){
                                        document.querySelector("button[kind=secondaryFormSubmit]").click();
                                    }, 30000);
                                </script>
                                """
                                st.markdown(auto_refresh_js, unsafe_allow_html=True)
                    except Exception as e:
                        # Silently ignore timestamp parsing errors
                        pass
        except Exception as e:
            st.error(f"Error processing results: {str(e)}")
            import traceback
            st.code(traceback.format_exc())

# Sidebar for navigation
with st.sidebar:
    st.title("Dashboard Navigation")
    st.session_state.selected_view = st.radio(
        "Select View",
        ["Summary", "Compounds", "Variants", "Docking Results"]
    )
    
    st.divider()
    
    # Sidebar filtering options (global)
    st.subheader("Global Filters")
    if st.session_state.results is not None and st.session_state.results.get("tracking_report") is not None:
        df = st.session_state.results["tracking_report"]
        
        # Round filter (applies to all views)
        if "round" in df.columns:
            try:
                round_options = sorted([r for r in df["round"].unique() if pd.notna(r)])
                sidebar_rounds = st.multiselect(
                    "Filter by Round",
                    options=round_options,
                    default=round_options,
                    key="sidebar_rounds"
                )
            except Exception as e:
                st.error(f"Error loading round options: {e}")
                sidebar_rounds = []
        else:
            st.info("Round information not available for filtering")
            sidebar_rounds = []
        
        # Status filter
        if "status" in df.columns:
            try:
                status_options = sorted([s for s in df["status"].unique() if pd.notna(s)])
                sidebar_status = st.multiselect(
                    "Filter by Status",
                    options=status_options,
                    default=status_options,
                    key="sidebar_status"
                )
            except Exception as e:
                st.error(f"Error loading status options: {e}")
                sidebar_status = []
        else:
            st.info("Status information not available for filtering")
            sidebar_status = []
        
        # Apply global filters
        if sidebar_rounds and sidebar_status and "round" in df.columns and "status" in df.columns:
            try:
                filtered_df = df[df["round"].isin(sidebar_rounds) & df["status"].isin(sidebar_status)]
            except Exception as e:
                st.error(f"Error applying filters: {e}")
                filtered_df = df
        else:
            filtered_df = df
            
    # Add refresh button
    if st.button("🔄 Refresh Data"):
        if output_dir_path:
            with st.spinner("Refreshing data..."):
                results = load_results(output_dir_path)
                if results is not None:
                    st.session_state.results = results
                    st.success("Data refreshed successfully!")
                    st.rerun()
                else:
                    st.error("Failed to refresh data.")

# Main content - Conditional rendering based on the selected view
if st.session_state.results is not None and st.session_state.results.get("tracking_report") is not None:
    df = st.session_state.results["tracking_report"]
    
    # Check if we have any data at all
    if df.empty:
        st.warning("The tracking report is empty. The pipeline may still be in the initial stages.")
        
        # Add auto-refresh option for empty data
        st.session_state.auto_refresh = st.checkbox(
            "Auto-refresh data (every 30 seconds)",
            value=st.session_state.auto_refresh,
            key="auto_refresh_empty_df"
        )
        
        if st.session_state.auto_refresh:
            auto_refresh_js = """
            <script>
                setTimeout(function(){
                    document.querySelector("button[kind=secondaryFormSubmit]").click();
                }, 30000);
            </script>
            """
            st.markdown(auto_refresh_js, unsafe_allow_html=True)
    else:
        # Continue with regular view rendering based on selected view
        # Define available_statuses for use across all views
        available_statuses = df["status"].unique() if "status" in df.columns else []
                
        if st.session_state.selected_view == "Summary":
            st.header("Pipeline Summary")
            
            # Summary metrics
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                compound_count = len(df[df["status"] == "GENERATED"]) if "status" in df.columns else 0
                st.metric("Total Compounds", compound_count)
            with col2:
                variant_count = len(df[df["status"] == "SYNTHETIZED"]) if "status" in df.columns else 0
                st.metric("Total Variants", variant_count)
            with col3:
                filtered_count = len(
                    df[df["status"].isin(["PASSFILTER", "PASSBLINDDOCK"])]
                ) if "status" in df.columns else 0
                st.metric("Filtered Variants", filtered_count)
            with col4:
                docked_count = len(df[df["status"] == "DOCKED"]) if "status" in df.columns else 0
                st.metric("Docked Compounds", docked_count)
            with col5:
                # Show best docking score if available (lower is better)
                if "docking_score" in df.columns and df["docking_score"].notna().any():
                    best_score = df[df["docking_score"].notna()]["docking_score"].min()
                    st.metric("Best Score (lower=better)", f"{best_score:.2f}")
                else:
                    st.metric("Best Score (lower=better)", "N/A")
                        
            # Workflow Progress Visualization
            st.subheader("Workflow Progress")
            
            # Define workflow stages
            workflow_stages = [
                ("Generation", "GENERATED", "🧬"),
                ("Retrosynthesis", "SYNTHETIZED", "⚗️"),
                ("MedChem Filter", "PASSFILTER", "🔬"),
                ("Boltz Filter", "PASSBLINDDOCK", "🤖"),
                ("Docking", "DOCKED", "🎯")
            ]
            
            # Create progress indicators
            progress_cols = st.columns(len(workflow_stages))
            
            for i, (stage_name, status_key, emoji) in enumerate(workflow_stages):
                with progress_cols[i]:
                    count = len(df[df["status"] == status_key]) if "status" in df.columns else 0
                    is_complete = status_key in available_statuses and count > 0
                    
                    if is_complete:
                        st.success(f"{emoji} {stage_name}")
                        st.write(f"**{count}** items")
                    else:
                        st.info(f"{emoji} {stage_name}")
                        st.write("Pending")
            
            # Show detailed progress message
            progress_message = ""
            if "GENERATED" in available_statuses and "SYNTHETIZED" not in available_statuses:
                progress_message = "Pipeline has generated compounds but not yet completed retrosynthesis."
            elif "SYNTHETIZED" in available_statuses and "PASSFILTER" not in available_statuses:
                progress_message = "Pipeline has generated variants but not yet completed filtering."
            elif "PASSFILTER" in available_statuses and "DOCKED" not in available_statuses:
                progress_message = "Pipeline has filtered variants but not yet completed docking."
            elif "DOCKED" in available_statuses:
                progress_message = "Pipeline has completed all major stages successfully!"
            
            if progress_message:
                if "completed all major stages" in progress_message:
                    st.success(progress_message)
                else:
                    st.info(progress_message + " Some visualizations may not be available until those steps complete.")
            
            # Affinity Analysis Section
            if "affinity_pred_value" in df.columns and df["affinity_pred_value"].notna().any():
                st.subheader("🤖 Boltz-2 Affinity Analysis")
                
                affinity_with_values = df[df["affinity_pred_value"].notna()]
                if not affinity_with_values.empty:
                    # Create metrics for affinity (IC50 in μM - lower is better)
                    aff_col1, aff_col2, aff_col3, aff_col4 = st.columns(4)
                    with aff_col1:
                        best_affinity = affinity_with_values["affinity_pred_value"].min()  # Lower IC50 is better
                        st.metric("Best IC50 (lower=better)", f"{best_affinity:.3f} μM")
                    with aff_col2:
                        avg_affinity = affinity_with_values["affinity_pred_value"].mean()
                        st.metric("Average IC50", f"{avg_affinity:.3f} μM")
                    with aff_col3:
                        if "affinity_probability_binary" in affinity_with_values.columns:
                            high_prob_count = len(affinity_with_values[affinity_with_values["affinity_probability_binary"] > 0.5])
                            st.metric("High Confidence", f"{high_prob_count}/{len(affinity_with_values)}")
                        else:
                            st.metric("Predictions", len(affinity_with_values))
                    with aff_col4:
                        if "confidence_score" in affinity_with_values.columns:
                            avg_confidence = affinity_with_values["confidence_score"].mean()
                            st.metric("Avg Confidence", f"{avg_confidence:.3f}")
                        else:
                            median_affinity = affinity_with_values["affinity_pred_value"].median()
                            st.metric("Median IC50", f"{median_affinity:.3f} μM")
                    
                    # Create visualizations
                    viz_col1, viz_col2 = st.columns(2)
                    
                    with viz_col1:
                        # Affinity value distribution
                        fig_aff = px.histogram(
                            affinity_with_values,
                            x="affinity_pred_value",
                            nbins=20,
                            title="Distribution of IC50 Predictions (Lower = Better)",
                            color_discrete_sequence=["#00cc96"],
                            labels={"affinity_pred_value": "IC50 Prediction (μM)", "count": "Number of Compounds"}
                        )
                        fig_aff.update_layout(bargap=0.1)
                        st.plotly_chart(fig_aff, use_container_width=True)
                    
                    with viz_col2:
                        # Affinity vs Probability scatter plot if probability data exists
                        if "affinity_probability_binary" in affinity_with_values.columns:
                            fig_scatter = px.scatter(
                                affinity_with_values,
                                x="affinity_pred_value",
                                y="affinity_probability_binary",
                                title="IC50 Prediction vs Probability (Lower IC50 = Better)",
                                color="affinity_probability_binary",
                                color_continuous_scale="viridis",
                                labels={
                                    "affinity_pred_value": "IC50 Prediction (μM)",
                                    "affinity_probability_binary": "Binary Probability"
                                }
                            )
                            st.plotly_chart(fig_scatter, use_container_width=True)
                        else:
                            # Show affinity by round if multiple rounds exist
                            if "round" in affinity_with_values.columns and len(affinity_with_values["round"].unique()) > 1:
                                fig_box_aff = px.box(
                                    affinity_with_values,
                                    x="round",
                                    y="affinity_pred_value",
                                    title="IC50 Predictions by Round (Lower = Better)",
                                    color_discrete_sequence=["#00cc96"]
                                )
                                fig_box_aff.update_layout(
                                    xaxis_title="Round",
                                    yaxis_title="IC50 Prediction (μM)"
                                )
                                st.plotly_chart(fig_box_aff, use_container_width=True)
                            else:
                                # Show affinity statistics
                                st.markdown("**IC50 Statistics (μM):**")
                                aff_stats = affinity_with_values["affinity_pred_value"].describe()
                                aff_stats_df = pd.DataFrame({
                                    "Statistic": ["Count", "Mean", "Std", "Min", "25%", "50%", "75%", "Max"],
                                    "Value": [
                                        f"{aff_stats['count']:.0f}",
                                        f"{aff_stats['mean']:.3f}",
                                        f"{aff_stats['std']:.3f}",
                                        f"{aff_stats['min']:.3f}",
                                        f"{aff_stats['25%']:.3f}",
                                        f"{aff_stats['50%']:.3f}",
                                        f"{aff_stats['75%']:.3f}",
                                        f"{aff_stats['max']:.3f}"
                                    ]
                                })
                                st.dataframe(aff_stats_df, use_container_width=True, hide_index=True)
                    
                    # Show top affinity performers (lowest IC50 values are best)
                    st.markdown("**🏆 Top 10 IC50 Predictions (Lowest/Best Values):**")
                    top_affinity = affinity_with_values.nsmallest(10, "affinity_pred_value")
                    aff_display_cols = ["compound_id", "affinity_pred_value", "round"]
                    if "variant_id" in top_affinity.columns:
                        aff_display_cols.insert(1, "variant_id")
                    if "barcode" in top_affinity.columns:
                        aff_display_cols.insert(2, "barcode")
                    if "affinity_probability_binary" in top_affinity.columns:
                        aff_display_cols.insert(-1, "affinity_probability_binary")
                    if "confidence_score" in top_affinity.columns:
                        aff_display_cols.insert(-1, "confidence_score")
                    
                    existing_aff_cols = [col for col in aff_display_cols if col in top_affinity.columns]
                    st.dataframe(
                        top_affinity[existing_aff_cols],
                        use_container_width=True,
                        hide_index=True
                    )

            # Docking score distribution if available
            if "docking_score" in df.columns and df["docking_score"].notna().any():
                st.subheader("🎯 Docking Score Analysis")
                
                docked_with_scores = df[df["docking_score"].notna()]
                if not docked_with_scores.empty:
                    # Create two columns for different visualizations
                    viz_col1, viz_col2 = st.columns(2)
                    
                    with viz_col1:
                        # Histogram of docking scores
                        fig_hist = px.histogram(
                            docked_with_scores,
                            x="docking_score",
                            nbins=20,
                            title="Distribution of Docking Scores (Lower = Better)",
                            color_discrete_sequence=["#4287f5"],
                            labels={"docking_score": "Docking Score (lower=better)", "count": "Number of Compounds"}
                        )
                        fig_hist.update_layout(bargap=0.1)
                        st.plotly_chart(fig_hist, use_container_width=True)
                    
                    with viz_col2:
                        # Box plot by round if multiple rounds exist
                        if "round" in docked_with_scores.columns and len(docked_with_scores["round"].unique()) > 1:
                            fig_box = px.box(
                                docked_with_scores,
                                x="round",
                                y="docking_score",
                                title="Docking Scores by Round",
                                color_discrete_sequence=["#ff6b6b"]
                            )
                            fig_box.update_layout(
                                xaxis_title="Round",
                                yaxis_title="Docking Score"
                            )
                            st.plotly_chart(fig_box, use_container_width=True)
                        else:
                            # Show summary statistics instead
                            st.markdown("**Summary Statistics:**")
                            stats = docked_with_scores["docking_score"].describe()
                            stats_df = pd.DataFrame({
                                "Statistic": ["Count", "Mean", "Std", "Min", "25%", "50%", "75%", "Max"],
                                "Value": [
                                    f"{stats['count']:.0f}",
                                    f"{stats['mean']:.2f}",
                                    f"{stats['std']:.2f}",
                                    f"{stats['min']:.2f}",
                                    f"{stats['25%']:.2f}",
                                    f"{stats['50%']:.2f}",
                                    f"{stats['75%']:.2f}",
                                    f"{stats['max']:.2f}"
                                ]
                            })
                            st.dataframe(stats_df, use_container_width=True, hide_index=True)
                
                # Show top performers (lowest/best scores)
                st.markdown("**🏆 Top 10 Docking Performers (Lowest/Best Scores):**")
                top_performers = docked_with_scores.nsmallest(10, "docking_score")
                display_cols = ["compound_id", "docking_score", "round"]
                if "variant_id" in top_performers.columns:
                    display_cols.insert(1, "variant_id")
                if "barcode" in top_performers.columns:
                    display_cols.insert(2, "barcode")
                
                existing_cols = [col for col in display_cols if col in top_performers.columns]
                st.dataframe(
                    top_performers[existing_cols],
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No compounds with docking scores are available yet.")
                
            # Combined Analysis Section - Show correlation if both affinity and docking data exist
            if ("affinity_pred_value" in df.columns and df["affinity_pred_value"].notna().any() and
                "docking_score" in df.columns and df["docking_score"].notna().any()):
                
                st.subheader("🔬 Combined Affinity vs Docking Analysis")
                
                # Get compounds that have both affinity and docking data
                combined_data = df[
                    df["affinity_pred_value"].notna() & 
                    df["docking_score"].notna()
                ]
                
                if not combined_data.empty:
                    # Create correlation plot
                    fig_corr = px.scatter(
                        combined_data,
                        x="docking_score",
                        y="affinity_pred_value",
                        color="affinity_probability_binary" if "affinity_probability_binary" in combined_data.columns else None,
                        title="Docking Score vs IC50 Prediction (Both Lower = Better)",
                        hover_data=["compound_id", "barcode"] if "barcode" in combined_data.columns else ["compound_id"],
                        labels={
                            "docking_score": "Docking Score (lower=better)",
                            "affinity_pred_value": "IC50 Prediction (μM, lower=better)",
                            "affinity_probability_binary": "Affinity Probability"
                        }
                    )
                    st.plotly_chart(fig_corr, use_container_width=True)
                    
                    # Show correlation coefficient
                    correlation = combined_data["docking_score"].corr(combined_data["affinity_pred_value"])
                    st.info(f"Correlation between docking score and IC50: {correlation:.3f} (positive correlation means both values tend to move together)")
                    
                    # Show top combined performers
                    st.markdown("**🎯 Best Combined Performance (Low IC50 + Low Docking Score):**")
                    # Normalize scores for ranking (lower values are better for both)
                    combined_data_normalized = combined_data.copy()
                    combined_data_normalized["docking_score_norm"] = (
                        (combined_data["docking_score"].max() - combined_data["docking_score"]) / 
                        (combined_data["docking_score"].max() - combined_data["docking_score"].min())
                    )
                    combined_data_normalized["affinity_norm"] = (
                        (combined_data["affinity_pred_value"].max() - combined_data["affinity_pred_value"]) / 
                        (combined_data["affinity_pred_value"].max() - combined_data["affinity_pred_value"].min())
                    )
                    combined_data_normalized["combined_score"] = (
                        combined_data_normalized["docking_score_norm"] + 
                        combined_data_normalized["affinity_norm"]
                    ) / 2
                    
                    top_combined = combined_data_normalized.nlargest(10, "combined_score")
                    combined_display_cols = ["compound_id", "docking_score", "affinity_pred_value", "combined_score"]
                    if "variant_id" in top_combined.columns:
                        combined_display_cols.insert(1, "variant_id")
                    if "barcode" in top_combined.columns:
                        combined_display_cols.insert(2, "barcode")
                    
                    existing_combined_cols = [col for col in combined_display_cols if col in top_combined.columns]
                    st.dataframe(
                        top_combined[existing_combined_cols].round(3),
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("No compounds have both affinity and docking data for correlation analysis.")

        elif st.session_state.selected_view == "Compounds":
            st.header("Generated Compounds")
            
            # Check if we have any compounds at all
            if "status" not in df.columns or not any(status for status in df["status"].unique() if status == "GENERATED"):
                st.info("No compounds have been generated yet. This tab will populate when compound generation completes.")
            else:
                # Enhanced filter controls
                filter_col1, filter_col2, filter_col3 = st.columns([2, 1, 1])
                with filter_col1:
                    round_options_compounds = sorted([r for r in df["round"].unique() if pd.notna(r)])
                    selected_rounds = st.multiselect(
                        "Filter by Round",
                        options=round_options_compounds,
                        default=round_options_compounds,
                        key="compounds_rounds"
                    )
                with filter_col2:
                    sort_options = ["compound_id", "generation"]
                    if "round" in df.columns:
                        sort_options.insert(1, "round")
                    
                    sort_by = st.selectbox(
                        "Sort by",
                        options=sort_options,
                        index=0,
                        key="compounds_sort"
                    )
                with filter_col3:
                    sort_order = st.radio(
                        "Order",
                        options=["Ascending", "Descending"],
                        horizontal=True,
                        key="compounds_order"
                    )
                
                # Filter and sort compounds
                try:
                    # First filter by status
                    compounds_df = df[df["status"] == "GENERATED"]
                    
                    # Then apply round filter if selected
                    if selected_rounds:
                        compounds_df = compounds_df[compounds_df["round"].isin(selected_rounds)]
                    
                    # Apply sorting if the column exists
                    if sort_by in compounds_df.columns:
                        ascending = sort_order == "Ascending"
                        compounds_df = compounds_df.sort_values(sort_by, ascending=ascending)
                except Exception as e:
                    st.error(f"Error filtering compounds: {e}")
                    compounds_df = pd.DataFrame()
                
                # Display count
                st.info(f"Displaying {len(compounds_df)} compounds")
                
                if compounds_df.empty:
                    st.warning("No compounds match the current filter criteria. Try adjusting the filters.")
                else:
                    # Determine which columns to display
                    display_columns = ["compound_id"]
                    if "barcode" in compounds_df.columns:
                        display_columns.append("barcode")
                    if "round" in compounds_df.columns:
                        display_columns.append("round")
                    if "generation" in compounds_df.columns:
                        display_columns.append("generation")
                    display_columns.append("smiles")
                    
                    # Only include columns that exist
                    existing_columns = [col for col in display_columns if col in compounds_df.columns]
                    
                    # First show the dataframe
                    st.dataframe(
                        compounds_df[existing_columns],
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Add download button for this filtered view
                    if not compounds_df.empty:
                        st.download_button(
                            "Download Filtered Compounds",
                            data=compounds_df.to_csv(index=False).encode('utf-8'),
                            file_name="filtered_compounds.csv",
                            mime="text/csv"
                        )
                        
        elif st.session_state.selected_view == "Variants":
            st.header("Synthesized Variants")
            
            # Check if we have any variants at all
            if "status" in df.columns and not any(status for status in df["status"].unique() if status in ["SYNTHETIZED", "PASSFILTER", "PASSBLINDDOCK"]):
                st.info("No variants have been synthesized yet. This tab will populate when retrosynthesis completes.")
                
                # Show what stages have been reached
                available_statuses = df["status"].unique() if "status" in df.columns else []
                if "GENERATED" in available_statuses:
                    st.success("✅ Compounds have been generated")
                    st.info("⏳ Waiting for retrosynthesis to complete")
            else:
                # Enhanced filter controls
                filter_col1, filter_col2, filter_col3 = st.columns(3)
                with filter_col1:
                    status_options = sorted([
                        s
                        for s in df["status"].unique()
                        if pd.notna(s)
                        and s
                        in [
                            "SYNTHETIZED",
                            "PASSFILTER",
                            "PASSBLINDDOCK",
                            "DOCKED",
                        ]
                    ])
                    default_status = [s for s in status_options if s in ["SYNTHETIZED", "PASSFILTER"]]
                    selected_status = st.multiselect(
                        "Filter by Status",
                        options=status_options,
                        default=default_status if default_status else status_options,
                        key="variants_status"
                    )
                with filter_col2:
                    round_options_var = sorted([r for r in df["round"].unique() if pd.notna(r)])
                    selected_rounds_var = st.multiselect(
                        "Filter by Round",
                        options=round_options_var,
                        default=round_options_var,
                        key="variants_rounds"
                    )
                with filter_col3:
                    if "score" in df.columns and df["score"].notna().any():
                        valid_scores = df["score"].dropna()
                        if not valid_scores.empty:
                            min_score, max_score = float(valid_scores.min()), float(valid_scores.max())
                        else:
                            min_score, max_score = 0.0, 1.0
                            
                        score_range = st.slider(
                            "Score Range",
                            min_value=min_score,
                            max_value=max_score,
                            value=(min_score, max_score),
                            key="variants_score"
                        )
                        score_filter = (df["score"] >= score_range[0]) & (df["score"] <= score_range[1])
                    else:
                        score_filter = pd.Series(True, index=df.index)
                        if "score" not in df.columns:
                            st.info("No score data available in variants")
                
                # Add sorting options
                sort_col1, sort_col2 = st.columns(2)
                with sort_col1:
                    sort_options = ["variant_id", "round", "generation"]
                    if "score" in df.columns:
                        sort_options.append("score")
                        
                    sort_by_var = st.selectbox(
                        "Sort by",
                        options=sort_options,
                        index=0,
                        key="variants_sort"
                    )
                with sort_col2:
                    sort_order_var = st.radio(
                        "Order",
                        options=["Ascending", "Descending"],
                        horizontal=True,
                        key="variants_order"
                    )
                
                # Filter and display variants
                try:
                    if selected_status and selected_rounds_var:
                        variants_df = df[
                            (df["status"].isin(selected_status)) &
                            (df["round"].isin(selected_rounds_var))
                        ]
                        # Apply score filter if it exists
                        if "score" in df.columns:
                            variants_df = variants_df[score_filter]
                            
                        # Sort values if possible
                        if sort_by_var in variants_df.columns:
                            ascending_var = sort_order_var == "Ascending"
                            variants_df = variants_df.sort_values(sort_by_var, ascending=ascending_var)
                    else:
                        variants_df = pd.DataFrame()
                except Exception as e:
                    st.error(f"Error filtering variants: {e}")
                    variants_df = pd.DataFrame()
                
                # Display count
                st.info(f"Displaying {len(variants_df)} variants")
                
                if variants_df.empty:
                    st.warning("No variants match the current filter criteria. Try adjusting the filters.")
                else:
                    # Show the dataframe with columns that exist
                    display_columns = ["variant_id", "round", "generation", "status", "smiles"]
                    if "parent_id" in variants_df.columns:
                        display_columns.insert(1, "parent_id")
                    if "score" in variants_df.columns:
                        display_columns.insert(-1, "score")
                    
                    # Only include columns that exist
                    existing_columns = [col for col in display_columns if col in variants_df.columns]
                    
                    st.dataframe(
                        variants_df[existing_columns],
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Add download button for this filtered view
                    if not variants_df.empty:
                        st.download_button(
                            "Download Filtered Variants",
                            data=variants_df.to_csv(index=False).encode('utf-8'),
                            file_name="filtered_variants.csv",
                            mime="text/csv"
                        )
                        
        elif st.session_state.selected_view == "Docking Results":
            st.header("Docking Results")
            
            if "docking_score" not in df.columns or df["docking_score"].notna().sum() == 0:
                st.info("No docking scores available in the tracking report yet. This tab will populate when docking completes.")
                
                # Show what stages have been reached
                if "status" in df.columns:
                    available_statuses = df["status"].unique()
                    if "GENERATED" in available_statuses:
                        st.success("✅ Compounds have been generated")
                    if "SYNTHETIZED" in available_statuses:
                        st.success("✅ Variants have been synthesized")
                    if "PASSFILTER" in available_statuses:
                        st.success("✅ Variants have been filtered")
                    if "DOCKED" not in available_statuses:
                        st.warning("⏳ Docking has not yet completed")
            else:
                # Enhanced filter controls for docking
                filter_col1, filter_col2 = st.columns(2)
                with filter_col1:
                    round_options_dock = sorted([r for r in df["round"].unique() if pd.notna(r)])
                    selected_rounds_dock = st.multiselect(
                        "Filter by Round",
                        options=round_options_dock,
                        default=round_options_dock,
                        key="docking_rounds"
                    )
                with filter_col2:
                    valid_scores = df["docking_score"].dropna()
                    if valid_scores.empty:
                        st.info("No valid docking scores found to create a filter range.")
                        score_min_filter = score_max_filter = 0.0
                        score_range_dock = None
                    else:
                        min_score, max_score = float(valid_scores.min()), float(valid_scores.max())
                        if min_score == max_score:
                            st.info(f"All filtered compounds have a docking score of {min_score:.2f}.")
                            score_min_filter = score_max_filter = min_score
                            score_range_dock = None
                        else:
                            score_range_dock = st.slider(
                                "Docking Score Range",
                                min_value=min_score,
                                max_value=max_score,
                                value=(min_score, max_score),
                                key="docking_score_range",
                            )
                            score_min_filter, score_max_filter = score_range_dock

                # Filter docked compounds
                try:
                    # Base filter for status and round
                    docked_df = df[
                        (df["status"] == "DOCKED") &
                        (df["round"].isin(selected_rounds_dock))
                    ]
                    # Apply score filter only if there are valid scores
                    if not valid_scores.empty:
                         docked_df = docked_df[
                             (docked_df["docking_score"] >= score_min_filter) &
                             (docked_df["docking_score"] <= score_max_filter)
                         ]
                     
                    # Sort the final filtered df
                    docked_df = docked_df.sort_values("docking_score")

                except Exception as e:
                    st.error(f"Error filtering docked compounds: {e}")
                
                if docked_df.empty:
                    st.info("No docked compounds match the current filter criteria.")
                else:
                    # Docking statistics (lower scores are better)
                    stats_cols = st.columns(4)
                    with stats_cols[0]:
                        st.metric("Best Score (lower=better)", f"{docked_df['docking_score'].min():.2f}")
                    with stats_cols[1]:
                        st.metric("Average Score", f"{docked_df['docking_score'].mean():.2f}")
                    with stats_cols[2]:
                        st.metric("Median Score", f"{docked_df['docking_score'].median():.2f}")
                    with stats_cols[3]:
                        st.metric("Total Docked", len(docked_df))
                        
                    # Score distribution
                    st.subheader("Score Distribution (Lower = Better)")
                    try:
                        fig = px.scatter(
                            docked_df,
                            x="round",
                            y="docking_score",
                            color="docking_score",
                            hover_data=["compound_id", "smiles"],
                            title="Docking Scores by Round (Lower = Better)",
                            color_continuous_scale="viridis_r",  # Reverse scale so lower values are brighter
                            labels={"docking_score": "Docking Score (lower=better)"}
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    except Exception as e:
                        st.error(f"Error creating score distribution plot: {e}")
                    
                    # Full docking results table
                    st.subheader("All Docking Results")
                    # Ensure required columns exist
                    table_columns = ["compound_id", "round", "docking_score", "status", "smiles"]
                    if "variant_id" in docked_df.columns:
                        table_columns.insert(1, "variant_id")
                    if "barcode" in docked_df.columns:
                        table_columns.insert(2, "barcode")
                    if "pose_count" in docked_df.columns:
                        table_columns.insert(-1, "pose_count")
                    if "all_scores" in docked_df.columns:
                        table_columns.insert(-1, "all_scores")
                        
                    # Only include columns that exist
                    existing_columns = [col for col in table_columns if col in docked_df.columns]
                    
                    st.dataframe(
                        docked_df[existing_columns],
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Add download button for this filtered view
                    col1, col2 = st.columns(2)
                    with col1:
                        st.download_button(
                            "Download Filtered Docking Results",
                            data=docked_df.to_csv(index=False).encode('utf-8'),
                            file_name="filtered_docking_results.csv",
                            mime="text/csv"
                        )
                    with col2:
                        # Add option to view 3D structures for selected compounds
                        if st.button("🧬 View 3D Structures", help="View 3D molecular structures for top results"):
                            st.session_state.show_3d_structures = True

                    # 3D Structure Viewer Section
                    if st.session_state.get('show_3d_structures', False):
                        st.subheader("🧬 3D Molecular Structures")
                        
                        # Allow user to select which compounds to visualize
                        st.markdown("Select compounds to visualize in 3D:")
                        
                        # Create a selection interface
                        top_10_results = docked_df.head(10)
                        
                        selected_indices = []
                        for idx, result in top_10_results.iterrows():
                            variant_id = result.get('variant_id', result.get('compound_id', 'Unknown'))
                            score = result.get('docking_score', 0)
                            
                            if st.checkbox(f"{variant_id} (Score: {score:.2f})", key=f"3d_select_{variant_id}"):
                                selected_indices.append(idx)
                        
                        # Display 3D structures for selected compounds
                        if selected_indices:
                            for idx in selected_indices:
                                result = docked_df.loc[idx]
                                variant_id = result.get('variant_id', result.get('compound_id', 'Unknown'))
                                
                                st.markdown(f"### 🎯 {variant_id}")
                                create_interactive_3d_viewer(result, output_dir_path)
                                st.divider()
                        else:
                            st.info("Select compounds above to view their 3D structures")
                        
                        # Add button to hide 3D structures
                        if st.button("Hide 3D Structures"):
                            st.session_state.show_3d_structures = False
                            st.rerun()
                    
                    # Detailed docking results with 3D visualization
                    st.subheader("Top Docking Results with 3D Visualization")
                    
                    # Show top 5 results with detailed information
                    top_results = docked_df.head(5)
                    
                    for idx, result in top_results.iterrows():
                        variant_id = result.get('variant_id', result.get('compound_id', 'Unknown'))
                        barcode = result.get('barcode', 'Unknown')
                        
                        with st.expander(f"🏆 {variant_id} - Score: {result.get('docking_score', 0):.2f}"):
                            col1, col2 = st.columns([1, 2])
                            
                            with col1:
                                # Render 2D structure
                                if "smiles" in result and not pd.isna(result["smiles"]):
                                    mol_img = render_mol(result["smiles"])
                                    if mol_img:
                                        st.image(mol_img, caption="2D Structure", use_container_width=True)
                                
                                # Show Boltz-2 affinity predictions
                                if "affinity_pred_value" in result and not pd.isna(result["affinity_pred_value"]):
                                    st.markdown("**🤖 Boltz-2 Predictions:**")
                                    affinity_data = {
                                        "IC50": f"{result['affinity_pred_value']:.3f} μM",
                                    }
                                    if "affinity_probability_binary" in result and not pd.isna(result["affinity_probability_binary"]):
                                        prob_val = result["affinity_probability_binary"]
                                        confidence_text = "High" if prob_val > 0.5 else "Low"
                                        affinity_data["Affinity Confidence"] = f"{prob_val:.3f} ({confidence_text})"
                                    if "confidence_score" in result and not pd.isna(result["confidence_score"]):
                                        affinity_data["Overall Confidence"] = f"{result['confidence_score']:.3f}"
                                    
                                    for key, value in affinity_data.items():
                                        st.write(f"**{key}:** {value}")
                                    
                                    st.divider()
                                
                                # Show docking statistics
                                st.markdown("**🎯 Docking Statistics:**")
                                stats_data = {
                                    "Score": f"{result.get('docking_score', 'N/A'):.2f}" if pd.notna(result.get('docking_score')) else "N/A",
                                    "Poses": result.get('pose_count', 'N/A'),
                                    "Round": result.get('round', 'N/A'),
                                    "Status": result.get('status', 'N/A')
                                }
                                
                                if "all_scores" in result and not pd.isna(result["all_scores"]):
                                    try:
                                        # Parse all_scores if it's a string representation of a list
                                        all_scores_str = str(result["all_scores"])
                                        if all_scores_str.startswith('[') and all_scores_str.endswith(']'):
                                            import ast
                                            all_scores = ast.literal_eval(all_scores_str)
                                            if len(all_scores) > 1:
                                                stats_data["Score Range"] = f"{min(all_scores):.2f} to {max(all_scores):.2f}"
                                    except:
                                        pass
                                
                                for key, value in stats_data.items():
                                    st.write(f"**{key}:** {value}")
                            
                            with col2:
                                # Create comprehensive 3D visualization
                                create_interactive_3d_viewer(result, output_dir_path)

else:
    # No results data available
    st.info("No results data available. The pipeline may still be initializing.")
    
    # Check if there's a log file we can show
    if output_dir_path:
        log_file = output_dir_path / "logs" / "quick_pipeline.log"
        if log_file.exists():
            st.subheader("Pipeline Log")
            try:
                with open(log_file, 'r') as f:
                    log_content = f.read()
                
                # Show the last 30 lines of the log
                log_lines = log_content.splitlines()
                if len(log_lines) > 30:
                    recent_logs = "\n".join(log_lines[-30:])
                else:
                    recent_logs = log_content
                
                create_auto_scrolling_text_area(recent_logs)
                
                # Add auto-refresh option
                st.session_state.auto_refresh = st.checkbox(
                    "Auto-refresh data (every 30 seconds)",
                    value=st.session_state.auto_refresh,
                    key="auto_refresh_no_results"
                )
                
                if st.session_state.auto_refresh:
                    auto_refresh_js = """
                    <script>
                        setTimeout(function(){
                            document.querySelector("button[kind=secondaryFormSubmit]").click();
                        }, 30000);
                    </script>
                    """
                    st.markdown(auto_refresh_js, unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Error reading log file: {e}")
        else:
            st.warning("No log file found. Please run the pipeline to generate results.")
    else:
        st.warning("Output directory not specified. Please configure and run the pipeline.")

# Export options
st.divider()
st.subheader("Export Options")
export_col1, export_col2, export_col3 = st.columns(3)

with export_col1:
    if st.button("Export All Results") and st.session_state.results is not None and st.session_state.results["tracking_report"] is not None:
        st.download_button(
            "📥 Download Complete Dataset",
            data=st.session_state.results["tracking_report"].to_csv(index=False).encode('utf-8'),
            file_name="all_results.csv",
            mime="text/csv"
        )

with export_col2:
    if (st.button("Export Docking Results") and st.session_state.results is not None 
        and st.session_state.results["tracking_report"] is not None 
        and "docking_score" in st.session_state.results["tracking_report"].columns):
        
        docked_df = st.session_state.results["tracking_report"][
            st.session_state.results["tracking_report"]["status"] == "DOCKED"
        ]
        st.download_button(
            "📥 Download Docking Results",
            data=docked_df.to_csv(index=False).encode('utf-8'),
            file_name="docking_results.csv",
            mime="text/csv"
        )

with export_col3:
    if st.button("Export Summary Statistics") and st.session_state.results is not None and st.session_state.results["tracking_report"] is not None:
        df = st.session_state.results["tracking_report"]
        stats = {
            "total_compounds": len(df[df["status"] == "GENERATED"]),
            "total_variants": len(df[df["status"] == "SYNTHETIZED"]),
            "filtered_variants": len(df[df["status"] == "PASSFILTER"]),
            "docked_compounds": len(df[df["status"] == "DOCKED"]),
            }
        
        if "docking_score" in df.columns and df["docking_score"].notna().any():
            stats["average_docking_score"] = float(df[df["docking_score"].notna()]["docking_score"].mean())
            stats["best_docking_score"] = float(df[df["docking_score"].notna()]["docking_score"].min())
        
        if "affinity_pred_value" in df.columns and df["affinity_pred_value"].notna().any():
            stats["average_ic50_uM"] = float(df[df["affinity_pred_value"].notna()]["affinity_pred_value"].mean())
            stats["best_ic50_uM"] = float(df[df["affinity_pred_value"].notna()]["affinity_pred_value"].min())  # Lower is better
            if "affinity_probability_binary" in df.columns:
                high_conf_count = len(df[df["affinity_probability_binary"] > 0.5])
                stats["high_confidence_ic50_predictions"] = high_conf_count
        
        st.json(stats) 