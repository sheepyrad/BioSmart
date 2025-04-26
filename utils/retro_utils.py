"""
Utility functions for retrosynthesis in the drug discovery pipeline.
"""

import logging
import pandas as pd
from pathlib import Path
from multiprocessing import Process, Queue

# Get logger for this module
logger = logging.getLogger(__name__)

# Import the retrosynthesis function
from utils.retrosynformer import run_retrosynthesis

def extract_variants_from_retrosynthesis(retro_result_file, max_variants=5):
    """
    Extract synthetic variants from a retrosynthesis result file.
    
    Args:
        retro_result_file: Path to the CSV file with retrosynthesis results
        max_variants: Maximum number of variants to extract
        
    Returns:
        List of dicts with variant_id and smiles
    """
    variants = []
    try:
        # Read retrosynthesis results
        df = pd.read_csv(retro_result_file)
        
        if df.empty:
            logger.warning(f"Empty retrosynthesis results file: {retro_result_file}")
            return variants
        
        # Find the SMILES column (should be 'smiles' but check alternatives)
        smiles_col = None
        if 'smiles' in df.columns:
            smiles_col = 'smiles'
        else:
            # Look for a column that might contain SMILES strings
            for col in df.columns:
                if df[col].dtype == 'object' and any(c for c in df[col].iloc[0] if c in '()=#@'):
                    smiles_col = col
                    break
        
        if smiles_col is None:
            logger.error(f"No SMILES column found in {retro_result_file}")
            return variants
        
        # Try to sort by a score column if it exists to get the best variants
        if 'score' in df.columns:
            # Determine if higher or lower score is better (assuming higher is better by default)
            # NOTE: If your scores are like energy where lower is better, reverse the sort
            df = df.sort_values('score', ascending=False)
            logger.info(f"Sorting variants by 'score' column (higher is better)")
        
        # Extract up to max_variants
        for idx, row in df.head(max_variants).iterrows():
            smiles = row[smiles_col]
            # Get score if available for labeling
            score_text = ""
            if 'score' in df.columns:
                score = row['score']
                if not pd.isna(score):
                    score_text = f"_score{score:.3f}"
            
            # Create variant ID based on the original compound and variant number
            parent_id = retro_result_file.stem
            variant_id = f"{parent_id}_variant_{idx+1}{score_text}"
            
            variants.append({
                "variant_id": variant_id, 
                "smiles": smiles, 
                "parent_id": parent_id,
                "score": float(row['score']) if 'score' in df.columns and not pd.isna(row['score']) else None
            })
    
    except Exception as e:
        logger.error(f"Error extracting variants from {retro_result_file}: {e}")
    
    logger.info(f"Extracted {len(variants)} variants from {retro_result_file}")
    return variants

def run_retrosynthesis_with_timeout(smiles, output_path, timeout=300):
    """
    Run retrosynthesis with a timeout using multiprocessing.
    
    Args:
        smiles: SMILES string of the compound
        output_path: Path to save the output CSV
        timeout: Maximum time in seconds to wait (default: 300 seconds / 5 minutes)
        
    Returns:
        True if successful, False if failed or timed out
    """
    def worker(smiles, output_path, queue):
        result = run_retrosynthesis(smiles, output_path)
        queue.put(result)
    
    # Create a queue to get the result
    queue = Queue()
    
    # Create and start the process
    process = Process(target=worker, args=(smiles, output_path, queue))
    process.start()
    
    # Wait for the specified timeout
    process.join(timeout)
    
    # If the process is still running after the timeout
    if process.is_alive():
        logger.warning(f"Retrosynthesis timed out after {timeout} seconds for SMILES: {smiles}")
        # Terminate the process
        process.terminate()
        process.join()
        return False
    
    # If the process finished within the timeout, get the result
    if not queue.empty():
        return queue.get()
    
    return False 