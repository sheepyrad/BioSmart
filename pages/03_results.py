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
        ligand_file: Path to ligand structure file (PDBQT or PDB)
        receptor_file: Optional path to receptor structure file (PDBQT or PDB)
    
    Returns:
        py3Dmol view object
    """
    view = py3Dmol.view(width=800, height=600)
    
    try:
        # Add ligand
        with open(ligand_file) as f:
            ligand_data = f.read()
        
        # Determine file format for py3Dmol
        ligand_format = 'pdb'  # Default format
        if str(ligand_file).lower().endswith('.pdbqt'):
            ligand_format = 'pdbqt'
        
        # Add ligand model with proper format
        view.addModel(ligand_data, ligand_format)
        view.setStyle({'model': 0}, {'stick': {'colorscheme': 'greenCarbon', 'radius': 0.2}})
        
        # Add receptor if provided
        if receptor_file and Path(receptor_file).exists():
            with open(receptor_file) as f:
                receptor_data = f.read()
            
            # Determine format for receptor
            receptor_format = 'pdb'  # Default format
            if str(receptor_file).lower().endswith('.pdbqt'):
                receptor_format = 'pdbqt'
            
            # Add receptor as separate model
            view.addModel(receptor_data, receptor_format)
            view.setStyle({'model': 1}, {'cartoon': {'color': 'spectrum'}, 'line': {'colorscheme': 'whiteCarbon'}})
        
        # Set view options
        view.zoomTo()
        view.setBackgroundColor('white')
        
        # Enable surface representation for binding pocket visualization
        if receptor_file:
            view.addSurface(py3Dmol.VDW, {'opacity': 0.7, 'color':'white'}, {'model': 1})
        
        return view
    
    except Exception as e:
        st.error(f"Error rendering 3D structure: {e}")
        return None

# Function to create downloadable link
def get_download_link(df, filename, text):
    """Create a download link for a dataframe"""
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    href = f'<a href="data:file/csv;base64,{b64}" download="{filename}">{text}</a>'
    return href

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
                            value=st.session_state.auto_refresh
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
                                value=st.session_state.auto_refresh
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
            value=st.session_state.auto_refresh
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
        if st.session_state.selected_view == "Summary":
            st.header("Pipeline Summary")
            
            # Determine what pipeline stages have been reached
            available_statuses = df["status"].unique() if "status" in df.columns else []
            
            # Summary metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                compound_count = len(df[df["status"] == "GENERATED"]) if "status" in df.columns else 0
                st.metric("Total Compounds", compound_count)
            with col2:
                variant_count = len(df[df["status"] == "SYNTHETIZED"]) if "status" in df.columns else 0
                st.metric("Total Variants", variant_count)
            with col3:
                filtered_count = len(df[df["status"] == "PASSFILTER"]) if "status" in df.columns else 0
                st.metric("Filtered Variants", filtered_count)
            with col4:
                docked_count = len(df[df["status"] == "DOCKED"]) if "status" in df.columns else 0
                st.metric("Docked Compounds", docked_count)
            
            # Show pipeline progress information
            progress_message = ""
            if "GENERATED" in available_statuses and "SYNTHETIZED" not in available_statuses:
                progress_message = "Pipeline has generated compounds but not yet completed retrosynthesis."
            elif "SYNTHETIZED" in available_statuses and "PASSFILTER" not in available_statuses:
                progress_message = "Pipeline has generated variants but not yet completed filtering."
            elif "PASSFILTER" in available_statuses and "DOCKED" not in available_statuses:
                progress_message = "Pipeline has filtered variants but not yet completed docking."
            
            if progress_message:
                st.info(progress_message + " Some visualizations may not be available until those steps complete.")
            
            # Docking score distribution if available
            if "docking_score" in df.columns and df["docking_score"].notna().any():
                st.subheader("Docking Score Distribution")
                
                # Just show regular histogram if only one type exists or if data is available
                docked_with_scores = df[df["docking_score"].notna()]
                if not docked_with_scores.empty:
                    fig = px.histogram(
                        docked_with_scores,
                        x="docking_score",
                        nbins=20,
                        title="Distribution of Docking Scores",
                        color_discrete_sequence=["#4287f5"]
                    )
                    fig.update_layout(bargap=0.1)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No compounds with docking scores are available yet.")
            else:
                st.info("No docking scores available in the tracking report. This section will populate when docking completes.")
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
            if "status" in df.columns and not any(status for status in df["status"].unique() if status in ["SYNTHETIZED", "PASSFILTER"]):
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
                    status_options = sorted([s for s in df["status"].unique() if pd.notna(s) and s in ["SYNTHETIZED", "PASSFILTER", "DOCKED"]])
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
                    # Safely get min/max values
                    valid_scores = df["docking_score"].dropna() 
                    if not valid_scores.empty:
                        min_score, max_score = float(valid_scores.min()), float(valid_scores.max())
                    else:
                        min_score, max_score = 0.0, 0.0

                    # Decide whether to show slider or just info
                    if not valid_scores.empty and min_score == max_score:
                        st.info(f"All filtered compounds have a docking score of {min_score:.2f}.")
                        # Set filter bounds directly
                        score_min_filter = min_score
                        score_max_filter = max_score
                        # No slider needed
                        score_range_dock = None 
                    elif not valid_scores.empty:
                        # Scores differ, show the slider
                        # Add check to prevent min_value >= max_value for slider widget itself
                        display_max_score = max_score
                        if min_score >= max_score:
                             epsilon = 0.1 
                             display_max_score = min_score + epsilon 
                             # Adjust the default value tuple as well if max_score was changed
                             default_value = (min_score, display_max_score)
                        else:
                            # Default value uses the original min/max if they were valid
                            default_value = (min_score, max_score)

                        score_range_dock = st.slider(
                            "Docking Score Range",
                            min_value=min_score,
                            max_value=display_max_score, # Use potentially adjusted max_score for display
                            value=default_value, # Use potentially adjusted default value
                            key="docking_score_range"
                        )
                        # Get filter bounds from slider value
                        score_min_filter = score_range_dock[0]
                        score_max_filter = score_range_dock[1]
                    else:
                         # No valid scores, maybe show info or disable filtering?
                         st.info("No valid docking scores found to create a filter range.")
                         score_min_filter = 0.0
                         score_max_filter = 0.0
                         score_range_dock = None # Indicate no slider/range

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
                    # Docking statistics
                    stats_cols = st.columns(4)
                    with stats_cols[0]:
                        st.metric("Best Score", f"{docked_df['docking_score'].min():.2f}")
                    with stats_cols[1]:
                        st.metric("Average Score", f"{docked_df['docking_score'].mean():.2f}")
                    with stats_cols[2]:
                        st.metric("Median Score", f"{docked_df['docking_score'].median():.2f}")
                    with stats_cols[3]:
                        st.metric("Total Docked", len(docked_df))
                    
                    # Score distribution
                    st.subheader("Score Distribution")
                    try:
                        fig = px.scatter(
                            docked_df,
                            x="round",
                            y="docking_score",
                            color="docking_score",
                            hover_data=["compound_id", "smiles"],
                            title="Docking Scores by Round",
                            color_continuous_scale="viridis"
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
                        
                    # Only include columns that exist
                    existing_columns = [col for col in table_columns if col in docked_df.columns]
                    
                    st.dataframe(
                        docked_df[existing_columns],
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Add download button for this filtered view
                    st.download_button(
                        "Download Filtered Docking Results",
                        data=docked_df.to_csv(index=False).encode('utf-8'),
                        file_name="filtered_docking_results.csv",
                        mime="text/csv"
                    )

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
                    value=st.session_state.auto_refresh
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
        
        st.json(stats) 