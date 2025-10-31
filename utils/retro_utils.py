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

def extract_variants_from_retrosynthesis(retro_result_file, top_n=5):
    """
    Extract synthetic variants from a retrosynthesis result file.
    
    Args:
        retro_result_file: Path to the CSV file with retrosynthesis results
        top_n: Maximum number of variants to extract
        
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
        
        # Extract up to top_n
        for idx, row in df.head(top_n).iterrows():
            # When using iterrows(), row is always a Series. Use .at or .iat for guaranteed scalar access
            try:
                # Get smiles value - use .at for guaranteed scalar access
                if smiles_col in df.columns:
                    smiles_val = row.at[smiles_col] if hasattr(row, 'at') else row[smiles_col]
                else:
                    smiles_val = ""
                
                # Convert to scalar string - double check it's not a DataFrame/Series
                if isinstance(smiles_val, pd.DataFrame):
                    logger.warning(f"smiles_val is DataFrame for row {idx}, using empty string")
                    smiles = ""
                elif isinstance(smiles_val, pd.Series):
                    smiles = str(smiles_val.iloc[0]) if len(smiles_val) > 0 else ""
                else:
                    smiles = str(smiles_val) if smiles_val is not None else ""
            except Exception as e:
                logger.warning(f"Error extracting smiles from row {idx}: {e}")
                smiles = ""
            
            # Get score if available for labeling
            score_text = ""
            score_value = None
            if 'score' in df.columns:
                try:
                    # Use .at for guaranteed scalar access
                    score_val = row.at['score'] if hasattr(row, 'at') else row['score']
                    
                    # Ensure score is a scalar
                    if isinstance(score_val, pd.DataFrame):
                        logger.warning(f"score_val is DataFrame for row {idx}, using None")
                        score_value = None
                    elif isinstance(score_val, pd.Series):
                        score_value = float(score_val.iloc[0]) if len(score_val) > 0 else None
                    elif score_val is not None and not pd.isna(score_val):
                        try:
                            score_value = float(score_val)
                            score_text = f"_score{score_value:.3f}"
                        except (ValueError, TypeError):
                            score_value = None
                except Exception as e:
                    logger.warning(f"Error extracting score from row {idx}: {e}")
                    score_value = None
            
            # Create variant ID based on the original compound and variant number
            parent_id = str(retro_result_file.stem)
            variant_id = f"{parent_id}_variant_{idx+1}{score_text}"
            
            # Final check - ensure all values are truly scalars
            variant_dict = {
                "variant_id": str(variant_id), 
                "smiles": str(smiles), 
                "parent_id": str(parent_id),
                "score": score_value
            }
            
            # Double-check for any DataFrame/Series values
            for k, v in variant_dict.items():
                if isinstance(v, (pd.DataFrame, pd.Series)):
                    logger.error(f"CRITICAL: DataFrame/Series found in variant_dict['{k}']! Type: {type(v)}")
                    variant_dict[k] = None
            
            variants.append(variant_dict)
    
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