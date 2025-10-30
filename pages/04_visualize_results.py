import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from rdkit import Chem
from rdkit.Chem import Draw
from rdkit.Chem import AllChem
import base64
 
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
    page_title="Visualize Results",
    page_icon="🔍",
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
    
    .analysis-header {
        background: linear-gradient(90deg, #11998e 0%, #38ef7d 100%);
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
        border-left: 4px solid #11998e;
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
    
    .analysis-indicator {
        color: #11998e;
        font-weight: bold;
    }
    
    <style>
    .metric-card {
        background: linear-gradient(90deg, #4a5568 0%, #2d3748 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin: 0.5rem 0;
    }
    .success-card {
        background: linear-gradient(90deg, #38a169 0%, #48bb78 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin: 0.5rem 0;
    }
    .info-card {
        border-left: 4px solid #38a169;
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
    .highlight {
        color: #38a169;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

# Header for visualization page
st.markdown("""
    <div class="analysis-header">
        <h1>🔍 Visualize Pipeline Results <span class="analysis-indicator">📈</span></h1>
        <p>Load and explore any completed pipeline output directory</p>
    </div>
""", unsafe_allow_html=True)

# Add information about analysis capabilities
with st.expander("🔬 Analysis Features", expanded=False):
    st.markdown("""
    **Comprehensive Analysis Capabilities:**
    
    📊 **Deep Data Exploration**
    - Load and analyze any completed pipeline output
    - Advanced filtering and sorting across all data dimensions
    - Pagination for large datasets with configurable views
    
    🎯 **Detailed Visualizations**
    - Interactive 3D molecular structure viewers
    - Multi-dimensional plotting and correlation analysis
    - Custom dashboard views for different analysis needs
    
    📈 **Statistical Analysis**
    - Distribution analysis for docking scores and affinity predictions
    - Correlation analysis between different metrics
    - Performance comparisons across pipeline rounds
    - Boltz-2 score ranking using paper formula: max((-affinity_pred_value1 + 2) / 4, 0) × likelihood
    
    🧬 **Enhanced 3D Visualization:**
    - 🟢 Best poses highlighted in green
    - 🔵🟣🟡🟠 Alternative poses color-coded  
    - 🌈 Protein receptor with binding surface
    - Interactive controls with download capabilities
    
    **💾 Export & Sharing:**
    - Download filtered datasets in multiple formats
    - Export 3D structures for external analysis
    - Generate summary reports and statistics
    
    **🔍 Flexible Data Input:**
    - Manual directory path entry
    - Automatic detection of pipeline structure
    - Support for multiple output formats
    
    **🔬 Receptor File Configuration:**
    - Set a global receptor file in the sidebar for all visualizations
    - Override with specific receptor files for individual compounds
    - Supports both .pdbqt and .pdb formats
    """)
    
    # Check library availability
    try:
        import py3Dmol
        from rdkit import Chem
        st.success("✅ All analysis libraries available (py3Dmol, RDKit)")
    except ImportError as e:
        st.warning(f"⚠️ Missing libraries: {e}")
        st.info("Install with: `pip install py3Dmol rdkit`")

# Initialize session state variables
if "output_dir" not in st.session_state:
    st.session_state.output_dir = None

if "results_data" not in st.session_state:
    st.session_state.results_data = None

if "selected_view" not in st.session_state:
    st.session_state.selected_view = "Summary"

# Directory selection
st.markdown("## 📁 Select Pipeline Output Directory")

st.info("Enter the path to any completed pipeline output directory for visualization")

# Enter path manually
dir_path = st.text_input(
    "Output Directory Path:", 
    placeholder="/path/to/outputs/pipeline_run_name",
    help="Enter the full path to a pipeline output directory containing results to visualize"
)

# Process manually entered path
if dir_path:
    output_dir_path = Path(dir_path)
    if output_dir_path.exists() and output_dir_path.is_dir():
        st.success(f"✅ Directory Found: {output_dir_path}")
        st.session_state.output_dir = output_dir_path
        
        # Auto-load results when valid directory is found
        with st.spinner("🔄 Loading results..."):
            try:
                results = load_results(st.session_state.output_dir)
                if results is not None and results.get("tracking_report") is not None:
                    st.session_state.results_data = results
                    st.success("✅ Successfully loaded results!")
                else:
                    st.warning("⚠️ No tracking report found. The pipeline may still be running or incomplete.")
                    st.session_state.results_data = results  # Keep partial results
            except Exception as e:
                st.error(f"❌ Error processing results: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
    else:
        st.error(f"❌ Directory not found: {output_dir_path}")
        st.session_state.output_dir = None
        st.session_state.results_data = None
else:
    st.warning("📁 Please enter a valid pipeline output directory path above to start visualization.")
    st.info("💡 **Tip:** Look for directories containing 'master_tracking' or 'round_*' subdirectories.")
    st.session_state.results_data = None

# Navigation and main content
if st.session_state.results_data and st.session_state.results_data.get("tracking_report") is not None:
    df = st.session_state.results_data["tracking_report"]
    
    with st.sidebar:
        st.session_state.selected_view = "Summary"
        
        
        # Sidebar filtering options (global)
        st.subheader("🎛️ Global Filters")
        
        # Round filter (applies to all views)
        if "round" in df.columns:
            try:
                round_options = sorted([r for r in df["round"].unique() if pd.notna(r)])
                sidebar_rounds = st.multiselect(
                    "Filter by Round",
                    options=round_options,
                    default=round_options,
                    key="sidebar_rounds_viz"
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
                    key="sidebar_status_viz"
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
                        key="retrosynthesis_threshold_viz"
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
            
    # Add refresh button
    if st.button("🔄 Refresh Data"):
        if st.session_state.output_dir:
            with st.spinner("Refreshing data..."):
                results = load_results(st.session_state.output_dir)
                if results is not None:
                    st.session_state.results_data = results
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
    # Check if we have any data at all
    if filtered_df.empty:
        st.warning("The tracking report is empty. The pipeline may still be in the initial stages.")
    else:
        # Continue with regular view rendering based on selected view
        # Define available_statuses for use across all views (use original df for this)
        available_statuses = df["status"].unique() if "status" in df.columns else []
                
        if st.session_state.selected_view == "Summary":
            st.markdown("## 📊 Pipeline Overview")
            
            # Enhanced Summary metrics with styling
            st.markdown("### 🔢 Key Metrics")
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
                            # Group by variant_id and take the best (highest) affinity_probability_binary for each
                            top_probability = (affinity_with_values
                                             .loc[affinity_with_values.groupby('variant_id')['affinity_probability_binary1'].idxmax()]
                                             .nlargest(10, "affinity_probability_binary1"))
                            st.caption("(Showing highest probability per unique variant)")
                        elif "barcode" in affinity_with_values.columns:
                            # Group by barcode and take the best (highest) affinity_probability_binary for each
                            top_probability = (affinity_with_values
                                             .loc[affinity_with_values.groupby('barcode')['affinity_probability_binary1'].idxmax()]
                                             .nlargest(10, "affinity_probability_binary1"))
                            st.caption("(Showing highest probability per unique barcode)")
                        elif "compound_id" in affinity_with_values.columns:
                            # Group by compound_id and take the best (highest) affinity_probability_binary for each
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
                    
                    # Add 3D visualization if we have docking data as well
                    if ("docking_score" in filtered_df.columns and filtered_df["docking_score"].notna().any() and
                        "affinity_probability_binary1" in affinity_with_values.columns):
                        
                        st.subheader("🎲 3D Interactive Analysis: Affinity vs Probability vs Docking")
                        
                        # Get compounds that have all three metrics
                        three_d_data = filtered_df[
                            filtered_df["affinity_pred_value1"].notna() & 
                            filtered_df["affinity_probability_binary1"].notna() &
                            filtered_df["docking_score"].notna()
                        ]
                        
                        if not three_d_data.empty:
                            # Add IC50 conversion for better interpretation
                            three_d_data_display = three_d_data.copy()
                            three_d_data_display["estimated_IC50_uM"] = 10 ** three_d_data_display["affinity_pred_value1"]
                            
                            # Create interactive 3D scatter plot
                            fig_3d = go.Figure(data=go.Scatter3d(
                                x=three_d_data_display["affinity_pred_value1"],
                                y=three_d_data_display["affinity_probability_binary1"],
                                z=three_d_data_display["docking_score"],
                                mode='markers',
                                marker=dict(
                                    size=8,
                                    color=three_d_data_display["affinity_probability_binary1"],
                                    colorscale='Viridis',
                                    colorbar=dict(title="Binding Probability"),
                                    opacity=0.8,
                                    line=dict(width=1, color='black')
                                ),
                                text=[
                                    f"ID: {row.get('compound_id', 'N/A')}<br>" +
                                    f"Variant: {row.get('variant_id', 'N/A')}<br>" +
                                    f"log(IC50): {row['affinity_pred_value1']:.3f}<br>" +
                                    f"IC50: {(10**row['affinity_pred_value1']):.2e} μM<br>" +
                                    f"Binding Prob: {row['affinity_probability_binary1']:.3f}<br>" +
                                    f"Docking Score: {row['docking_score']:.3f}<br>" +
                                    f"Round: {row.get('round', 'N/A')}"
                                    for _, row in three_d_data_display.iterrows()
                                ],
                                hovertemplate='%{text}<extra></extra>',
                                name='Compounds'
                            ))
                            
                            # Update layout for better visualization
                            fig_3d.update_layout(
                                title={
                                    'text': '3D Analysis: log(IC50) vs Binding Probability vs Docking Score',
                                    'x': 0.5,
                                    'xanchor': 'center'
                                },
                                scene=dict(
                                    xaxis_title='log(IC50) Prediction (lower = better)',
                                    yaxis_title='Binding Probability (higher = better)',
                                    zaxis_title='Docking Score (lower = better)',
                                    camera=dict(
                                        eye=dict(x=1.2, y=1.2, z=1.2)
                                    )
                                ),
                                width=800,
                                height=600,
                                margin=dict(r=20, b=10, l=10, t=40)
                            )
                            
                            st.plotly_chart(fig_3d, use_container_width=True)
                        else:
                            st.info("No compounds have all three metrics (affinity, probability, and docking) for 3D visualization.")
                    else:
                        st.info("💡 3D visualization requires compounds with affinity predictions, binding probabilities, and docking scores.")

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
            
            # Boltz-2 Score Analysis Section (use precomputed column if available, else compute from available inputs)
            has_boltz_cols = (
                ("affinity_pred_value1" in filtered_df.columns and filtered_df["affinity_pred_value1"].notna().any() and
                 "affinity_probability_binary1" in filtered_df.columns and filtered_df["affinity_probability_binary1"].notna().any())
                or
                ("boltz2_score" in filtered_df.columns and filtered_df["boltz2_score"].notna().any())
            )
            if has_boltz_cols:
                
                st.markdown("---")
                st.subheader("🧮 Boltz-2 Score (From Paper)")
                
                st.markdown("""
                **Formula:** score = max((-affinity + 2) / 4, 0) × likelihood
                
                Where:
                - **affinity**: log(IC50) prediction (lower = better). Prefer ensemble-1 if present.
                - **likelihood**: binding probability (0-1 scale). Prefer ensemble-1 if present.
                
                **Note:** If `boltz2_score` exists in the tracking file it will be used directly; otherwise it is computed on-the-fly.
                """)
                
                # Use/compute score
                if "boltz2_score" in filtered_df.columns and filtered_df["boltz2_score"].notna().any():
                    scored_data = filtered_df[filtered_df["boltz2_score"].notna()].copy()
                else:
                    scored_data = filtered_df.copy()
                    use_aff = "affinity_pred_value1"
                    use_prob = "affinity_probability_binary1"
                    if use_aff in scored_data.columns and use_prob in scored_data.columns:
                        scored_data = scored_data[scored_data[use_aff].notna() & scored_data[use_prob].notna()].copy()
                        try:
                            scored_data["boltz2_score"] = (
                                scored_data.apply(lambda row: max(((-float(row[use_aff])) + 2.0) / 4.0, 0.0) * float(row[use_prob]), axis=1)
                            )
                        except Exception:
                            scored_data["boltz2_score"] = pd.NA
                    else:
                        scored_data = pd.DataFrame()
                
                if not scored_data.empty:
                    # Create summary metrics with proper unique counting
                    score_col1, score_col2, score_col3, score_col4 = st.columns(4)
                    
                    # Determine the best unique identifier to use for counting
                    if "variant_id" in scored_data.columns:
                        unique_count = scored_data["variant_id"].nunique()
                        identifier_type = "unique variants"
                    elif "barcode" in scored_data.columns:
                        unique_count = scored_data["barcode"].nunique()
                        identifier_type = "unique barcodes"
                    elif "compound_id" in scored_data.columns:
                        unique_count = scored_data["compound_id"].nunique()
                        identifier_type = "unique compounds"
                    else:
                        unique_count = len(scored_data)
                        identifier_type = "entries"
                    
                    with score_col1:
                        best_score = scored_data["boltz2_score"].max()
                        st.metric("Best Score", f"{best_score:.4f}")
                    with score_col2:
                        avg_score = scored_data["boltz2_score"].mean()
                        st.metric("Average Score", f"{avg_score:.4f}")
                    with score_col3:
                        st.metric("Compounds Scored", unique_count)
                        if identifier_type != "entries":
                            st.caption(f"({identifier_type})")
                    with score_col4:
                        high_score_data = scored_data[scored_data["boltz2_score"] > 0.5]
                        if identifier_type == "unique variants" and "variant_id" in high_score_data.columns:
                            high_score_count = high_score_data["variant_id"].nunique()
                        elif identifier_type == "unique barcodes" and "barcode" in high_score_data.columns:
                            high_score_count = high_score_data["barcode"].nunique()
                        elif identifier_type == "unique compounds" and "compound_id" in high_score_data.columns:
                            high_score_count = high_score_data["compound_id"].nunique()
                        else:
                            high_score_count = len(high_score_data)
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
                    
                    # Top scoring compounds with deduplication
                    st.markdown("**🏆 Top 10 Scoring Compounds**")
                    
                    # Get unique top performers to avoid showing the same compound multiple times
                    # Determine the best unique identifier to use
                    if "variant_id" in scored_data.columns:
                        # Group by variant_id and take the best (highest) boltz2_score for each
                        top_scored = (scored_data
                                    .loc[scored_data.groupby('variant_id')['boltz2_score'].idxmax()]
                                    .nlargest(10, "boltz2_score"))
                        st.caption("(Showing highest score per unique variant)")
                    elif "barcode" in scored_data.columns:
                        # Group by barcode and take the best (highest) boltz2_score for each
                        top_scored = (scored_data
                                    .loc[scored_data.groupby('barcode')['boltz2_score'].idxmax()]
                                    .nlargest(10, "boltz2_score"))
                        st.caption("(Showing highest score per unique barcode)")
                    elif "compound_id" in scored_data.columns:
                        # Group by compound_id and take the best (highest) boltz2_score for each
                        top_scored = (scored_data
                                    .loc[scored_data.groupby('compound_id')['boltz2_score'].idxmax()]
                                    .nlargest(10, "boltz2_score"))
                        st.caption("(Showing highest score per unique compound)")
                    else:
                        # Fallback to simple nlargest if no identifier available
                        top_scored = scored_data.nlargest(10, "boltz2_score")
                        st.caption("(Showing top 10 entries - may include duplicates)")
                    
                    # Prepare display columns
                    display_columns = ["compound_id", "boltz2_score", "affinity_pred_value1", "affinity_probability_binary1"]
                    if "variant_id" in top_scored.columns:
                        display_columns.insert(1, "variant_id")
                    if "barcode" in top_scored.columns:
                        display_columns.insert(2, "barcode")
                    if "smiles" in top_scored.columns:
                        display_columns.append("smiles")
                    if "docking_score" in top_scored.columns and top_scored["docking_score"].notna().any():
                        display_columns.append("docking_score")
                    
                    # Only include columns that exist
                    existing_display_cols = [col for col in display_columns if col in top_scored.columns]
                    
                    # Format the dataframe for better display
                    display_df = top_scored[existing_display_cols].copy()
                    display_df["boltz2_score"] = display_df["boltz2_score"].round(4)
                    display_df["affinity_pred_value1"] = display_df["affinity_pred_value1"].round(3)
                    display_df["affinity_probability_binary1"] = display_df["affinity_probability_binary1"].round(3)
                    if "docking_score" in display_df.columns:
                        display_df["docking_score"] = display_df["docking_score"].round(3)
                    
                    st.dataframe(
                        display_df,
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    st.caption("💡 Compounds are ranked by Boltz-2 score (higher = better). The score combines affinity predictions and confidence levels.")
                    
                    # Download option for top scores with deduplication
                    col1, col2 = st.columns(2)
                    with col1:
                        # Download unique top scores
                        if "variant_id" in scored_data.columns:
                            unique_top_100 = (scored_data
                                            .loc[scored_data.groupby('variant_id')['boltz2_score'].idxmax()]
                                            .nlargest(100, "boltz2_score"))
                            filename = "top_100_unique_boltz2_scores.csv"
                            button_text = "📥 Download Top 100 Unique Scores"
                        elif "barcode" in scored_data.columns:
                            unique_top_100 = (scored_data
                                            .loc[scored_data.groupby('barcode')['boltz2_score'].idxmax()]
                                            .nlargest(100, "boltz2_score"))
                            filename = "top_100_unique_boltz2_scores.csv"
                            button_text = "📥 Download Top 100 Unique Scores"
                        elif "compound_id" in scored_data.columns:
                            unique_top_100 = (scored_data
                                            .loc[scored_data.groupby('compound_id')['boltz2_score'].idxmax()]
                                            .nlargest(100, "boltz2_score"))
                            filename = "top_100_unique_boltz2_scores.csv"
                            button_text = "📥 Download Top 100 Unique Scores"
                        else:
                            unique_top_100 = scored_data.nlargest(100, "boltz2_score")
                            filename = "top_100_boltz2_scores.csv"
                            button_text = "📥 Download Top 100 Scores"
                        
                        st.download_button(
                            button_text,
                            data=unique_top_100.to_csv(index=False).encode('utf-8'),
                            file_name=filename,
                            mime="text/csv"
                        )
                    
                    with col2:
                        # Download all scores (with duplicates)
                        st.download_button(
                            "📥 Download All Scores (with duplicates)",
                            data=scored_data.to_csv(index=False).encode('utf-8'),
                            file_name="all_boltz2_scores.csv",
                            mime="text/csv"
                        )
                else:
                    st.warning("No compounds found with both first ensemble model affinity predictions (affinity_pred_value1) and probability values.")

        # Other dashboard views removed per request
    
    # Enhanced Export options
    st.divider()
    st.markdown("## 💾 Export & Download Options")
    st.markdown("Export your analyzed data for external analysis or sharing")

    export_col1, export_col2, export_col3 = st.columns(3)

    with export_col1:
        if st.button("Export All Results"):
            if not filtered_df.empty:
                st.download_button(
                    "📥 Download Complete Dataset",
                    data=filtered_df.to_csv(index=False).encode('utf-8'),
                    file_name="all_results.csv",
                    mime="text/csv"
                )
            else:
                st.warning("No data to export after filtering.")

    with export_col2:
        if (st.button("Export Docking Results") 
            and "docking_score" in filtered_df.columns):
            
            docked_df = filtered_df[filtered_df["status"] == "DOCKED"]
            if not docked_df.empty:
                st.download_button(
                    "📥 Download Docking Results",
                    data=docked_df.to_csv(index=False).encode('utf-8'),
                    file_name="docking_results.csv",
                    mime="text/csv"
                )
            else:
                st.warning("No docking results to export after filtering.")

    with export_col3:
        if st.button("Export Summary Statistics"):
            if not filtered_df.empty:
                stats = {
                    "total_compounds": len(filtered_df[filtered_df["status"] == "GENERATED"]) if "status" in filtered_df.columns else 0,
                    "total_variants": count_reached_stage(filtered_df, "SYNTHETIZED", include_failures=True),
                    "filtered_variants": count_reached_stage(filtered_df, "PASSFILTER", include_failures=False),
                    "docked_compounds": len(filtered_df[filtered_df["status"] == "DOCKED"]) if "status" in filtered_df.columns else 0,
                    }
                
                if "docking_score" in filtered_df.columns and filtered_df["docking_score"].notna().any():
                    stats["average_docking_score"] = float(filtered_df[filtered_df["docking_score"].notna()]["docking_score"].mean())
                    stats["best_docking_score"] = float(filtered_df[filtered_df["docking_score"].notna()]["docking_score"].min())
                
                if "affinity_pred_value1" in filtered_df.columns and filtered_df["affinity_pred_value1"].notna().any():
                    stats["average_log_ic50"] = float(filtered_df[filtered_df["affinity_pred_value1"].notna()]["affinity_pred_value1"].mean())
                    stats["best_log_ic50"] = float(filtered_df[filtered_df["affinity_pred_value1"].notna()]["affinity_pred_value1"].min())  # Lower is better
                    if "affinity_probability_binary1" in filtered_df.columns:
                        # Count unique binders to avoid double counting
                        binders_df = filtered_df[filtered_df["affinity_probability_binary1"] > 0.5]
                        
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
            else:
                st.warning("No data to export after filtering.")
else:
    # No results data available
    st.info("Please select an output directory and load results to view visualizations.")
    
    # Show help information when no data is loaded
    st.markdown("### 💡 Getting Started")
    st.markdown("""
    **To start visualizing your pipeline results:**
    
    1. **Enter the output directory path** in the text field above
    2. **Wait for automatic loading** of the tracking report
    3. **Explore different views** using the sidebar navigation
    
    **Supported Directory Structures:**
    - Pipeline output directories with `master_tracking/` folder
    - Round-specific directories with `round_*/` folders
    - Directories containing tracking reports (CSV files)
    
    **Features Available:**
    - 📊 Summary dashboard with key metrics
    - 🤖 Boltz-2 affinity predictions analysis
    - 🧮 Boltz-2 score ranking (from paper formula using first ensemble model)
    - 💾 Export and download capabilities
    """) 