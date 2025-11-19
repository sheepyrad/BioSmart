"""
Utility modules for drug discovery pipeline.

This package contains various utilities for different stages of the drug discovery pipeline:
- Ligand generation
- Retrosynthesis
- MedChem filtering
- Redocking (now using Unidock)
- Energy minimization ## Deprecated
- Pose evaluation ## Deprecated
- Molecule processing
- Tracking and reporting
- Logging
- Boltz-2 filtering with affinity prediction
"""

# Import main utilities
from utils.ligand_generation import run_ligand_generation, combine_pocket2mol_outputs
from utils.retrosynformer import run_retrosynthesis
from utils.medchem_filter import filter_by_pass_count, generate_filter_plots
from utils.energy_minimization import optimize_ligand_in_pocket
from utils.pose_evaluation import run_posebuster

# Import new utilities
from utils.molecule_processing import extract_smiles_from_sdf, smiles_to_sdf, extract_best_pose_and_score
from utils.retro_utils import extract_variants_from_retrosynthesis, run_retrosynthesis_with_timeout
from utils.tracking import generate_tracking_report, update_tracking_report
from utils.logging_utils import setup_logging, ThreadSafeRotatingFileHandler
from utils.boltz_filter import boltz_filter_variants

# Export all utilities
__all__ = [
    # Ligand generation
    'run_ligand_generation', 'combine_pocket2mol_outputs',
    
    # Redocking (now Unidock-based)
    # Note: redock_compound removed - use run_batch_compound_redocking instead
    
    # Retrosynthesis
    'run_retrosynthesis',
    
    # MedChem filtering
    'filter_by_pass_count', 'generate_filter_plots',
    
    # Energy minimization (deprecated)
    'optimize_ligand_in_pocket',
    
    # Pose evaluation (deprecated)
    'run_posebuster',
    
    # Molecule processing
    'extract_smiles_from_sdf', 'smiles_to_sdf', 'extract_best_pose_and_score',
    
    # Retro utilities
    'extract_variants_from_retrosynthesis', 'run_retrosynthesis_with_timeout',
    
    # Tracking and reporting
    'generate_tracking_report', 'update_tracking_report',
    
    # Logging
    'setup_logging', 'ThreadSafeRotatingFileHandler',
    
    # Boltz filtering
    'boltz_filter_variants',

    # DuckDB storage
    'DuckDBStore',
] 