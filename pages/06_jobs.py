import streamlit as st
import pandas as pd
from pathlib import Path
import json
from datetime import datetime
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.duckdb_store import DuckDBStore

# Function to get the central jobs database path
def get_central_jobs_db_path():
    """Get the path to the central jobs database in project root."""
    project_root = Path(__file__).resolve().parent.parent
    return project_root / "jobs.duckdb"

st.set_page_config(
    page_title="Pipeline Jobs",
    page_icon="📋",
    layout="wide"
)

# Add custom CSS
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
    .job-card {
        background-color: #f0f2f6;
        border: 1px solid #d1d5db;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 1rem;
        transition: all 0.3s ease;
    }
    .job-card:hover {
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        transform: translateY(-2px);
    }
    .job-card h3 {
        color: #1f2937;
        font-weight: 600;
        margin-top: 0;
    }
    .job-card p {
        color: #374151;
        margin: 0.5rem 0;
    }
    .job-card strong {
        color: #111827;
        font-weight: 600;
    }
    .job-card code {
        background-color: #1f2937;
        color: #f9fafb;
        padding: 0.2rem 0.4rem;
        border-radius: 4px;
        font-size: 0.9em;
    }
    .status-running { 
        color: #ea580c; 
        font-weight: bold;
        background-color: #fff7ed;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        display: inline-block;
    }
    .status-completed { 
        color: #16a34a; 
        font-weight: bold;
        background-color: #f0fdf4;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        display: inline-block;
    }
    .status-failed { 
        color: #dc2626; 
        font-weight: bold;
        background-color: #fef2f2;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        display: inline-block;
    }
    .status-stopped { 
        color: #64748b; 
        font-weight: bold;
        background-color: #f1f5f9;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        display: inline-block;
    }
    </style>
""", unsafe_allow_html=True)

st.title("📋 Pipeline Jobs")

st.markdown("""
    View and manage all your pipeline runs. Click on any job to view its results.
""")

# Initialize session state
if "jobs_refresh" not in st.session_state:
    st.session_state.jobs_refresh = False

# Function to scan for pipeline.duckdb files
def scan_for_pipeline_dbs(base_path=None, max_depth=3):
    """Scan for pipeline.duckdb files in common output locations."""
    if base_path is None:
        # Try common locations
        project_root = Path(__file__).resolve().parent.parent
        base_paths = [
            project_root,
            project_root / "outputs",
            Path.home() / "outputs",
            Path("/tmp")
        ]
    else:
        base_paths = [Path(base_path)]
    
    found_dbs = []
    for base in base_paths:
        if not base.exists():
            continue
        try:
            for db_file in base.rglob("pipeline.duckdb"):
                if db_file.is_file():
                    output_dir = db_file.parent
                    found_dbs.append((str(output_dir), str(db_file)))
        except Exception as e:
            st.warning(f"Error scanning {base}: {e}")
    
    return found_dbs

# Function to get all jobs from central DuckDB database
def get_all_jobs_from_central_db():
    """Collect all jobs from the central jobs database."""
    all_jobs = []
    
    # Get central jobs database path
    central_db_path = get_central_jobs_db_path()
    
    # Check if database exists
    if not central_db_path.exists():
        return all_jobs
    
    try:
        store = DuckDBStore(central_db_path)
        store.init_schema()  # Ensure schema exists
        jobs_df = store.get_all_jobs(limit=1000)
        
        if not jobs_df.empty:
            for _, row in jobs_df.iterrows():
                job_data = {
                    "job_id": row.get("job_id", "unknown"),
                    "job_name": row.get("job_name"),
                    "output_dir": row.get("output_dir", ""),
                    "status": row.get("status", "unknown"),
                    "created_at": row.get("created_at"),
                    "completed_at": row.get("completed_at"),
                    "user_id": row.get("user_id"),
                }
                
                # Parse parameters
                if pd.notna(row.get("parameters_json")):
                    try:
                        job_data["parameters"] = json.loads(row["parameters_json"])
                    except json.JSONDecodeError:
                        job_data["parameters"] = {}
                else:
                    job_data["parameters"] = {}
                
                all_jobs.append(job_data)
    except Exception as e:
        st.warning(f"Error reading from central jobs database: {e}")
    
    return all_jobs

# Sidebar filters
with st.sidebar:
    st.header("🔍 Filters")
    
    # Status filter
    status_filter = st.multiselect(
        "Filter by Status",
        options=["running", "completed", "failed", "stopped"],
        default=["running", "completed", "failed", "stopped"],
        key="jobs_status_filter"
    )
    
    # Model filter
    model_filter = st.multiselect(
        "Filter by Model",
        options=["diffsbdd", "pocket2mol", "cgflow"],
        default=["diffsbdd", "pocket2mol", "cgflow"],
        key="jobs_model_filter"
    )
    
    # Refresh button
    if st.button("🔄 Refresh Jobs List"):
        st.session_state.jobs_refresh = True
        st.rerun()

# Load jobs from central database
central_db_path = get_central_jobs_db_path()

if not central_db_path.exists():
    st.warning(f"⚠️ Central jobs database not found at: `{central_db_path}`")
    st.info("""
    **No jobs database found.**
    
    The central jobs database will be created automatically when you run your first pipeline.
    
    To get started:
    1. Go to the **Configuration** page
    2. Set up your pipeline parameters
    3. Run the pipeline from the **Execution** page
    4. Your job will be automatically saved to the central database
    
    **Database Location:** `jobs.duckdb` in the project root directory
    """)
    all_jobs = []
else:
    with st.spinner("Loading jobs from central database..."):
        all_jobs = get_all_jobs_from_central_db()

# Initialize filtered_jobs to handle empty state
filtered_jobs = []

if not all_jobs:
    st.info("No pipeline jobs found in the central database. Run a pipeline from the Configuration page to create your first job.")
    st.markdown(f"""
    **Database Location:** `{central_db_path}`
    
    **To create your first job:**
    1. Go to the **Configuration** page
    2. Set up your pipeline parameters
    3. Run the pipeline from the **Execution** page
    4. Your job will be automatically saved to the central database
    """)
else:
    # Filter jobs
    for job in all_jobs:
        # Status filter
        if job.get("status") not in status_filter:
            continue
        
        # Model filter
        params = job.get("parameters", {})
        model = params.get("model_choice", "unknown")
        if model not in model_filter:
            continue
        
        filtered_jobs.append(job)
    
    # Sort by created_at (most recent first)
    filtered_jobs.sort(key=lambda x: x.get("created_at") or datetime.min, reverse=True)
    
    st.success(f"Found {len(filtered_jobs)} job(s)")
    
    # Display jobs
    for job in filtered_jobs:
        job_id = job.get("job_id", "unknown")
        job_name = job.get("job_name", "") or job.get("parameters", {}).get("job_name", "")
        if not job_name:
            job_name = Path(job.get("output_dir", "")).name if job.get("output_dir") else "Unnamed"
        output_dir = job.get("output_dir", "")
        status = job.get("status", "unknown")
        created_at = job.get("created_at")
        completed_at = job.get("completed_at")
        params = job.get("parameters", {})
        
        # Format dates
        created_str = ""
        if created_at and pd.notna(created_at):
            if isinstance(created_at, str):
                created_str = created_at
            elif hasattr(created_at, 'strftime'):
                try:
                    created_str = created_at.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, AttributeError):
                    created_str = str(created_at)
        
        completed_str = ""
        if completed_at and pd.notna(completed_at):
            if isinstance(completed_at, str):
                completed_str = completed_at
            elif hasattr(completed_at, 'strftime'):
                try:
                    completed_str = completed_at.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, AttributeError):
                    completed_str = str(completed_at)
        
        # Status badge
        status_class = f"status-{status}"
        
        # Create job card
        with st.container():
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.markdown(f"""
                <div class="job-card">
                    <h3>{job_name}</h3>
                    <p><strong>Job ID:</strong> <code>{job_id[:8]}...</code></p>
                    <p><strong>Output Directory:</strong> <code>{output_dir}</code></p>
                    <p><strong>Status:</strong> <span class="{status_class}">{status.upper()}</span></p>
                    <p><strong>Model:</strong> {params.get('model_choice', 'N/A')}</p>
                    <p><strong>Rounds:</strong> {params.get('num_rounds', 'N/A')}</p>
                    <p><strong>Created:</strong> {created_str if created_str else 'N/A'}</p>
                    {f'<p><strong>Completed:</strong> {completed_str}</p>' if completed_str else ''}
                </div>
                """, unsafe_allow_html=True)
                
                # Show parameters in expander
                with st.expander("View Parameters"):
                    st.json(params)
            
            with col2:
                # Button to view results
                if st.button("View Results", key=f"view_{job_id}", type="primary"):
                    # Store the selected job output directory for navigation
                    st.session_state.selected_job_output_dir = output_dir
                    st.session_state.output_dir = output_dir
                    st.session_state.results_data = None  # Force reload
                    # Navigate to visualization page
                    st.switch_page("pages/04_visualize_results.py")
        
        st.divider()

# Summary statistics
if filtered_jobs:
    st.subheader("📊 Summary Statistics")
    col1, col2, col3, col4 = st.columns(4)
    
    status_counts = {}
    for job in filtered_jobs:
        status = job.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    
    with col1:
        st.metric("Total Jobs", len(filtered_jobs))
    with col2:
        st.metric("Running", status_counts.get("running", 0))
    with col3:
        st.metric("Completed", status_counts.get("completed", 0))
    with col4:
        st.metric("Failed", status_counts.get("failed", 0) + status_counts.get("stopped", 0))

