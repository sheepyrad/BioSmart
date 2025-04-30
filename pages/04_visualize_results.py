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

st.title("🔍 Visualize Pipeline Results")
st.markdown("""
    View the results from an existing output directory. Upload or select a directory to visualize results.
""")

# Initialize session state variables
if "output_dir" not in st.session_state:
    st.session_state.output_dir = None

if "results_data" not in st.session_state:
    st.session_state.results_data = None

if "selected_view" not in st.session_state:
    st.session_state.selected_view = "Summary"

# Directory selection
st.header("Select Output Directory")

# Enter path manually
dir_path = st.text_input("Enter the path to the output directory:", placeholder="/path/to/outputs/NS5")

# Process manually entered path
if dir_path:
    output_dir_path = Path(dir_path)
    if output_dir_path.exists() and output_dir_path.is_dir():
        st.success(f"Found directory: {output_dir_path}")
        st.session_state.output_dir = output_dir_path
    else:
        st.error(f"Directory not found: {output_dir_path}")
        st.session_state.output_dir = None

# Load results if directory is available
if st.session_state.output_dir:
    st.success(f"Ready to load data from: {st.session_state.output_dir}")
    
    # Add a more prominent load button
    load_col1, load_col2 = st.columns([2, 1])
    with load_col1:
        st.markdown("Click the button to load data from the selected directory.")
    with load_col2:
        if st.button("Load Results", type="primary", use_container_width=True):
            with st.spinner("Loading results..."):
                try:
                    results = load_results(st.session_state.output_dir)
                    if results is None:
                        st.error("Failed to load results")
                    else:
                        st.session_state.results_data = results
                        st.success("Successfully loaded results!")
                except Exception as e:
                    st.error(f"Error processing results: {str(e)}")
                    import traceback
                    st.code(traceback.format_exc())
else:
    st.info("Please select a directory to load results from.")

# Navigation
if st.session_state.results_data:
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
        df = st.session_state.results_data["tracking_report"]
        
        # Round filter (applies to all views)
        # Filter out NaN values from options
        round_options = sorted([r for r in df["round"].unique() if pd.notna(r)])
        sidebar_rounds = st.multiselect(
            "Filter by Round",
            options=round_options,
            default=round_options,
            key="sidebar_rounds"
        )
        
        # Status filter
        status_options = sorted([s for s in df["status"].unique() if pd.notna(s)])
        sidebar_status = st.multiselect(
            "Filter by Status",
            options=status_options,
            default=status_options,
            key="sidebar_status"
        )
        
        # Apply global filters
        if sidebar_rounds and sidebar_status:
            filtered_df = df[df["round"].isin(sidebar_rounds) & df["status"].isin(sidebar_status)]
        else:
            filtered_df = df
            
    # Main content based on selected view
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
                
                # Then show expandable elements with molecule renderings
                st.subheader("Compound Structures")
                
                # Add pagination for large datasets
                if len(compounds_df) > 10:
                    compounds_per_page = st.slider("Compounds per page", 5, 20, 10, key="compounds_per_page")
                    page_number = st.number_input("Page", min_value=1, max_value=max(1, len(compounds_df) // compounds_per_page + 1), step=1, key="compounds_page")
                    start_idx = (page_number - 1) * compounds_per_page
                    end_idx = min(start_idx + compounds_per_page, len(compounds_df))
                    paginated_df = compounds_df.iloc[start_idx:end_idx]
                else:
                    paginated_df = compounds_df
                
                for _, compound in paginated_df.iterrows():
                    with st.expander(f"Compound {compound.get('compound_id', 'Unknown')}"):
                        col1, col2 = st.columns([1, 2])
                        
                        with col1:
                            # Display 2D structure
                            if "smiles" in compound and not pd.isna(compound["smiles"]):
                                mol_img = render_mol(compound["smiles"])
                                if mol_img:
                                    st.image(mol_img, caption="2D Structure", use_container_width=True)
                                else:
                                    st.info("Could not render molecule structure")
                            else:
                                st.warning("No SMILES data available for this compound")
                        
                        with col2:
                            # Compound details
                            details_tab, variants_tab = st.tabs(["Details", "Related Variants"])
                            
                            with details_tab:
                                # Build details dict with only non-NA values
                                details = {}
                                for field in ["compound_id", "barcode", "generation", "round", "smiles", "source", "timestamp"]:
                                    if field in compound and not pd.isna(compound[field]):
                                        details[field.replace("_", " ").title()] = compound[field]
                                st.json(details)
                            
                            with variants_tab:
                                # Find related variants
                                if "parent_id" in df.columns:
                                    compound_id = compound.get("compound_id", "")
                                    if compound_id:
                                        related_variants = df[df["parent_id"] == compound_id]
                                        
                                        if not related_variants.empty:
                                            # Determine what fields to show in the related variants table
                                            variant_columns = ["variant_id", "status"]
                                            if "score" in related_variants.columns:
                                                variant_columns.append("score")
                                            if "docking_score" in related_variants.columns:
                                                variant_columns.append("docking_score")
                                                
                                            # Only use columns that exist
                                            existing_var_columns = [col for col in variant_columns if col in related_variants.columns]
                                            
                                            st.dataframe(
                                                related_variants[existing_var_columns],
                                                use_container_width=True,
                                                hide_index=True
                                            )
                                            
                                            # Add helpful status information
                                            variant_statuses = related_variants["status"].unique() if "status" in related_variants.columns else []
                                            if "DOCKED" in variant_statuses:
                                                st.success("✅ Some variants have been docked")
                                            elif "PASSFILTER" in variant_statuses:
                                                st.info("⏳ Variants have been filtered but not yet docked")
                                            elif "SYNTHETIZED" in variant_statuses:
                                                st.info("⏳ Variants have been synthesized but not yet filtered or docked")
                                        else:
                                            st.info("No related variants found")
                                    else:
                                        st.info("Compound ID not available to find related variants")
                                else:
                                    st.info("Parent-variant relationship not available")
    
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
                
                # Variant Structures
                st.subheader("Variant Structures")
                
                # Add pagination for large datasets
                if len(variants_df) > 10:
                    variants_per_page = st.slider("Variants per page", 5, 20, 10, key="variants_per_page")
                    page_number = st.number_input("Page", min_value=1, max_value=max(1, len(variants_df) // variants_per_page + 1), step=1, key="variants_page")
                    start_idx = (page_number - 1) * variants_per_page
                    end_idx = min(start_idx + variants_per_page, len(variants_df))
                    paginated_var_df = variants_df.iloc[start_idx:end_idx]
                else:
                    paginated_var_df = variants_df
                
                for _, variant in paginated_var_df.iterrows():
                    with st.expander(f"Variant {variant.get('variant_id', 'Unknown')}"):
                        col1, col2 = st.columns([1, 2])
                        
                        with col1:
                            # Display 2D structure
                            if "smiles" in variant and not pd.isna(variant["smiles"]):
                                mol_img = render_mol(variant["smiles"])
                                if mol_img:
                                    st.image(mol_img, caption="2D Structure", use_container_width=True)
                                else:
                                    st.info("Could not render molecule structure")
                            else:
                                st.info("No SMILES data available for this variant")
                            
                            # If parent molecule exists, display it for comparison
                            has_parent_data = "parent_id" in variant and not pd.isna(variant["parent_id"])
                            
                            if has_parent_data:
                                st.subheader("Parent Structure")
                                if "source_smiles" in variant and not pd.isna(variant["source_smiles"]):
                                    parent_mol_img = render_mol(variant["source_smiles"])
                                    if parent_mol_img:
                                        st.image(parent_mol_img, caption="Parent Structure", use_container_width=True)
                                    else:
                                        st.info("Could not render parent molecule structure")
                                else:
                                    # Try to find parent SMILES in the dataframe
                                    parent_id = variant.get("parent_id", "")
                                    if parent_id and parent_id in df["compound_id"].values:
                                        parent_smiles = df[df["compound_id"] == parent_id]["smiles"].values[0]
                                        parent_mol_img = render_mol(parent_smiles)
                                        if parent_mol_img:
                                            st.image(parent_mol_img, caption="Parent Structure", use_container_width=True)
                                    else:
                                        st.info("Parent structure not available")
                        
                        with col2:
                            # Variant details
                            details = {
                                "Variant ID": variant.get("variant_id", ""),
                                "Status": variant.get("status", ""),
                                "Generation": variant.get("generation", ""),
                                "Round": variant.get("round", ""),
                                "Source": variant.get("source", "")
                            }
                            
                            # Only add optional fields if they exist and are not NA
                            if "parent_id" in variant and not pd.isna(variant["parent_id"]):
                                details["Parent Compound"] = variant["parent_id"]
                            
                            if "timestamp" in variant and not pd.isna(variant["timestamp"]):
                                details["Timestamp"] = variant["timestamp"]
                                
                            if "score" in variant and not pd.isna(variant["score"]):
                                details["Retrosynthesis Score"] = variant["score"]
                                
                            st.json(details)
                            
                            # Link to parent only if parent_id exists and is valid
                            if "parent_id" in variant and not pd.isna(variant["parent_id"]):
                                parent_id = variant.get("parent_id", "")
                                if parent_id and parent_id in df["compound_id"].values:
                                    parent_smiles = df[df["compound_id"] == parent_id]["smiles"].values[0]
                                    st.markdown(f"**Parent SMILES**: `{parent_smiles}`")
                                    
                            # Show docking results if available
                            if variant.get("status") == "DOCKED" and "docking_score" in variant and not pd.isna(variant["docking_score"]):
                                st.success(f"Docking Score: {variant['docking_score']:.2f}")
                                if "best_pose" in variant and not pd.isna(variant["best_pose"]):
                                    st.info(f"Best Pose: {variant['best_pose']}")
    
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
                    
                score_range_dock = st.slider(
                    "Docking Score Range",
                    min_value=min_score,
                    max_value=max_score,
                    value=(min_score, max_score),
                    key="docking_score_range"
                )
            
            # Filter docked compounds
            try:
                docked_df = df[
                    (df["status"] == "DOCKED") &
                    (df["round"].isin(selected_rounds_dock)) &
                    (df["docking_score"] >= score_range_dock[0]) &
                    (df["docking_score"] <= score_range_dock[1])
                ].sort_values("docking_score")
            except Exception as e:
                st.error(f"Error filtering docked compounds: {e}")
                docked_df = pd.DataFrame()
            
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
                
                # Top results
                st.subheader("Top Docking Results")
                
                # Add pagination for large datasets
                if len(docked_df) > 10:
                    top_n = st.slider("Show top N results", 5, min(30, len(docked_df)), 10, key="docking_top_n")
                    top_results = docked_df.head(top_n)
                else:
                    top_results = docked_df
                
                for _, result in top_results.iterrows():
                    # Use variant_id if available, otherwise fallback to compound_id
                    display_id = result.get('variant_id', result.get('compound_id', 'Unknown'))
                    
                    with st.expander(f"{display_id} (Score: {result.get('docking_score', 0):.2f})"):
                        col1, col2 = st.columns([1, 2])
                        with col1:
                            mol_img = render_mol(result["smiles"])
                            if mol_img:
                                st.image(mol_img, caption="2D Structure", use_container_width=True)
                            else:
                                st.info("Could not render molecule structure")
                        with col2:
                            # Use .get() for safer access to ensure no KeyError if fields are missing
                            details = {
                                "Compound ID": result.get("compound_id", ""),
                                "Variant ID": result.get("variant_id", ""),
                                "Barcode": result.get("barcode", ""),
                                "Round": result.get("round", ""),
                                "Docking Score": result.get("docking_score", ""),
                                "SMILES": result.get("smiles", "")
                            }
                            
                            # Only add best_pose if it exists
                            if "best_pose" in result and not pd.isna(result["best_pose"]):
                                details["Best Pose"] = result["best_pose"]
                                
                            st.json(details)
                            
                            # Download options for 3D files
                            if "barcode" in result and not pd.isna(result.get("barcode")) and "round" in result:
                                try:
                                    # Safely handle non-existent directories
                                    variant_dir = Path(st.session_state.output_dir) / f"round_{result['round']}" / "docking_results" / f"variant_{result['barcode']}"
                                    
                                    has_valid_pose = False
                                    pose_file = None
                                    
                                    # Only try to parse best_pose if the field exists
                                    if "best_pose" in result and not pd.isna(result["best_pose"]):
                                        try:
                                            best_pose_num = int(float(result["best_pose"]))
                                            pose_file = variant_dir / f"pose_{best_pose_num}.pdbqt"
                                            if pose_file.exists():
                                                has_valid_pose = True
                                        except (ValueError, TypeError):
                                            # If conversion fails, we'll look for any pose files below
                                            pass
                                    
                                    # Get receptor file path from the input directory
                                    receptor_file = Path(st.session_state.output_dir).parent / "input" / "NS5_test.pdbqt"
                                    
                                    # Check if pose file exists and we can actually read it
                                    if has_valid_pose and pose_file.exists():
                                        try:
                                            with open(pose_file, 'rb') as f:
                                                pose_data = f.read()
                                            
                                            # Download buttons for the best pose and receptor
                                            st.download_button(
                                                "Download Best Pose",
                                                data=pose_data,
                                                file_name=pose_file.name,
                                                mime="application/octet-stream",
                                                key=f"dl_best_pose_{display_id}"
                                            )
                                            
                                            if receptor_file.exists():
                                                with open(receptor_file, 'rb') as f:
                                                    receptor_data = f.read()
                                                
                                                st.download_button(
                                                    "Download Receptor File",
                                                    data=receptor_data,
                                                    file_name=receptor_file.name,
                                                    mime="application/octet-stream",
                                                    key=f"dl_receptor_best_{display_id}"
                                                )
                                        except Exception as e:
                                            st.error(f"Error reading pose file: {e}")
                                    else:
                                        # Try to find all available pose files in the variant directory
                                        if variant_dir.exists():
                                            try:
                                                pose_files = list(variant_dir.glob("pose_*.pdbqt"))
                                                if pose_files:
                                                    st.info(f"Found {len(pose_files)} pose files")
                                                    
                                                    # Extract pose numbers and sort them
                                                    pose_numbers = []
                                                    for p in pose_files:
                                                        try:
                                                            # Extract number from pose_X.pdbqt
                                                            pose_num = int(p.stem.split('_')[1])
                                                            pose_numbers.append((pose_num, p))
                                                        except (ValueError, IndexError):
                                                            continue
                                                    
                                                    if pose_numbers:
                                                        # Sort poses by number
                                                        pose_numbers.sort()
                                                        sorted_poses = [p[1] for p in pose_numbers]
                                                        
                                                        # Create a selection for the poses
                                                        pose_options = [f"Pose {p[0]}" for p in pose_numbers]
                                                        selected_pose_idx = st.selectbox(
                                                            "Select pose", 
                                                            range(len(pose_options)),
                                                            format_func=lambda i: pose_options[i],
                                                            key=f"pose_select_{display_id}"
                                                        )
                                                        
                                                        selected_file = sorted_poses[selected_pose_idx]
                                                        
                                                        try:
                                                            with open(selected_file, 'rb') as f:
                                                                pose_data = f.read()
                                                                
                                                            # Download buttons for the selected pose and receptor
                                                            st.download_button(
                                                                "Download Selected Pose",
                                                                data=pose_data,
                                                                file_name=selected_file.name,
                                                                mime="application/octet-stream",
                                                                key=f"dl_pose_{display_id}"
                                                            )
                                                            
                                                            if receptor_file.exists():
                                                                with open(receptor_file, 'rb') as f:
                                                                    receptor_data = f.read()
                                                                    
                                                                st.download_button(
                                                                    "Download Receptor File",
                                                                    data=receptor_data,
                                                                    file_name=receptor_file.name,
                                                                    mime="application/octet-stream",
                                                                    key=f"dl_receptor_{display_id}"
                                                                )
                                                        except Exception as file_err:
                                                            st.error(f"Error reading pose file: {file_err}")
                                                    else:
                                                        st.info("No valid pose files found")
                                                else:
                                                    st.info(f"No pose files found in {variant_dir}")
                                            except Exception as e:
                                                st.error(f"Error accessing pose files: {e}")
                                        else:
                                            st.info(f"Variant directory not found: {variant_dir}. Docking results may still be processing.")
                                except Exception as e:
                                    st.error(f"Error processing docking results: {e}")
                            else:
                                st.info("Barcode or round information missing for 3D structure visualization")
    
    # Export options
    st.divider()
    st.subheader("Export Options")
    
    # Add download button for complete dataset
    if st.button("Export All Results"):
        st.download_button(
            "📥 Download Complete Dataset",
            data=df.to_csv(index=False).encode('utf-8'),
            file_name="all_results.csv",
            mime="text/csv"
        )
else:
    st.info("Please select an output directory and load results to view visualizations.") 