import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import base64
import json
import streamlit.components.v1 as components


def create_auto_scrolling_text_area(content, height=400):
    """Create an auto-scrolling text area using HTML and JavaScript with syntax highlighting"""
    # Escape HTML special characters
    content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    # Add syntax highlighting for common log patterns
    content = content.replace("ERROR", '<span style="color: #f56565;">ERROR</span>')
    content = content.replace("WARNING", '<span style="color: #ed8936;">WARNING</span>')
    content = content.replace("INFO", '<span style="color: #48bb78;">INFO</span>')
    content = content.replace("DEBUG", '<span style="color: #63b3ed;">DEBUG</span>')
    
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
        content = content.replace(stage, f'<span style="color: #ed8936;">{stage}</span>')
    
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
    
    # Try DuckDB first
    duckdb_path = output_dir / "pipeline.duckdb"
    if duckdb_path.exists():
        try:
            from utils.duckdb_store import DuckDBStore
            store = DuckDBStore(duckdb_path)
            results["tracking_report"] = store.get_all_tracking_data()
            st.success("Successfully loaded tracking report from DuckDB.")
            return results
        except Exception as e:
            st.warning(f"Could not read from DuckDB ({duckdb_path}): {e}. Falling back to CSV.")
    
    # Fallback to CSV
    tracking_file = output_dir / "master_tracking" / "master_compound_tracking_report.csv"
    
    if tracking_file.exists():
        try:
            results["tracking_report"] = pd.read_csv(tracking_file)
            st.success("Successfully loaded tracking report from CSV.")
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

# Function to create downloadable link
def get_download_link(df, filename, text):
    """Create a download link for a dataframe"""
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    href = f'<a href="data:file/csv;base64,{b64}" download="{filename}">{text}</a>'
    return href

# Page configuration
st.set_page_config(
    page_title="Live Pipeline Dashboard",
    page_icon="📊",
    layout="wide"
)

# Add custom CSS for consistent styling across both pages
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
    
    /* Dashboard-specific styling */
    .dashboard-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 1rem;
    }
    
    .metric-container {
        background: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border-left: 4px solid #667eea;
        color: #2c3e50;
    }
    
    .metric-container h4 {
        color: #34495e;
        margin: 0 0 0.5rem 0;
        font-size: 1rem;
        font-weight: 600;
    }
    
    .metric-container h2 {
        margin: 0.5rem 0;
        font-size: 2rem;
        font-weight: bold;
    }
    
    .metric-container small {
        color: #7f8c8d;
        font-size: 0.875rem;
    }
    
    .status-indicator {
        display: inline-block;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        margin-right: 8px;
    }
    
    .status-running { background-color: #ffd93d; }
    .status-complete { background-color: #6bff6b; }
    .status-pending { background-color: #d3d3d3; }
    .status-error { background-color: #ff6b6b; }
    
    .pipeline-stage {
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
        transition: all 0.3s ease;
    }
    
    .pipeline-stage:hover {
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        transform: translateY(-2px);
    }
    
    .live-indicator {
        animation: pulse 2s infinite;
        color: #ff6b6b;
    }
    
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
    }
    
    <style>
    .metric-card {
        background: linear-gradient(90deg, #4a5568 0%, #2d3748 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin: 0.5rem 0;
    }
    .info-card {
        border-left: 4px solid #4a5568;
        color: #e2e8f0;
        padding: 1rem;
        margin: 1rem 0;
    }
    .info-card h3 {
        color: #e2e8f0;
        margin-top: 0;
    }
    .info-card p {
        margin-bottom: 0;
    }
    .small-text {
        font-size: 0.9em;
        color: #a0aec0;
    }
    .status-running { background-color: #ed8936; }
    .status-complete { background-color: #48bb78; }
    .status-pending { background-color: #4a5568; }
    .status-error { background-color: #f56565; }
    
    .log-container {
        background: #1a202c;
        border: 1px solid #4a5568;
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .error-message {
        color: #f56565;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

# Initialize session state variables
if "results" not in st.session_state:
    st.session_state.results = None

if "pipeline_config" not in st.session_state:
    st.session_state.pipeline_config = None


# Add a refresh flag to enable auto-refreshing for ongoing pipelines
if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = False

# Header with live indicator
st.markdown("""
    <div class="dashboard-header">
        <h1>📊 Live Pipeline Dashboard <span class="live-indicator">●</span></h1>
        <p>Real-time monitoring of your active pipeline run</p>
    </div>
""", unsafe_allow_html=True)

# Add information about dashboard capabilities
with st.expander("🔧 Dashboard Features", expanded=False):
    st.markdown("""
    **Live Monitoring Capabilities:**
    
    🔄 **Real-time Updates**
    - Auto-refresh functionality for live data streaming
    - Pipeline progress tracking with visual indicators
    - Live log monitoring with syntax highlighting
    
    📊 **Interactive Visualizations**
    - Dynamic charts that update as data arrives
    - Multi-dimensional plotting and correlation analysis
    
    🎯 **Pipeline Stages Tracking**
    - Generation → Retrosynthesis → Filtering → Docking
    - Status indicators for each stage
    - Estimated completion times
    
    **📈 Advanced Analytics:**
    - Boltz-2 affinity predictions (IC50 values)
    - Docking score distributions
    - Combined affinity vs docking analysis
    
    """)

# Check if configuration exists
if not st.session_state.pipeline_config:
    st.markdown("""
        <div style="text-align: center; padding: 2rem; background: #2d3748; border-radius: 10px; margin: 2rem 0; color: #ed8936;">
            <h3>🚀 No Active Pipeline Found</h3>
            <p>Please configure and run a pipeline first to start monitoring.</p>
            <p><strong>Next Steps:</strong> Go to the <strong>Configure & Run</strong> page to set up and launch a pipeline.</p>
        </div>
    """, unsafe_allow_html=True)
    st.stop()

# Get the output directory path
output_dir = Path(st.session_state.pipeline_config.get("out_dir", ""))
output_dir_path = Path(output_dir) if output_dir else None

# Validate output directory
if not output_dir_path or not output_dir_path.exists():
    st.markdown("""
        <div style="text-align: center; padding: 2rem; background: #1a202c; border-radius: 10px; margin: 2rem 0; color: #f56565;">
            <h3>❌ Output Directory Not Found</h3>
            <p>Output directory: <code>{}</code></p>
            <p>Please check if the pipeline has started running properly.</p>
        </div>
    """.format(output_dir_path), unsafe_allow_html=True)
    st.stop()

# Live Status Indicator
status_col1, status_col2, status_col3 = st.columns([1, 2, 1])
with status_col2:
    st.markdown("""
        <div style="text-align: center; padding: 1rem; background: #2d3748; border-radius: 8px; margin: 1rem 0; color: #63b3ed;">
            <h4>🔴 LIVE</h4>
            <p>Monitoring: <code>{}</code></p>
        </div>
    """.format(output_dir_path.name), unsafe_allow_html=True)

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

# Enhanced Sidebar for navigation
with st.sidebar:
    st.markdown("""
        <div style="text-align: center; padding: 1rem; background: linear-gradient(135deg, #4a5568 0%, #2d3748 100%); border-radius: 10px; color: white; margin-bottom: 1rem;">
            <h3>🔴 LIVE DASHBOARD</h3>
            <p style="margin: 0; font-size: 0.9em;">Real-time monitoring</p>
        </div>
    """, unsafe_allow_html=True)
    
    # Sidebar filtering options (global)
    st.subheader("🎛️ Global Filters")
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
        
        # Retrosynthesis Score Threshold filter
        st.divider()
        if "score" in df.columns:
            try:
                score_values = df["score"].dropna()
                if not score_values.empty:
                    min_score = float(score_values.min())
                    max_score = float(score_values.max())
                    default_threshold = min_score  # Default to minimum to show all
                    
                    retrosynthesis_threshold = st.slider(
                        "Retrosynthesis Score Threshold",
                        min_value=float(min_score),
                        max_value=float(max_score),
                        value=float(default_threshold),
                        step=0.01,
                        help="Filter variants by minimum retrosynthesis score. Only variants with scores >= this threshold will be shown.",
                        key="retrosynthesis_threshold"
                    )
                else:
                    st.info("No retrosynthesis scores available for filtering")
                    retrosynthesis_threshold = None
            except Exception as e:
                st.error(f"Error loading retrosynthesis score options: {e}")
                retrosynthesis_threshold = None
        else:
            st.info("Retrosynthesis score information not available for filtering")
            retrosynthesis_threshold = None
        
        # Apply global filters
        filtered_df = df.copy()
        
        # Apply round filter
        if sidebar_rounds and "round" in df.columns:
            try:
                filtered_df = filtered_df[filtered_df["round"].isin(sidebar_rounds)]
            except Exception as e:
                st.error(f"Error applying round filter: {e}")
        
        # Apply status filter
        if sidebar_status and "status" in df.columns:
            try:
                filtered_df = filtered_df[filtered_df["status"].isin(sidebar_status)]
            except Exception as e:
                st.error(f"Error applying status filter: {e}")
        
        # Apply retrosynthesis score threshold filter
        if retrosynthesis_threshold is not None and "score" in filtered_df.columns:
            try:
                # For rows with retrosynthesis scores, filter by threshold
                # For rows without scores (e.g., generated compounds), keep them
                score_mask = filtered_df["score"].isna() | (filtered_df["score"] >= retrosynthesis_threshold)
                filtered_df = filtered_df[score_mask]
            except Exception as e:
                st.error(f"Error applying retrosynthesis score filter: {e}")
        
        # Show filter summary
        if retrosynthesis_threshold is not None and "score" in df.columns:
            score_filtered_count = len(filtered_df[filtered_df["score"].notna()])
            total_with_scores = len(df[df["score"].notna()])
            if total_with_scores > 0:
                st.caption(f"📊 Showing {score_filtered_count} / {total_with_scores} variants with scores >= {retrosynthesis_threshold:.3f}")
        
        # Store filtered_df in session state for use in main content
        st.session_state.filtered_df = filtered_df
    else:
        # No results data available in sidebar, initialize filtered_df
        st.session_state.filtered_df = None
            
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
            
# Helper function to check if a status indicates progression to or beyond a stage
# Status progression: GENERATED -> SYNTHETIZED -> PASSFILTER/PASSBLINDDOCK -> DOCKED
def has_reached_stage(status_value, target_stage, include_failures=True):
    """Check if a status indicates the compound has reached the target stage or beyond
    
    Args:
        status_value: The status value to check
        target_stage: The target stage to check against
        include_failures: If True, FAIL statuses count as having reached the stage
                        (e.g., FAILSCORE counts as reached SYNTHETIZED)
                        If False, only PASS statuses count, BUT compounds that passed
                        earlier stages but failed later stages still count for the earlier stage
                        (e.g., FAILBLINDDOCK counts for PASSFILTER since it passed filter first)
    """
    if pd.isna(status_value):
        return False
    status_str = str(status_value).upper()
    stage_upper = target_stage.upper()
    
    # Define stage progression hierarchy
    # Higher numbers = further along in pipeline
    stage_hierarchy = {
        "GENERATED": 0,
        "SYNTHETIZED": 1,
        "PASSSCORE": 1,  # At same level as SYNTHETIZED
        "FAILSCORE": 1 if include_failures else -1,  # Reached synthesis but failed
        "PASSFILTER": 2,
        "CHEMAPPASS": 2,  # At same level as PASSFILTER
        "FAILFILTER": 2 if include_failures else -1,  # Reached filter but failed
        "PASSBLINDDOCK": 3,
        "FAILBLINDDOCK": 3,  # Failed Boltz but passed filter, so still counts for PASSFILTER
        "DOCKED": 4,
        "DOCKFAIL": 4,  # Failed docking but passed earlier stages
    }
    
    # Handle various BOLTZFAIL statuses - these indicate reached Boltz stage
    # If include_failures=False and checking for PASSFILTER, they should count
    # If include_failures=False and checking for PASSBLINDDOCK, they should not count
    if status_str.startswith("BOLTZFAIL"):
        if not include_failures:
            # If checking for PASSFILTER (level 2), BOLTZFAIL means they passed filter
            if stage_upper == "PASSFILTER":
                return True  # They reached Boltz, so they passed filter
            else:
                return False  # Failed, so don't count for PASSBLINDDOCK or DOCKED
        else:
            # Include failures, check normally
            current_level = 3  # BOLTZFAIL indicates reached level 3
            target_level = stage_hierarchy.get(stage_upper, -1)
            return current_level >= target_level
    
    current_level = stage_hierarchy.get(status_str, -1)
    target_level = stage_hierarchy.get(stage_upper, -1)
    
    # If current_level is -1 (unknown or excluded status), don't count
    if current_level == -1:
        return False
    
    # If include_failures=False, exclude FAIL statuses at the target level
    # (e.g., FAILFILTER shouldn't count for PASSFILTER, FAILBLINDDOCK shouldn't count for PASSBLINDDOCK)
    if not include_failures:
        fail_statuses = {
            "FAILSCORE": 1,
            "FAILFILTER": 2,
            "FAILBLINDDOCK": 3,
            "DOCKFAIL": 4
        }
        if status_str in fail_statuses and fail_statuses[status_str] == target_level:
            return False
    
    # Special handling: if include_failures=False, compounds that reached higher stages
    # should still count for lower target levels (they passed the lower stage)
    if not include_failures and current_level > target_level:
        # Compound reached a later stage (even if failed), so it must have passed the target stage
        return True
    
    return current_level >= target_level

# Helper function to count compounds that have reached a stage or beyond
def count_reached_stage(df, target_stage, include_failures=True):
    """Count compounds that have reached the target stage or beyond
    
    Args:
        df: DataFrame with status column
        target_stage: The target stage to count (e.g., "SYNTHETIZED", "PASSFILTER")
        include_failures: If True, FAIL statuses count as having reached the stage
                        (e.g., for variants count, FAILSCORE counts)
                        If False, only PASS statuses count (e.g., for filtered count)
    """
    if "status" not in df.columns:
        return 0
    return df["status"].apply(lambda s: has_reached_stage(s, target_stage, include_failures)).sum()

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
        # Define available_statuses for use across all views (use original df for this)
        available_statuses = df["status"].unique() if "status" in df.columns else []
                
        # Summary view only
        st.markdown("## 📊 Live Pipeline Overview")
        
        # Enhanced Summary metrics with styling
        st.markdown("### 🔢 Key Metrics")
        
        # Apply filters - use filtered_df from sidebar if available
        if 'filtered_df' in st.session_state and st.session_state.filtered_df is not None:
            filtered_df = st.session_state.filtered_df
        else:
            filtered_df = df.copy()
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            compound_count = len(filtered_df[filtered_df["status"] == "GENERATED"]) if "status" in filtered_df.columns else 0
            st.markdown(f"""
                <div class="metric-container">
                    <h4>🧬 Compounds</h4>
                    <h2 style="color: #48bb78; margin: 0;">{compound_count}</h2>
                    <small>Generated</small>
                </div>
            """, unsafe_allow_html=True)
        with col2:
            # Count variants: anything that has reached SYNTHETIZED or beyond (i.e., not GENERATED)
            variant_count = count_reached_stage(filtered_df, "SYNTHETIZED")
            st.markdown(f"""
                <div class="metric-container">
                    <h4>⚗️ Variants</h4>
                    <h2 style="color: #48bb78; margin: 0;">{variant_count}</h2>
                    <small>Synthesized</small>
                </div>
            """, unsafe_allow_html=True)
        with col3:
            # Count filtered: anything that has reached PASSFILTER or PASSBLINDDOCK or beyond
            # Exclude failures - only count compounds that actually passed filters
            filtered_count = count_reached_stage(filtered_df, "PASSFILTER", include_failures=False)
            st.markdown(f"""
                <div class="metric-container">
                    <h4>🔬 Filtered</h4>
                    <h2 style="color: #48bb78; margin: 0;">{filtered_count}</h2>
                    <small>Passed filters</small>
                </div>
            """, unsafe_allow_html=True)
        with col4:
            docked_count = len(filtered_df[filtered_df["status"] == "DOCKED"]) if "status" in filtered_df.columns else 0
            st.markdown(f"""
                <div class="metric-container">
                    <h4>🎯 Docked</h4>
                    <h2 style="color: #48bb78; margin: 0;">{docked_count}</h2>
                    <small>Completed</small>
                </div>
            """, unsafe_allow_html=True)
        with col5:
            # Show best docking score if available (lower is better)
            if "docking_score" in filtered_df.columns and filtered_df["docking_score"].notna().any():
                best_score = filtered_df[filtered_df["docking_score"].notna()]["docking_score"].min()
                score_text = f"{best_score:.2f}"
            else:
                score_text = "N/A"
            st.markdown(f"""
                <div class="metric-container">
                    <h4>🏆 Best Score</h4>
                    <h2 style="color: #48bb78; margin: 0;">{score_text}</h2>
                    <small>Lower = better</small>
                </div>
            """, unsafe_allow_html=True)
                    
        # Workflow Progress Visualization
        st.subheader("Workflow Progress")
        
        # Define workflow stages with their target statuses
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
                # Count compounds that have reached this stage or beyond
                # For filter stages (PASSFILTER, PASSBLINDDOCK), only count successes
                # For other stages, count all that reached (including failures)
                include_failures = status_key not in ["PASSFILTER", "PASSBLINDDOCK"]
                count = count_reached_stage(filtered_df, status_key, include_failures=include_failures)
                is_complete = count > 0
                
                if is_complete:
                    st.success(f"{emoji} {stage_name}")
                    st.write(f"**{count}** items")
                else:
                    st.info(f"{emoji} {stage_name}")
                    st.write("Pending")
        
        # Show detailed progress message based on actual counts
        has_generated = count_reached_stage(filtered_df, "GENERATED") > 0
        has_synthesized = count_reached_stage(filtered_df, "SYNTHETIZED", include_failures=True) > 0
        has_filtered = count_reached_stage(filtered_df, "PASSFILTER", include_failures=False) > 0
        has_docked = count_reached_stage(filtered_df, "DOCKED") > 0
        
        progress_message = ""
        if has_generated and not has_synthesized:
            progress_message = "Pipeline has generated compounds but not yet completed retrosynthesis."
        elif has_synthesized and not has_filtered:
            progress_message = "Pipeline has generated variants but not yet completed filtering."
        elif has_filtered and not has_docked:
            progress_message = "Pipeline has filtered variants but not yet completed docking."
        elif has_docked:
            progress_message = "Pipeline has completed all major stages successfully!"
        
        if progress_message:
            if "completed all major stages" in progress_message:
                st.success(progress_message)
            else:
                st.info(progress_message + " Some visualizations may not be available until those steps complete.")
        
        # Affinity Analysis Section
        if "affinity_pred_value1" in filtered_df.columns and filtered_df["affinity_pred_value1"].notna().any():
            st.subheader("🤖 Boltz-2 Affinity Analysis")
            
            # Add explanation of the two metrics
            with st.expander("📖 Understanding Boltz-2 Affinity Predictions", expanded=False):
                st.markdown("""
                    **Two Types of Predictions:**
                    
                    🎯 **Affinity Probability Binary** (0-1 scale):
                    - Used for **hit discovery** to detect binders from decoys
                    - Values closer to 1 indicate higher probability of binding
                    - Threshold: >0.5 typically indicates a predicted binder
                    
                    📊 **Affinity Prediction Value** (log(IC50) scale):
                    - Used for **ligand optimization** (hit-to-lead, lead-optimization)
                    - Reports binding affinity as log(IC50) where IC50 is in μM
                    - **Lower values = stronger binding**
                    - Examples:
                        - -3: Strong binder (IC50 ~ 10⁻⁹ M)
                        - 0: Moderate binder (IC50 ~ 10⁻⁶ M) 
                        - 2: Weak binder/decoy (IC50 ~ 10⁻⁴ M)
                    
                    🔄 **Conversions:**
                    - To IC50 in μM: IC50 = 10^(log(IC50))
                    - To pIC50 in kcal/mol: pIC50 = (6 - log(IC50)) × 1.364
                    
                    📊 **Counting Method:**
                    - "Predicted Binders" counts unique molecules (by variant_id, barcode, or compound_id)
                    - This prevents double-counting when the same molecule appears in multiple rounds
                    - The displayed count represents distinct chemical entities, not data entries
                    """)
                
                affinity_with_values = filtered_df[filtered_df["affinity_pred_value1"].notna()]
                if not affinity_with_values.empty:
                    # Create metrics for affinity predictions
                    aff_col1, aff_col2, aff_col3, aff_col4 = st.columns(4)
                    with aff_col1:
                        best_affinity = affinity_with_values["affinity_pred_value1"].min()  # Lower log(IC50) is better
                        st.metric("Best log(IC50) (lower=better)", f"{best_affinity:.3f}")
                    with aff_col2:
                        avg_affinity = affinity_with_values["affinity_pred_value1"].mean()
                        st.metric("Average log(IC50)", f"{avg_affinity:.3f}")
                    with aff_col3:
                        if "affinity_probability_binary1" in affinity_with_values.columns:
                            # Count unique binders to avoid double counting
                            binders_df = affinity_with_values[affinity_with_values["affinity_probability_binary1"] > 0.5]
                            
                            # Determine the best unique identifier to use
                            if "variant_id" in binders_df.columns:
                                unique_binders = binders_df["variant_id"].nunique()
                                total_unique = affinity_with_values["variant_id"].nunique()
                                identifier_type = "unique variants"
                            elif "barcode" in binders_df.columns:
                                unique_binders = binders_df["barcode"].nunique()
                                total_unique = affinity_with_values["barcode"].nunique()
                                identifier_type = "unique barcodes"
                            elif "compound_id" in binders_df.columns:
                                unique_binders = binders_df["compound_id"].nunique()
                                total_unique = affinity_with_values["compound_id"].nunique()
                                identifier_type = "unique compounds"
                            else:
                                # Fallback to row count if no identifier available
                                unique_binders = len(binders_df)
                                total_unique = len(affinity_with_values)
                                identifier_type = "entries"
                            
                            st.metric("Predicted Binders", f"{unique_binders}/{total_unique}")
                            if identifier_type != "entries":
                                st.caption(f"({identifier_type})")
                        else:
                            st.metric("Predictions", len(affinity_with_values))
                    with aff_col4:
                        if "affinity_probability_binary1" in affinity_with_values.columns:
                            avg_prob = affinity_with_values["affinity_probability_binary1"].mean()
                            st.metric("Avg Binding Prob", f"{avg_prob:.3f}")
                        else:
                            median_affinity = affinity_with_values["affinity_pred_value1"].median()
                            st.metric("Median log(IC50)", f"{median_affinity:.3f}")
                    
                    # Create visualizations
                    viz_col1, viz_col2 = st.columns(2)
                    
                    with viz_col1:
                        # Affinity value distribution
                        fig_aff = px.histogram(
                            affinity_with_values,
                            x="affinity_pred_value1",
                            nbins=20,
                            title="Distribution of log(IC50) Predictions (Lower = Better)",
                            color_discrete_sequence=["#00cc96"],
                            labels={"affinity_pred_value1": "log(IC50) Prediction", "count": "Number of Compounds"}
                        )
                        fig_aff.update_layout(bargap=0.1)
                        st.plotly_chart(fig_aff, use_container_width=True)
                    
                    with viz_col2:
                        # Affinity vs Probability scatter plot if probability data exists
                        if "affinity_probability_binary1" in affinity_with_values.columns:
                            fig_scatter = px.scatter(
                                affinity_with_values,
                                x="affinity_pred_value1",
                                y="affinity_probability_binary1",
                                title="log(IC50) vs Binding Probability (Lower log(IC50) = Better)",
                                color="affinity_probability_binary1",
                                color_continuous_scale="viridis",
                                labels={
                                    "affinity_pred_value1": "log(IC50) Prediction",
                                    "affinity_probability_binary1": "Binding Probability"
                                }
                            )
                            st.plotly_chart(fig_scatter, use_container_width=True)
                        else:
                            # Show affinity by round if multiple rounds exist
                            if "round" in affinity_with_values.columns and len(affinity_with_values["round"].unique()) > 1:
                                fig_box_aff = px.box(
                                    affinity_with_values,
                                    x="round",
                                    y="affinity_pred_value1",
                                    title="log(IC50) Predictions by Round (Lower = Better)",
                                    color_discrete_sequence=["#48bb78"]
                                )
                                fig_box_aff.update_layout(
                                    xaxis_title="Round",
                                    yaxis_title="log(IC50) Prediction"
                                )
                                st.plotly_chart(fig_box_aff, use_container_width=True)
                            else:
                                # Show affinity statistics
                                st.markdown("**log(IC50) Statistics:**")
                                aff_stats = affinity_with_values["affinity_pred_value1"].describe()
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
                    
                    # Show top affinity performers (lowest log(IC50) values are best)
                    st.markdown("**🏆 Top 10 log(IC50) Predictions (Lowest/Best Values):**")
                    
                    # Get unique top performers to avoid showing the same compound multiple times
                    # Determine the best unique identifier to use
                    if "variant_id" in affinity_with_values.columns:
                        # Group by variant_id and take the best (lowest) affinity_pred_value for each
                        unique_identifier = "variant_id"
                        top_affinity = (affinity_with_values
                                      .loc[affinity_with_values.groupby('variant_id')['affinity_pred_value1'].idxmin()]
                                      .nsmallest(10, "affinity_pred_value1"))
                        st.caption("(Showing best prediction per unique variant)")
                    elif "barcode" in affinity_with_values.columns:
                        # Group by barcode and take the best (lowest) affinity_pred_value for each
                        unique_identifier = "barcode"
                        top_affinity = (affinity_with_values
                                      .loc[affinity_with_values.groupby('barcode')['affinity_pred_value1'].idxmin()]
                                      .nsmallest(10, "affinity_pred_value1"))
                        st.caption("(Showing best prediction per unique barcode)")
                    elif "compound_id" in affinity_with_values.columns:
                        # Group by compound_id and take the best (lowest) affinity_pred_value for each
                        unique_identifier = "compound_id"
                        top_affinity = (affinity_with_values
                                      .loc[affinity_with_values.groupby('compound_id')['affinity_pred_value1'].idxmin()]
                                      .nsmallest(10, "affinity_pred_value1"))
                        st.caption("(Showing best prediction per unique compound)")
                    else:
                        # Fallback to simple nsmallest if no identifier available
                        top_affinity = affinity_with_values.nsmallest(10, "affinity_pred_value1")
                        st.caption("(Showing top 10 entries - may include duplicates)")
                    
                    # Add IC50 conversion column for better interpretation
                    top_affinity_display = top_affinity.copy()
                    # Convert log(IC50) to approximate IC50 in μM: IC50 ≈ 10^(log(IC50))
                    top_affinity_display["estimated_IC50_uM"] = 10 ** top_affinity_display["affinity_pred_value1"]
                    # Convert to pIC50 in kcal/mol: pIC50 = (6 - log(IC50)) × 1.364
                    top_affinity_display["pIC50_kcal_mol"] = (6 - top_affinity_display["affinity_pred_value1"]) * 1.364
                    
                    aff_display_cols = ["compound_id", "affinity_pred_value1", "estimated_IC50_uM", "pIC50_kcal_mol", "round"]
                    if "variant_id" in top_affinity_display.columns:
                        aff_display_cols.insert(1, "variant_id")
                    if "barcode" in top_affinity_display.columns:
                        aff_display_cols.insert(2, "barcode")
                    if "smiles" in top_affinity_display.columns:
                        aff_display_cols.insert(-1, "smiles")
                    if "affinity_probability_binary1" in top_affinity_display.columns:
                        aff_display_cols.insert(-1, "affinity_probability_binary1")
                    
                    existing_aff_cols = [col for col in aff_display_cols if col in top_affinity_display.columns]
                    
                    # Format the dataframe for better display
                    display_df = top_affinity_display[existing_aff_cols].copy()
                    if "estimated_IC50_uM" in display_df.columns:
                        display_df["estimated_IC50_uM"] = display_df["estimated_IC50_uM"].apply(lambda x: f"{x:.2e}")
                    if "affinity_pred_value1" in display_df.columns:
                        display_df["affinity_pred_value1"] = display_df["affinity_pred_value1"].round(3)
                    if "pIC50_kcal_mol" in display_df.columns:
                        display_df["pIC50_kcal_mol"] = display_df["pIC50_kcal_mol"].round(3)
                    if "affinity_probability_binary1" in display_df.columns:
                        display_df["affinity_probability_binary1"] = display_df["affinity_probability_binary1"].round(3)
                    
                    st.dataframe(
                        display_df,
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    st.caption("💡 estimated_IC50_uM = 10^(log(IC50)); pIC50_kcal_mol = (6 - log(IC50)) × 1.364")
                    
                    # Show top binding probability performers if probability data is available
                    if "affinity_probability_binary1" in affinity_with_values.columns:
                        st.markdown("**🎯 Top 10 Highest Binding Probability (Highest Values):**")
                        
                        # Get unique top probability performers to avoid showing the same compound multiple times
                        # Determine the best unique identifier to use
                        if "variant_id" in affinity_with_values.columns:
                            # Group by variant_id and take the best (highest) affinity_probability_binary1 for each
                            top_probability = (affinity_with_values
                                             .loc[affinity_with_values.groupby('variant_id')['affinity_probability_binary1'].idxmax()]
                                             .nlargest(10, "affinity_probability_binary1"))
                            st.caption("(Showing highest probability per unique variant)")
                        elif "barcode" in affinity_with_values.columns:
                            # Group by barcode and take the best (highest) affinity_probability_binary1 for each
                            top_probability = (affinity_with_values
                                             .loc[affinity_with_values.groupby('barcode')['affinity_probability_binary1'].idxmax()]
                                             .nlargest(10, "affinity_probability_binary1"))
                            st.caption("(Showing highest probability per unique barcode)")
                        elif "compound_id" in affinity_with_values.columns:
                            # Group by compound_id and take the best (highest) affinity_probability_binary1 for each
                            top_probability = (affinity_with_values
                                             .loc[affinity_with_values.groupby('compound_id')['affinity_probability_binary1'].idxmax()]
                                             .nlargest(10, "affinity_probability_binary1"))
                            st.caption("(Showing highest probability per unique compound)")
                        else:
                            # Fallback to simple nlargest if no identifier available
                            top_probability = affinity_with_values.nlargest(10, "affinity_probability_binary1")
                            st.caption("(Showing top 10 entries - may include duplicates)")
                        
                        # Prepare display columns for probability table
                        prob_display_cols = ["compound_id", "affinity_probability_binary1", "affinity_pred_value1", "round"]
                        if "variant_id" in top_probability.columns:
                            prob_display_cols.insert(1, "variant_id")
                        if "barcode" in top_probability.columns:
                            prob_display_cols.insert(2, "barcode")
                        if "smiles" in top_probability.columns:
                            prob_display_cols.insert(-1, "smiles")
                        
                        existing_prob_cols = [col for col in prob_display_cols if col in top_probability.columns]
                        
                        # Format the dataframe for better display
                        prob_display_df = top_probability[existing_prob_cols].copy()
                        if "affinity_probability_binary1" in prob_display_df.columns:
                            prob_display_df["affinity_probability_binary1"] = prob_display_df["affinity_probability_binary1"].round(3)
                        if "affinity_pred_value1" in prob_display_df.columns:
                            prob_display_df["affinity_pred_value1"] = prob_display_df["affinity_pred_value1"].round(3)
                        
                        st.dataframe(
                            prob_display_df,
                            use_container_width=True,
                            hide_index=True
                        )
                        
                        st.caption("💡 Higher probability values (closer to 1.0) indicate stronger predicted binding")

            # Docking score distribution if available
            if "docking_score" in filtered_df.columns and filtered_df["docking_score"].notna().any():
                st.subheader("🎯 Docking Score Analysis")
                
                docked_with_scores = filtered_df[filtered_df["docking_score"].notna()]
                if not docked_with_scores.empty:
                    # Create two columns for different visualizations
                    viz_col1, viz_col2 = st.columns(2)
                    
                    with viz_col1:
                        # Histogram of docking scores
                        fig_hist = px.histogram(
                            docked_with_scores,
                            x="docking_score",
                            nbins=20,
                            title="Distribution of Docking Scores",
                            color_discrete_sequence=["#63b3ed"],
                            labels={"docking_score": "Docking Score", "count": "Number of Compounds"}
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
                                color_discrete_sequence=["#f56565"]
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
                
                # Get unique top performers to avoid showing the same compound multiple times
                # Determine the best unique identifier to use
                if "variant_id" in docked_with_scores.columns:
                    # Group by variant_id and take the best (lowest) docking_score for each
                    top_performers = (docked_with_scores
                                    .loc[docked_with_scores.groupby('variant_id')['docking_score'].idxmin()]
                                    .nsmallest(10, "docking_score"))
                    st.caption("(Showing best score per unique variant)")
                elif "barcode" in docked_with_scores.columns:
                    # Group by barcode and take the best (lowest) docking_score for each
                    top_performers = (docked_with_scores
                                    .loc[docked_with_scores.groupby('barcode')['docking_score'].idxmin()]
                                    .nsmallest(10, "docking_score"))
                    st.caption("(Showing best score per unique barcode)")
                elif "compound_id" in docked_with_scores.columns:
                    # Group by compound_id and take the best (lowest) docking_score for each
                    top_performers = (docked_with_scores
                                    .loc[docked_with_scores.groupby('compound_id')['docking_score'].idxmin()]
                                    .nsmallest(10, "docking_score"))
                    st.caption("(Showing best score per unique compound)")
                else:
                    # Fallback to simple nsmallest if no identifier available
                    top_performers = docked_with_scores.nsmallest(10, "docking_score")
                    st.caption("(Showing top 10 entries - may include duplicates)")
                display_cols = ["compound_id", "docking_score", "round"]
                if "variant_id" in top_performers.columns:
                    display_cols.insert(1, "variant_id")
                if "barcode" in top_performers.columns:
                    display_cols.insert(2, "barcode")
                if "smiles" in top_performers.columns:
                    display_cols.insert(-1, "smiles")
                
                existing_cols = [col for col in display_cols if col in top_performers.columns]
                st.dataframe(
                    top_performers[existing_cols],
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No compounds with docking scores are available yet.")
                
            # Combined Analysis Section - Show correlation if both affinity and docking data exist
            if ("affinity_pred_value1" in filtered_df.columns and filtered_df["affinity_pred_value1"].notna().any() and
                "docking_score" in filtered_df.columns and filtered_df["docking_score"].notna().any()):
                
                st.subheader("🔬 Combined Affinity vs Docking Analysis")
                
                # Get compounds that have both affinity and docking data
                combined_data = filtered_df[
                    filtered_df["affinity_pred_value1"].notna() & 
                    filtered_df["docking_score"].notna()
                ]
                
                if not combined_data.empty:
                    # Create correlation plot
                    fig_corr = px.scatter(
                        combined_data,
                        x="docking_score",
                        y="affinity_pred_value1",
                        color="affinity_probability_binary1" if "affinity_probability_binary1" in combined_data.columns else None,
                        title="Docking Score vs log(IC50) Prediction (Both Lower = Better)",
                        hover_data=["compound_id", "barcode"] if "barcode" in combined_data.columns else ["compound_id"],
                        labels={
                            "docking_score": "Docking Score (lower=better)",
                            "affinity_pred_value1": "log(IC50) Prediction (lower=better)",
                            "affinity_probability_binary1": "Binding Probability"
                        }
                    )
                    st.plotly_chart(fig_corr, use_container_width=True)
                    
                    # Show correlation coefficient
                    correlation = combined_data["docking_score"].corr(combined_data["affinity_pred_value1"])
                    st.info(f"Correlation between docking score and log(IC50): {correlation:.3f} (positive correlation means both values tend to move together)")
                    
                    # Show top combined performers
                    st.markdown("**🎯 Best Combined Performance (Low log(IC50) + Low Docking Score):**")
                    # Normalize scores for ranking (lower values are better for both)
                    combined_data_normalized = combined_data.copy()
                    combined_data_normalized["docking_score_norm"] = (
                        (combined_data["docking_score"].max() - combined_data["docking_score"]) / 
                        (combined_data["docking_score"].max() - combined_data["docking_score"].min())
                    )
                    combined_data_normalized["affinity_norm"] = (
                        (combined_data["affinity_pred_value1"].max() - combined_data["affinity_pred_value1"]) / 
                        (combined_data["affinity_pred_value1"].max() - combined_data["affinity_pred_value1"].min())
                    )
                    combined_data_normalized["combined_score"] = (
                        combined_data_normalized["docking_score_norm"] + 
                        combined_data_normalized["affinity_norm"]
                    ) / 2
                    
                    # Add estimated IC50 for better interpretation
                    combined_data_normalized["estimated_IC50_uM"] = 10 ** combined_data_normalized["affinity_pred_value1"]
                    
                    # Get unique top combined performers to avoid showing the same compound multiple times
                    # Determine the best unique identifier to use
                    if "variant_id" in combined_data_normalized.columns:
                        # Group by variant_id and take the best (highest) combined_score for each
                        top_combined = (combined_data_normalized
                                      .loc[combined_data_normalized.groupby('variant_id')['combined_score'].idxmax()]
                                      .nlargest(10, "combined_score"))
                        st.caption("(Showing best combined score per unique variant)")
                    elif "barcode" in combined_data_normalized.columns:
                        # Group by barcode and take the best (highest) combined_score for each
                        top_combined = (combined_data_normalized
                                      .loc[combined_data_normalized.groupby('barcode')['combined_score'].idxmax()]
                                      .nlargest(10, "combined_score"))
                        st.caption("(Showing best combined score per unique barcode)")
                    elif "compound_id" in combined_data_normalized.columns:
                        # Group by compound_id and take the best (highest) combined_score for each
                        top_combined = (combined_data_normalized
                                      .loc[combined_data_normalized.groupby('compound_id')['combined_score'].idxmax()]
                                      .nlargest(10, "combined_score"))
                        st.caption("(Showing best combined score per unique compound)")
                    else:
                        # Fallback to simple nlargest if no identifier available
                        top_combined = combined_data_normalized.nlargest(10, "combined_score")
                        st.caption("(Showing top 10 entries - may include duplicates)")
                    combined_display_cols = ["compound_id", "docking_score", "affinity_pred_value1", "estimated_IC50_uM", "combined_score"]
                    if "variant_id" in top_combined.columns:
                        combined_display_cols.insert(1, "variant_id")
                    if "barcode" in top_combined.columns:
                        combined_display_cols.insert(2, "barcode")
                    if "smiles" in top_combined.columns:
                        combined_display_cols.insert(-1, "smiles")
                    if "affinity_probability_binary1" in top_combined.columns:
                        combined_display_cols.insert(-1, "affinity_probability_binary1")
                    
                    existing_combined_cols = [col for col in combined_display_cols if col in top_combined.columns]
                    
                    # Format the display
                    display_combined = top_combined[existing_combined_cols].copy()
                    if "estimated_IC50_uM" in display_combined.columns:
                        display_combined["estimated_IC50_uM"] = display_combined["estimated_IC50_uM"].apply(lambda x: f"{x:.2e}")
                    
                    st.dataframe(
                        display_combined.round(3),
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("No compounds have both affinity and docking data for correlation analysis.")

            # Boltz-2 Score Analysis Section (use precomputed column if available, else compute)
            has_boltz_cols = (
                ("affinity_pred_value1" in df.columns and df["affinity_pred_value1"].notna().any() and
                 "affinity_probability_binary1" in df.columns and df["affinity_probability_binary1"].notna().any())
                or
                ("boltz2_score" in df.columns and df["boltz2_score"].notna().any())
            )

            if has_boltz_cols:
                st.markdown("---")
                st.subheader("🧮 Boltz-2 Score")

                scored_data = df.copy()
                # Use existing boltz2_score if present, otherwise compute strictly from ensemble-1 inputs
                if "boltz2_score" not in scored_data.columns or scored_data["boltz2_score"].isna().all():
                    use_aff = "affinity_pred_value1"
                    use_prob = "affinity_probability_binary1"
                    if use_aff in scored_data.columns and use_prob in scored_data.columns:
                        try:
                            scored_data = scored_data[scored_data[use_aff].notna() & scored_data[use_prob].notna()].copy()
                            scored_data["boltz2_score"] = (
                                scored_data.apply(lambda row: max(((-float(row[use_aff])) + 2.0) / 4.0, 0.0) * float(row[use_prob]), axis=1)
                            )
                        except Exception:
                            scored_data["boltz2_score"] = pd.NA
                    else:
                        scored_data["boltz2_score"] = pd.NA

                # Filter to rows with boltz2_score now
                scored_data = scored_data[scored_data.get("boltz2_score").notna()] if "boltz2_score" in scored_data.columns else pd.DataFrame()

                if not scored_data.empty:
                    # Summary metrics (unique count by best identifier)
                    score_col1, score_col2, score_col3, score_col4 = st.columns(4)
                    # unique identification hierarchy
                    if "variant_id" in scored_data.columns:
                        unique_count = scored_data["variant_id"].nunique()
                        high_score_count = scored_data[scored_data["boltz2_score"] > 0.5]["variant_id"].nunique()
                        ident_caption = "unique variants"
                    elif "barcode" in scored_data.columns:
                        unique_count = scored_data["barcode"].nunique()
                        high_score_count = scored_data[scored_data["boltz2_score"] > 0.5]["barcode"].nunique()
                        ident_caption = "unique barcodes"
                    elif "compound_id" in scored_data.columns:
                        unique_count = scored_data["compound_id"].nunique()
                        high_score_count = scored_data[scored_data["boltz2_score"] > 0.5]["compound_id"].nunique()
                        ident_caption = "unique compounds"
                    else:
                        unique_count = len(scored_data)
                        high_score_count = len(scored_data[scored_data["boltz2_score"] > 0.5])
                        ident_caption = "entries"

                    with score_col1:
                        st.metric("Best Score", f"{scored_data['boltz2_score'].max():.4f}")
                    with score_col2:
                        st.metric("Average Score", f"{scored_data['boltz2_score'].mean():.4f}")
                    with score_col3:
                        st.metric("Compounds Scored", unique_count)
                        if ident_caption != "entries":
                            st.caption(f"({ident_caption})")
                    with score_col4:
                        st.metric("High Scores (>0.5)", high_score_count)

                    # Boltz-2 score distribution
                    st.markdown("**Score Distribution**")
                    try:
                        fig_boltz_hist = px.histogram(
                            scored_data,
                            x="boltz2_score",
                            nbins=20,
                            title="Distribution of Boltz-2 Scores",
                            color_discrete_sequence=["#38a169"],
                            labels={"boltz2_score": "Boltz-2 Score", "count": "Number of Compounds"}
                        )
                        fig_boltz_hist.update_layout(bargap=0.1)
                        st.plotly_chart(fig_boltz_hist, use_container_width=True)
                    except Exception as e:
                        st.warning(f"Could not render Boltz-2 score histogram: {e}")

                    # Top scoring (deduplicated by best identifier)
                    st.markdown("**🏆 Top 10 Boltz-2 Scores**")
                    if "variant_id" in scored_data.columns:
                        top_scored = (scored_data
                                      .loc[scored_data.groupby('variant_id')["boltz2_score"].idxmax()]
                                      .nlargest(10, "boltz2_score"))
                    elif "barcode" in scored_data.columns:
                        top_scored = (scored_data
                                      .loc[scored_data.groupby('barcode')["boltz2_score"].idxmax()]
                                      .nlargest(10, "boltz2_score"))
                    elif "compound_id" in scored_data.columns:
                        top_scored = (scored_data
                                      .loc[scored_data.groupby('compound_id')["boltz2_score"].idxmax()]
                                      .nlargest(10, "boltz2_score"))
                    else:
                        top_scored = scored_data.nlargest(10, "boltz2_score")

                    display_columns = ["compound_id", "boltz2_score"]
                    if "variant_id" in top_scored.columns:
                        display_columns.insert(1, "variant_id")
                    if "barcode" in top_scored.columns:
                        display_columns.insert(2, "barcode")
                    for extra in ["affinity_pred_value1", "affinity_probability_binary1", "affinity_pred_value", "affinity_probability_binary", "docking_score", "round", "smiles"]:
                        if extra in top_scored.columns and extra not in display_columns:
                            display_columns.append(extra)

                    existing_display_cols = [c for c in display_columns if c in top_scored.columns]
                    st.dataframe(top_scored[existing_display_cols].round(3), use_container_width=True, hide_index=True)
                else:
                    st.info("No sufficient Boltz-2 inputs found to compute scores.")

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

# Enhanced Export options
st.divider()
st.markdown("## 💾 Export & Download Options")
st.markdown("Export your live pipeline data for external analysis or sharing")

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
            "total_compounds": len(df[df["status"] == "GENERATED"]) if "status" in df.columns else 0,
            "total_variants": count_reached_stage(df, "SYNTHETIZED", include_failures=True),
            "filtered_variants": count_reached_stage(df, "PASSFILTER", include_failures=False),
            "docked_compounds": len(df[df["status"] == "DOCKED"]) if "status" in df.columns else 0,
            }
        
        if "docking_score" in df.columns and df["docking_score"].notna().any():
            stats["average_docking_score"] = float(df[df["docking_score"].notna()]["docking_score"].mean())
            stats["best_docking_score"] = float(df[df["docking_score"].notna()]["docking_score"].min())
        
        if "affinity_pred_value1" in df.columns and df["affinity_pred_value1"].notna().any():
            stats["average_log_ic50"] = float(df[df["affinity_pred_value1"].notna()]["affinity_pred_value1"].mean())
            stats["best_log_ic50"] = float(df[df["affinity_pred_value1"].notna()]["affinity_pred_value1"].min())  # Lower is better
            if "affinity_probability_binary1" in df.columns:
                # Count unique binders to avoid double counting
                binders_df = df[df["affinity_probability_binary1"] > 0.5]
                
                # Determine the best unique identifier to use
                if "variant_id" in binders_df.columns:
                    unique_binders = binders_df["variant_id"].nunique()
                    stats["predicted_binders_unique_variants"] = unique_binders
                elif "barcode" in binders_df.columns:
                    unique_binders = binders_df["barcode"].nunique()
                    stats["predicted_binders_unique_barcodes"] = unique_binders
                elif "compound_id" in binders_df.columns:
                    unique_binders = binders_df["compound_id"].nunique()
                    stats["predicted_binders_unique_compounds"] = unique_binders
                else:
                    # Fallback to row count if no identifier available
                    unique_binders = len(binders_df)
                    stats["predicted_binders_entries"] = unique_binders
                
                # Also keep the total row count for comparison
                stats["predicted_binders_total_entries"] = len(binders_df)
        
        st.json(stats)

# Dashboard footer
st.divider()
st.markdown("""
    <div style="text-align: center; padding: 2rem; background: #f8f9fa; border-radius: 10px; margin: 2rem 0;">
        <p style="margin: 0; color: #6c757d;">
            <strong>Live Pipeline Dashboard</strong> | Real-time monitoring and analysis<br>
            🔄 Auto-refresh available | 📊 Interactive visualizations | 🧬 3D molecular viewers
        </p>
    </div>
""", unsafe_allow_html=True) 