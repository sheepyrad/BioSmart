"""
Module for running retrosynthesis analysis on top compounds from redocking results.
Uses Synformer to generate possible synthetic routes.
"""

import os
import ast
import pandas as pd
import subprocess
import numpy as np
from pathlib import Path
import logging

# Import the new environment manager
from .environment_manager import env_manager

logger = logging.getLogger(__name__)

def parse_vina_scores(pose_pred_out_str):
    """Parse the pose_pred_out string to extract Vina scores."""
    try:
        # Convert string representation of dict to actual dict
        pose_dict = ast.literal_eval(pose_pred_out_str)
        
        # Extract all score lists
        all_scores = []
        for key, value in pose_dict.items():
            if isinstance(value, list) and len(value) > 0 and isinstance(value[0], list):
                all_scores.extend(value[0])  # Get the scores from each pose
        
        # Calculate average score if we have any scores
        if all_scores:
            return np.mean(all_scores)
        else:
            return None
    except (SyntaxError, ValueError) as e:
        logger.error(f"Error parsing pose_pred_out: {e}")
        return None

def get_top_compounds(results_csv, top_n=5):
    """
    Extract top N compounds from redocking results based on average Vina score.
    
    Args:
        results_csv: Path to the redocking results CSV file
        top_n: Number of top compounds to select (default: 5)
        
    Returns:
        DataFrame containing the top N compounds
    """
    try:
        df = pd.read_csv(results_csv)
        
        # Calculate average Vina score for each compound
        df['avg_vina_score'] = df['pose_pred_out'].apply(parse_vina_scores)
        
        # Sort by average Vina score (lower is better) and take top N
        sorted_df = df.sort_values('avg_vina_score').head(top_n)
        
        logger.info(f"Selected top {len(sorted_df)} compounds from {results_csv}")
        return sorted_df
    
    except Exception as e:
        logger.error(f"Error getting top compounds: {e}")
        return pd.DataFrame()

def run_retrosynthesis(smiles, output_path, model_path="./src/synformer/data/trained_weights/sf_ed_default.ckpt", timeout=300):
    """
    Run retrosynthesis analysis on a single compound using Synformer with conda environment.
    
    Args:
        smiles: SMILES string of the compound
        output_path: Path to save the output CSV
        model_path: Path to the Synformer model checkpoint (now in src directory)
        timeout: Maximum time in seconds to wait for retrosynthesis to complete (default: 300 seconds / 5 minutes)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Make all paths absolute
        output_path = Path(output_path).absolute()
        model_path = Path(model_path).absolute()
        synformer_dir = Path("./src/synformer").absolute()
        
        # Create a temporary input CSV file with the SMILES string
        input_dir = output_path.parent
        temp_input_csv = input_dir / f"temp_input_{output_path.stem}.csv"
        
        # Create a CSV file with a 'smiles' column
        pd.DataFrame({'smiles': [smiles]}).to_csv(temp_input_csv, index=False)
        logger.info(f"Created temporary input CSV file: {temp_input_csv}")
        
        # Command to run using environment manager
        command = [
            "python", 
            "scripts/sample.py", 
            "--model-path", str(model_path),
            "--input", str(temp_input_csv),
            "--output", str(output_path)
        ]
        
        logger.info(f"Running retrosynthesis for {smiles}")
        logger.info(f"Command: {' '.join(command)}")
        
        try:
            # Use environment manager to run Synformer with streaming output
            result = env_manager.run_tool(
                tool_name="synformer",
                command=command,
                cwd=str(synformer_dir),
                timeout=timeout,
                capture_output=True,
                text=True,
                check=False,  # Don't raise exception on non-zero exit
                log_callback=logger.info,
                stream_output=True  # Enable real-time output streaming
            )
            
            if result.returncode == 0:
                logger.info(f"Retrosynthesis complete. Output saved to {output_path}")
                logger.debug(f"Synformer output: {result.stdout}")
                return True
            else:
                logger.error(f"Synformer failed with exit code {result.returncode}")
                logger.error(f"Synformer stderr: {result.stderr}")
                return False
            
        except subprocess.TimeoutExpired:
            logger.warning(f"Retrosynthesis timed out after {timeout} seconds for SMILES: {smiles}")
            return False
            
        finally:
            # Clean up the temporary input file
            temp_input_csv.unlink(missing_ok=True)
    
    except Exception as e:
        logger.error(f"Unexpected error running retrosynthesis: {e}")
        return False

def process_redocking_results(redock_dir, round_no, top_n=5, retro_dir=None):
    """
    Process redocking results and run retrosynthesis on top compounds.
    
    Args:
        redock_dir: Path to the redocking results directory
        round_no: Round number (0-based)
        top_n: Number of top compounds to select (default: 5)
        retro_dir: Directory to save retrosynthesis results (if None, will use parent of redock_dir)
    
    Returns:
        Path to the retrosynthesis results directory
    """
    redock_dir = Path(redock_dir)
    results_csv = redock_dir / f"redocking_results_round_{round_no+1}.csv"
    
    if not results_csv.exists():
        logger.error(f"Redocking results file not found: {results_csv}")
        return None
    
    # Use provided retro_dir if available, otherwise use default location
    if retro_dir is None:
        retro_dir = redock_dir.parent / "synformer_synthesis"
    retro_dir = Path(retro_dir)
    retro_dir.mkdir(exist_ok=True)
    
    # Create a round-specific folder to keep results organized
    round_retro_dir = retro_dir / f"round_{round_no+1}"
    round_retro_dir.mkdir(exist_ok=True)
    
    # Get top compounds
    top_compounds = get_top_compounds(results_csv, top_n)
    
    if top_compounds.empty:
        logger.warning(f"No compounds found for retrosynthesis in round {round_no+1}")
        return retro_dir
    
    # Run retrosynthesis for each top compound
    for i, (_, compound) in enumerate(top_compounds.iterrows()):
        cid = compound["compound_id"]
        smi = compound["smiles"]
        score = compound["avg_vina_score"]
        
        # Save to the round-specific directory to keep organized
        output_file = round_retro_dir / f"top{i+1}_{cid}.csv"
        
        logger.info(f"Processing compound {i+1}/{len(top_compounds)}: {cid} (score: {score:.2f})")
        success = run_retrosynthesis(smi, output_file)
        
        if success:
            logger.info(f"Retrosynthesis completed for {cid}")
        else:
            logger.warning(f"Retrosynthesis failed for {cid}")
    
    # Create a summary file with all top compounds in the round directory
    summary_csv = round_retro_dir / f"top{top_n}_summary.csv"
    top_compounds.to_csv(summary_csv, index=False)
    logger.info(f"Saved summary of top {top_n} compounds to {summary_csv}")
    
    return round_retro_dir 