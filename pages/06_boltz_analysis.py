import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
from pathlib import Path
import logging
from typing import Dict, List, Optional, Tuple
import py3Dmol
import streamlit.components.v1 as components
from Bio.PDB.MMCIFParser import MMCIFParser
import tempfile
from stmol import showmol

# Set up logging
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Boltz-2 Analysis",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Add custom CSS for better styling
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
    .metric-container {
        background-color: #2d3748;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .status-pass {
        color: #48bb78;
        font-weight: bold;
    }
    .status-fail {
        color: #f56565;
        font-weight: bold;
    }
    .confidence-high {
        color: #48bb78;
    }
    .confidence-medium {
        color: #ed8936;
    }
    .confidence-low {
        color: #f56565;
    }
    .metric-card {
        background-color: #2d3748;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #63b3ed;
    }
    .success-card {
        background-color: #1a202c;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #48bb78;
    }
    .warning-card {
        background-color: #1a202c;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #ed8936;
    }
    .error-card {
        background-color: #1a202c;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #f56565;
    }
    .info-box {
        background-color: #1a202c;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #63b3ed;
        margin: 1rem 0;
    }
    .placeholder-box {
        background-color: #2d3748;
        padding: 2rem;
        border-radius: 0.5rem;
        border: 2px dashed #4a5568;
        text-align: center;
        margin: 1rem 0;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        padding-left: 20px;
        padding-right: 20px;
    }
    </style>
""", unsafe_allow_html=True)

def load_tracking_data(results_dir: Path) -> pd.DataFrame:
    """Load tracking data from master or round-specific reports."""
    tracking_files = []
    
    # Look for master tracking report
    master_file = results_dir / "master_tracking" / "master_compound_tracking_report.csv"
    if master_file.exists():
        tracking_files.append(master_file)
    
    # Look for round-specific tracking reports
    for round_dir in results_dir.glob("round_*"):
        round_file = round_dir / f"{round_dir.name}_tracking_report.csv"
        if round_file.exists():
            tracking_files.append(round_file)
    
    if not tracking_files:
        return pd.DataFrame()
    
    # Load and combine all tracking data
    dfs = []
    for file in tracking_files:
        try:
            df = pd.read_csv(file)
            dfs.append(df)
        except Exception as e:
            logger.warning(f"Could not load tracking file {file}: {e}")
    
    if not dfs:
        return pd.DataFrame()
    
    combined_df = pd.concat(dfs, ignore_index=True)
    # Remove duplicates based on barcode (keep the most recent entry)
    combined_df = combined_df.drop_duplicates(subset=['barcode'], keep='last')
    
    return combined_df

def load_boltz_results(results_dir: Path) -> pd.DataFrame:
    """Load Boltz-2 results from the results directory."""
    boltz_data = []
    
    # Look for Boltz results in each round
    for round_dir in results_dir.glob("round_*"):
        boltz_dir = round_dir / "Boltz_result"
        if not boltz_dir.exists():
            continue
            
        for variant_dir in boltz_dir.iterdir():
            if not variant_dir.is_dir():
                continue
                
            barcode = variant_dir.name
            variant_results = {
                'barcode': barcode,
                'round': round_dir.name,
                'variant_dir': str(variant_dir),
                'has_structure': False
            }
            
            # Load affinity data
            affinity_file = variant_dir / "predictions" / "input" / "affinity_input.json"
            if affinity_file.exists():
                try:
                    with open(affinity_file, 'r') as f:
                        affinity_data = json.load(f)
                        # Flatten affinity data into the main record
                        for key, value in affinity_data.items():
                            variant_results[key] = value
                except Exception as e:
                    st.warning(f"Could not load affinity data for {barcode}: {e}")
            
            # Load confidence data
            confidence_file = variant_dir / "predictions" / "input" / "confidence_input_model_0.json"
            if confidence_file.exists():
                try:
                    with open(confidence_file, 'r') as f:
                        confidence_data = json.load(f)
                        # Flatten confidence data into the main record
                        for key, value in confidence_data.items():
                            variant_results[key] = value
                except Exception as e:
                    st.warning(f"Could not load confidence data for {barcode}: {e}")
            
            # Check for CIF file
            cif_file = variant_dir / "predictions" / "input" / "input_model_0.cif"
            if cif_file.exists():
                variant_results['cif_file'] = str(cif_file)
                variant_results['has_structure'] = True
            
            boltz_data.append(variant_results)
    
    return pd.DataFrame(boltz_data) if boltz_data else pd.DataFrame()

def create_affinity_distribution_plot(df: pd.DataFrame) -> go.Figure:
    """Create a distribution plot of affinity predictions."""
    if 'affinity_pred_value' not in df.columns or df['affinity_pred_value'].isna().all():
        return go.Figure().add_annotation(text="No affinity data available", 
                                        xref="paper", yref="paper", x=0.5, y=0.5)
    
    fig = px.histogram(
        df, 
        x='affinity_pred_value',
        nbins=30,
        title='Distribution of Boltz-2 Affinity Predictions',
        labels={'affinity_pred_value': 'Affinity Prediction Value', 'count': 'Number of Variants'},
        color_discrete_sequence=['#63b3ed']
    )
    
    fig.update_layout(
        xaxis_title="Affinity Prediction Value",
        yaxis_title="Count",
        showlegend=False
    )
    
    return fig

def create_affinity_scatter_plot(df: pd.DataFrame) -> go.Figure:
    """Create a scatter plot of affinity prediction value vs affinity probability binary."""
    if 'affinity_pred_value' not in df.columns or 'affinity_probability_binary' not in df.columns:
        return go.Figure().add_annotation(text="Insufficient data for affinity vs probability plot", 
                                        xref="paper", yref="paper", x=0.5, y=0.5)
    
    # Filter out NaN values
    plot_df = df.dropna(subset=['affinity_pred_value', 'affinity_probability_binary'])
    
    if plot_df.empty:
        return go.Figure().add_annotation(text="No valid data points for plotting", 
                                        xref="paper", yref="paper", x=0.5, y=0.5)
    
    # Color by status if available, otherwise use probability ranges
    if 'status' in plot_df.columns:
        color_map = {
            'PASSBLINDDOCK': '#48bb78',
            'FAILBLINDDOCK': '#f56565',
            'BOLTZFAIL_PREDICT': '#ed8936',
            'BOLTZFAIL_NOCIF': '#e53e3e'
        }
        
        fig = px.scatter(
            plot_df,
            x='affinity_pred_value',
            y='affinity_probability_binary',
            color='status',
            hover_data=['barcode'] if 'barcode' in plot_df.columns else None,
            title='Affinity Prediction Value vs Probability Binary',
            color_discrete_map=color_map
        )
    else:
        # Create probability categories for coloring
        plot_df['prob_category'] = pd.cut(
            plot_df['affinity_probability_binary'], 
            bins=[0, 0.3, 0.5, 0.7, 1.0], 
            labels=['Low (0-0.3)', 'Moderate (0.3-0.5)', 'High (0.5-0.7)', 'Very High (0.7-1.0)']
        )
        
        fig = px.scatter(
            plot_df,
            x='affinity_pred_value',
            y='affinity_probability_binary',
            color='prob_category',
            hover_data=['barcode'] if 'barcode' in plot_df.columns else None,
            title='Affinity Prediction Value vs Probability Binary',
            color_discrete_map={
                'Low (0-0.3)': '#fc8181',
                'Moderate (0.3-0.5)': '#f6ad55', 
                'High (0.5-0.7)': '#63b3ed',
                'Very High (0.7-1.0)': '#68d391'
            }
        )
    
    # Add reference lines for IC50 categories
    fig.add_vline(x=-3, line_dash="dash", line_color="darkgreen", line_width=1,
                  annotation_text="Strong Binder (IC50 < 1nM)", 
                  annotation_position="top")
    
    fig.add_vline(x=0, line_dash="dash", line_color="orange", line_width=1,
                  annotation_text="Moderate Binder (IC50 = 1μM)", 
                  annotation_position="top")
    
    fig.add_vline(x=2, line_dash="dash", line_color="darkred", line_width=1,
                  annotation_text="Weak Binder (IC50 > 100μM)", 
                  annotation_position="top")
    
    # Add horizontal line at 0.5 probability threshold
    fig.add_hline(y=0.5, line_dash="dot", line_color="purple", line_width=1,
                  annotation_text="Hit Detection Threshold", 
                  annotation_position="left")
    
    # Add trend line
    if len(plot_df) > 1:
        try:
            # Add trendline
            z = np.polyfit(plot_df['affinity_pred_value'], plot_df['affinity_probability_binary'], 1)
            p = np.poly1d(z)
            x_trend = np.linspace(plot_df['affinity_pred_value'].min(), plot_df['affinity_pred_value'].max(), 100)
            y_trend = p(x_trend)
            
            fig.add_trace(go.Scatter(
                x=x_trend, y=y_trend,
                mode='lines',
                name='Trend Line',
                line=dict(color='red', width=2, dash='dash'),
                showlegend=True
            ))
        except:
            pass  # Skip trendline if calculation fails
    
    fig.update_layout(
        xaxis_title="Affinity Prediction Value (log scale, more negative = stronger)",
        yaxis_title="Affinity Probability Binary (0-1, >0.5 = potential hit)",
        height=600,
        showlegend=True
    )
    
    # Add informative subtitle
    high_prob_count = len(plot_df[plot_df['affinity_probability_binary'] > 0.5])
    total_count = len(plot_df)
    
    fig.update_layout(
        title=dict(
            text=(
                f"Affinity Prediction Value vs Probability Binary<br>"
                f"<sub>n = {total_count} compounds | "
                f"{high_prob_count} potential hits ({high_prob_count/total_count*100:.1f}%)</sub>"
            ),
            x=0.5
        )
    )
    
    return fig

def create_status_summary_plot(df: pd.DataFrame) -> go.Figure:
    """Create a summary plot of Boltz-2 status results."""
    if 'status' not in df.columns:
        return go.Figure().add_annotation(text="No status data available", 
                                        xref="paper", yref="paper", x=0.5, y=0.5)
    
    # Filter for Boltz-related statuses
    boltz_statuses = df[df['status'].str.contains('BOLTZ|BLINDDOCK', na=False)]
    
    if boltz_statuses.empty:
        return go.Figure().add_annotation(text="No Boltz-2 results found", 
                                        xref="paper", yref="paper", x=0.5, y=0.5)
    
    status_counts = boltz_statuses['status'].value_counts()
    
    # Define colors for different statuses
    colors = {
        'PASSBLINDDOCK': '#48bb78',
        'FAILBLINDDOCK': '#f56565',
        'BOLTZFAIL_PREDICT': '#ed8936',
        'BOLTZFAIL_NOCIF': '#e53e3e',
        'BOLTZFAIL_ERROR': '#c53030',
        'BOLTZFAIL_NOSMILES': '#fc8181',
        'BOLTZFAIL_PROTEIN_SEQUENCE': '#e53e3e'
    }
    
    fig = go.Figure(data=[
        go.Bar(
            x=status_counts.index,
            y=status_counts.values,
            marker_color=[colors.get(status, '#63b3ed') for status in status_counts.index]
        )
    ])
    
    fig.update_layout(
        title='Boltz-2 Processing Status Summary',
        xaxis_title='Status',
        yaxis_title='Count',
        xaxis={'tickangle': 45}
    )
    
    return fig

def create_correlation_heatmap(df: pd.DataFrame) -> go.Figure:
    """Create a correlation heatmap of Boltz-2 metrics."""
    numeric_cols = ['affinity_pred_value', 'affinity_probability_binary', 'confidence_score', 
                   'ptm', 'iptm', 'ligand_iptm', 'protein_iptm', 'complex_plddt', 'complex_iplddt']
    
    available_cols = [col for col in numeric_cols if col in df.columns and not df[col].isna().all()]
    
    if len(available_cols) < 2:
        return go.Figure().add_annotation(text="Insufficient numeric data for correlation analysis", 
                                        xref="paper", yref="paper", x=0.5, y=0.5)
    
    # Calculate correlation matrix
    corr_matrix = df[available_cols].corr()
    
    # Create heatmap
    fig = go.Figure(data=go.Heatmap(
        z=corr_matrix.values,
        x=corr_matrix.columns,
        y=corr_matrix.columns,
        colorscale='RdBu',
        zmid=0,
        text=corr_matrix.round(3).values,
        texttemplate="%{text}",
        textfont={"size": 10},
        hoverongaps=False
    ))
    
    fig.update_layout(
        title='Correlation Matrix of Boltz-2 Metrics',
        xaxis_title='Metrics',
        yaxis_title='Metrics',
        width=600,
        height=600
    )
    
    return fig

def create_round_comparison_plot(df: pd.DataFrame) -> go.Figure:
    """Create a comparison plot across different rounds."""
    if 'round' not in df.columns or 'affinity_pred_value' not in df.columns:
        return go.Figure().add_annotation(text="Insufficient data for round comparison", 
                                        xref="paper", yref="paper", x=0.5, y=0.5)
    
    # Group by round and calculate statistics
    round_stats = df.groupby('round')['affinity_pred_value'].agg(['mean', 'std', 'count']).reset_index()
    
    if round_stats.empty:
        return go.Figure().add_annotation(text="No round data available", 
                                        xref="paper", yref="paper", x=0.5, y=0.5)
    
    fig = go.Figure()
    
    # Add mean line with error bars
    fig.add_trace(go.Scatter(
        x=round_stats['round'],
        y=round_stats['mean'],
        error_y=dict(type='data', array=round_stats['std']),
        mode='lines+markers',
        name='Mean Affinity ± Std',
        line=dict(color='blue', width=2),
        marker=dict(size=8)
    ))
    
    fig.update_layout(
        title='Affinity Predictions Across Rounds',
        xaxis_title='Round',
        yaxis_title='Mean Affinity Prediction Value',
        showlegend=True
    )
    
    return fig

def visualize_structure_3d(cif_file: Path, barcode: str) -> str:
    """Create a 3D visualization of the Boltz-2 predicted structure."""
    try:
        # Read CIF file content
        with open(cif_file, 'r') as f:
            cif_content = f.read()
        
        # Create py3Dmol viewer
        view = py3Dmol.view(width=800, height=600)
        view.addModel(cif_content, "cif")
        
        # Style the protein (chain A) and ligand (chain B)
        view.setStyle({'chain': 'A'}, {'cartoon': {'color': 'lightblue'}})
        view.setStyle({'chain': 'B'}, {'stick': {'color': 'red'}, 'sphere': {'color': 'red', 'radius': 0.5}})
        
        # Add labels
        view.addLabel(f"Protein", {'fontColor':'blue', 'backgroundColor': 'white', 'showBackground': True}, {'chain': 'A'})
        view.addLabel(f"Ligand ({barcode})", {'fontColor':'red', 'backgroundColor': 'white', 'showBackground': True}, {'chain': 'B'})
        
        view.zoomTo()
        view.render()
        
        return view._make_html()
        
    except Exception as e:
        logger.error(f"Error creating 3D visualization for {barcode}: {e}")
        return f"<p>Error loading 3D structure: {e}</p>"

def format_confidence_score(score: float) -> str:
    """Format confidence score with color coding."""
    if pd.isna(score):
        return "N/A"
    
    if score >= 0.8:
        return f'<span class="confidence-high">{score:.3f}</span>'
    elif score >= 0.6:
        return f'<span class="confidence-medium">{score:.3f}</span>'
    else:
        return f'<span class="confidence-low">{score:.3f}</span>'

def format_status(status: str) -> str:
    """Format status with color coding."""
    if 'PASS' in status:
        return f'<span class="status-pass">{status}</span>'
    elif 'FAIL' in status:
        return f'<span class="status-fail">{status}</span>'
    else:
        return status

# Add the missing load_all_data function
@st.cache_data(ttl=10)
def load_all_data(outputs_path: str):
    """Load all data with caching."""
    outputs_path_obj = Path(outputs_path)
    if not outputs_path_obj.exists():
        return pd.DataFrame(), pd.DataFrame()
    
    tracking_df = load_tracking_data(outputs_path_obj)
    boltz_df = load_boltz_results(outputs_path_obj)
    return tracking_df, boltz_df

# Main Streamlit App
def main():
    # Page header
    st.title("🧬 Boltz-2 Analysis Dashboard")
    st.markdown("Comprehensive analysis of Boltz-2 blind-docking predictions and affinity data")
    
    # Sidebar configuration
    st.sidebar.title("⚙️ Configuration")
    
    # Directory input
    st.sidebar.subheader("📂 Data Source")
    results_dir_path = st.sidebar.text_input(
        "Pipeline Outputs Directory",
        value="/media/data/conrad_hku/NS5_350_10_2",  # Default example path
        help="Path to the directory containing your pipeline outputs with round_* folders"
    )
    
    # Refresh controls
    st.sidebar.subheader("🔄 Refresh")
    if st.sidebar.button("Refresh data now"):
        try:
            load_all_data.clear()
        except Exception:
            pass
        st.rerun()

    # Educational information box
    st.markdown("""
    <div class="info-box">
        <h4>📚 Understanding Boltz-2 Affinity Predictions</h4>
        <p><strong>Boltz-2 provides two types of affinity predictions:</strong></p>
        <ul>
            <li><strong>affinity_probability_binary:</strong> Binary classification probability (0-1) for hit identification. Values > 0.5 suggest potential binding activity.</li>
            <li><strong>affinity_pred_value:</strong> Continuous affinity prediction value for lead optimization. More negative values indicate stronger predicted binding.</li>
        </ul>
        <p><strong>IC50 Reference Scale:</strong></p>
        <ul>
            <li><strong>Strong Binders (IC50 < 1 µM):</strong> affinity_pred_value < -3</li>
            <li><strong>Moderate Binders (1-100 µM):</strong> affinity_pred_value: -3 to 0</li>
            <li><strong>Weak Binders (> 100 µM):</strong> affinity_pred_value > 0</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)
    
    if not results_dir_path or not Path(results_dir_path).exists():
        st.markdown("""
        <div class="placeholder-box">
            <h3>🔍 Welcome to Boltz-2 Analysis</h3>
            <p>To get started, please:</p>
            <ol>
                <li>Enter the path to your pipeline outputs directory in the sidebar</li>
                <li>Ensure your directory contains <code>round_*</code> folders with Boltz-2 results</li>
                <li>The analysis will automatically load and display your data</li>
            </ol>
            <p><strong>Expected directory structure:</strong></p>
            <pre>
outputs/
├── master_tracking/
│   └── master_compound_tracking_report.csv
├── round_1/
│   ├── Boltz_result/
│   │   └── [variant_barcodes]/
│   │       └── boltz_results_input/predictions/input/
│   │           ├── affinity_input.json
│   │           ├── confidence_input_model_0.json
│   │           └── input_model_0.cif
│   └── round_1_tracking_report.csv
└── round_2/
    └── ...
            </pre>
        </div>
        """, unsafe_allow_html=True)
        return
    
    # Load data
    with st.spinner("Loading pipeline data..."):
        tracking_df, boltz_df = load_all_data(results_dir_path)
    
    if tracking_df.empty and boltz_df.empty:
        st.markdown("""
        <div class="error-card">
            <h4>❌ No Data Found</h4>
            <p>No tracking data or Boltz-2 results found in the specified directory.</p>
            <p><strong>Please check:</strong></p>
            <ul>
                <li>The directory path is correct</li>
                <li>The directory contains <code>round_*</code> subdirectories</li>
                <li>Boltz-2 analysis has been run on your pipeline results</li>
                <li>The file structure matches the expected format</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        return
    
    # Merge tracking and Boltz data if both are available
    if not tracking_df.empty and not boltz_df.empty and 'barcode' in tracking_df.columns:
        merged_df = pd.merge(tracking_df, boltz_df, on='barcode', how='outer', suffixes=('_tracking', '_boltz'))
    elif not boltz_df.empty:
        merged_df = boltz_df
    else:
        merged_df = tracking_df
    
    # Sidebar filters
    st.sidebar.subheader("🔧 Filters")
    
    # Round selection
    if 'round' in merged_df.columns:
        available_rounds = sorted(merged_df['round'].dropna().unique())
        if available_rounds:
            selected_rounds = st.sidebar.multiselect(
                "Select Rounds",
                available_rounds,
                default=available_rounds[-3:] if len(available_rounds) > 3 else available_rounds,
                help="Select which rounds to include in the analysis"
            )
        else:
            selected_rounds = []
    else:
        selected_rounds = []
        st.sidebar.info("No round information available")
    
    # Status filter
    if 'status' in merged_df.columns:
        available_statuses = merged_df['status'].dropna().unique()
        selected_statuses = st.sidebar.multiselect(
            "Filter by Status",
            available_statuses,
            default=available_statuses,
            help="Filter compounds by their processing status"
        )
    else:
        selected_statuses = []
        st.sidebar.info("No status information available")
    
    # Affinity thresholds
    st.sidebar.subheader("📈 Affinity Thresholds")
    if 'affinity_probability_binary' in merged_df.columns:
        prob_threshold = st.sidebar.slider(
            "Probability Binary Threshold",
            0.0, 1.0, 0.5, 0.05,
            help="Minimum probability for hit identification"
        )
    else:
        prob_threshold = 0.5
        st.sidebar.info("No probability data available")
    
    if 'affinity_pred_value' in merged_df.columns:
        pred_threshold = st.sidebar.slider(
            "Pred Value Threshold",
            -5.0, 5.0, 0.0, 0.1,
            help="Maximum pred value for strong binding"
        )
    else:
        pred_threshold = 0.0
        st.sidebar.info("No pred value data available")
    
    # Confidence threshold
    if 'confidence_score' in merged_df.columns:
        conf_threshold = st.sidebar.slider(
            "Confidence Score Threshold",
            0.0, 1.0, 0.7, 0.05,
            help="Minimum confidence score for reliable predictions"
        )
    else:
        conf_threshold = 0.7
        st.sidebar.info("No confidence data available")
    
    # Apply filters
    filtered_df = merged_df.copy()
    
    if selected_rounds and 'round' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['round'].isin(selected_rounds)]
    
    if selected_statuses and 'status' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['status'].isin(selected_statuses)]
    
    # Data summary
    st.sidebar.subheader("📊 Data Summary")
    total_compounds = len(filtered_df)
    
    if not filtered_df.empty:
        if 'affinity_probability_binary' in filtered_df.columns:
            high_prob_count = len(filtered_df[filtered_df['affinity_probability_binary'] > prob_threshold])
            st.sidebar.metric("High Probability Hits", f"{high_prob_count}/{total_compounds}")
        
        if 'confidence_score' in filtered_df.columns:
            high_conf_count = len(filtered_df[filtered_df['confidence_score'] > conf_threshold])
            st.sidebar.metric("High Confidence", f"{high_conf_count}/{total_compounds}")
        
        if 'has_structure' in filtered_df.columns:
            structure_count = len(filtered_df[filtered_df['has_structure'] == True])
            st.sidebar.metric("Available Structures", f"{structure_count}/{total_compounds}")
    else:
        st.sidebar.metric("Total Compounds", "0")
    
    # Main tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "🔬 Detailed Analysis", "🧬 Structure Viewer", "📥 Data Export"])
    
    with tab1:
        st.header("📊 Analysis Overview")
        
        if filtered_df.empty:
            st.markdown("""
            <div class="placeholder-box">
                <h4>📭 No Data to Display</h4>
                <p>No compounds match the current filter criteria.</p>
                <p>Try adjusting the filters in the sidebar or check your data source.</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            # Key metrics
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Total Compounds", len(filtered_df))
            
            with col2:
                if 'affinity_probability_binary' in filtered_df.columns:
                    hits = len(filtered_df[filtered_df['affinity_probability_binary'] > prob_threshold])
                    st.metric("Potential Hits", hits, f"{hits/len(filtered_df)*100:.1f}%")
                else:
                    st.metric("Potential Hits", "N/A")
            
            with col3:
                if 'confidence_score' in filtered_df.columns:
                    avg_conf = filtered_df['confidence_score'].mean()
                    st.metric("Avg Confidence", f"{avg_conf:.3f}")
                else:
                    st.metric("Avg Confidence", "N/A")
            
            with col4:
                if 'round' in filtered_df.columns:
                    rounds = filtered_df['round'].nunique()
                    st.metric("Rounds Analyzed", rounds)
                else:
                    st.metric("Rounds Analyzed", "N/A")
            
            # Status distribution
            col1, col2 = st.columns(2)
            
            with col1:
                st.plotly_chart(create_status_summary_plot(filtered_df), use_container_width=True, key="status_summary_overview")
            
            with col2:
                st.plotly_chart(create_round_comparison_plot(filtered_df), use_container_width=True, key="round_comparison_overview")
    
    with tab2:
        st.header("🔬 Detailed Analysis")
        
        if filtered_df.empty:
            st.markdown("""
            <div class="placeholder-box">
                <h4>📭 No Data for Detailed Analysis</h4>
                <p>Load pipeline data to see detailed affinity and confidence analysis.</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            # Affinity distributions
            col1, col2 = st.columns(2)
            
            with col1:
                fig1 = create_affinity_distribution_plot(filtered_df)
                st.plotly_chart(fig1, use_container_width=True, key="affinity_distribution_detailed")
            
            with col2:
                fig2 = create_affinity_scatter_plot(filtered_df)
                st.plotly_chart(fig2, use_container_width=True, key="affinity_scatter_detailed")
            
            # Correlation heatmap
            st.plotly_chart(create_correlation_heatmap(filtered_df), use_container_width=True, key="correlation_heatmap_detailed")
            
            # Statistical summary
            st.subheader("📈 Statistical Summary")
            
            if not filtered_df.empty:
                numeric_cols = ['affinity_pred_value', 'affinity_probability_binary', 'confidence_score', 
                               'ptm', 'iptm', 'complex_plddt']
                available_cols = [col for col in numeric_cols if col in filtered_df.columns]
                
                if available_cols:
                    summary_stats = filtered_df[available_cols].describe()
                    st.dataframe(summary_stats, use_container_width=True)
                else:
                    st.info("No numeric columns available for statistical summary")
    
    with tab3:
        st.header("🧬 3D Structure Viewer")
        
        if filtered_df.empty or 'has_structure' not in filtered_df.columns:
            st.markdown("""
            <div class="placeholder-box">
                <h4>🔬 No 3D Structures Available</h4>
                <p>3D structure visualization requires:</p>
                <ul>
                    <li>Boltz-2 predictions with CIF files</li>
                    <li>Completed pipeline runs with structure generation</li>
                    <li>Valid structure files in the expected locations</li>
                </ul>
                <p>Run Boltz-2 analysis on your compounds to generate 3D structures.</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            # Filter for variants with structures
            structure_df = filtered_df[filtered_df['has_structure'] == True]
            
            if structure_df.empty:
                st.markdown("""
                <div class="warning-card">
                    <h4>⚠️ No Structures in Current Selection</h4>
                    <p>No 3D structures are available for the currently filtered compounds.</p>
                    <p>Try adjusting your filters or ensure Boltz-2 analysis has completed successfully.</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                # Variant selection
                variant_options = structure_df['barcode'].tolist()
                selected_variant = st.selectbox("Select Variant to Visualize", variant_options)
                
                if selected_variant:
                    variant_row = structure_df[structure_df['barcode'] == selected_variant].iloc[0]
                    cif_file = variant_row['cif_file']
                    
                    # Display variant information
                    variant_info = variant_row.to_dict()
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader("Variant Information")
                        st.write(f"**Barcode:** {selected_variant}")
                        st.write(f"**Round:** {variant_info.get('round', 'Unknown')}")
                        
                        # Display affinity data
                        if 'affinity_pred_value' in variant_info:
                            st.write("**Affinity Predictions:**")
                            st.write(f"  - Pred Value: {variant_info['affinity_pred_value']:.4f}")
                        if 'affinity_probability_binary' in variant_info:
                            st.write(f"  - Probability: {variant_info['affinity_probability_binary']:.4f}")
                    
                    with col2:
                        # Display confidence data
                        if 'confidence_score' in variant_info:
                            st.write("**Confidence Metrics:**")
                            st.write(f"  - Overall Score: {variant_info['confidence_score']:.4f}")
                        if 'ptm' in variant_info:
                            st.write(f"  - PTM: {variant_info['ptm']:.4f}")
                        if 'iptm' in variant_info:
                            st.write(f"  - iPTM: {variant_info['iptm']:.4f}")
                    
                    # 3D Structure visualization
                    st.subheader("3D Structure")
                    
                    if cif_file and Path(cif_file).exists():
                        try:
                            # Read CIF file
                            with open(cif_file, 'r') as f:
                                cif_content = f.read()
                            
                            # Create 3D viewer
                            view = py3Dmol.view(width=800, height=600)
                            view.addModel(cif_content, 'cif')
                            view.setStyle({'cartoon': {'color': 'spectrum'}})
                            view.addStyle({'resn': 'LIG'}, {'stick': {'colorscheme': 'greenCarbon'}})
                            view.zoomTo()
                            view.spin(True)
                            
                            showmol(view, height=600, width=800)
                            
                        except Exception as e:
                            st.error(f"Error loading 3D structure: {e}")
                            st.info("Please ensure the CIF file is valid and accessible.")
                    else:
                        st.warning("CIF file not found or inaccessible")
    
    with tab4:
        st.header("📥 Data Export")
        
        if filtered_df.empty:
            st.markdown("""
            <div class="placeholder-box">
                <h4>📤 No Data to Export</h4>
                <p>Load and filter your data to enable export functionality.</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.subheader("Export Options")
            
            # CSV export
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("📊 Export Filtered Data (CSV)", type="primary"):
                    csv = filtered_df.to_csv(index=False)
                    st.download_button(
                        label="Download CSV",
                        data=csv,
                        file_name=f"boltz_analysis_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
            
            with col2:
                # Summary statistics export
                if st.button("📈 Export Summary Statistics", type="secondary"):
                    numeric_cols = ['affinity_pred_value', 'affinity_probability_binary', 'confidence_score']
                    available_cols = [col for col in numeric_cols if col in filtered_df.columns]
                    
                    if available_cols:
                        summary = filtered_df[available_cols].describe()
                        csv = summary.to_csv()
                        st.download_button(
                            label="Download Summary CSV",
                            data=csv,
                            file_name=f"boltz_summary_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )
            
            # Data preview
            st.subheader("Data Preview")
            st.dataframe(filtered_df.head(100), use_container_width=True)
            
            if len(filtered_df) > 100:
                st.info(f"Showing first 100 rows of {len(filtered_df)} total compounds")

if __name__ == "__main__":
    main() 