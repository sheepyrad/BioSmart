"""
Utility functions for tracking and reporting in the drug discovery pipeline.
"""

import logging
from pathlib import Path
import pandas as pd
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from utils.duckdb_store import DuckDBStore

# Get logger for this module
logger = logging.getLogger(__name__)

def generate_tracking_report(compounds, variants, redock_results, out_dir):
    """
    Generate a comprehensive report showing the lineage of all compounds.
    
    Args:
        compounds: List of original generated compounds
        variants: List of variants from retrosynthesis
        redock_results: List of final docking results
        out_dir: Directory to save the report
    """
    try:
        # Create a comprehensive dataframe tracing all compounds
        report_rows = []
        
        # Add original compounds
        for comp in compounds:
            row = {
                'barcode': comp.get('barcode', 'unknown'),
                'smiles': comp.get('smiles', ''),
                'parent_id': 'NONE',
                'status': 'GENERATED',
                'source': 'AI_GENERATION'
            }
            report_rows.append(row)
        
        # Add all variants
        for var in variants:
            # Extract parent barcode from variant barcode (format: R{round}-{parent_barcode}-V-{vidx})
            parent_barcode = 'unknown'
            variant_barcode = var.get('barcode', '')
            if variant_barcode and '-V-' in variant_barcode:
                # Extract parent barcode: everything between "R{round}-" and "-V-"
                parts = variant_barcode.split('-V-')
                if parts:
                    parent_part = parts[0]
                    # Remove the round prefix (R{round}-)
                    if '-' in parent_part:
                        parent_barcode = parent_part.split('-', 1)[1] if len(parent_part.split('-')) > 1 else parent_part
            
            row = {
                'barcode': variant_barcode,
                'smiles': var.get('smiles', ''),
                'parent_id': var.get('source_compound', 'unknown'),
                'parent_barcode': parent_barcode,
                'status': 'SYNTHETIZED',
                'source': 'RETROSYNTHESIS',
                'score': var.get('score', None)
            }
            report_rows.append(row)
        
        # Update status for successfully docked variants
        docked_barcodes = {result.get('barcode') for result in redock_results}
        for row in report_rows:
            if row['barcode'] in docked_barcodes:
                row['status'] = 'DOCKED'
                
                # Find the docking score
                for result in redock_results:
                    if result.get('barcode') == row['barcode']:
                        # Extract docking score from Unidock results
                        if 'docking_score' in result and result['docking_score'] is not None:
                            row['docking_score'] = result['docking_score']
                        
                        # Add pose count information
                        if 'pose_count' in result and result['pose_count'] is not None:
                            row['pose_count'] = result['pose_count']
                        
                        # Add result file path
                        if 'result_file' in result and result['result_file'] is not None:
                            row['result_file'] = result['result_file']
                        
                        # Add all scores if available
                        if 'all_scores' in result and result['all_scores'] is not None:
                            row['all_scores'] = str(result['all_scores'])
                        
                        # Legacy support for old format
                        if 'pose_pred_out' in result and result['pose_pred_out'] is not None:
                            try:
                                from utils.molecule_processing import extract_best_pose_and_score
                                best_score, best_pose = extract_best_pose_and_score(result['pose_pred_out'])
                                if best_score is not None and 'docking_score' not in row:
                                    row['docking_score'] = best_score
                                if best_pose is not None:
                                    row['best_pose'] = best_pose
                            except Exception as e:
                                logger.warning(f"Error extracting legacy pose data for {row['barcode']}: {e}")
                        
                        # Legacy support for re_scored_values
                        elif 're_scored_values' in result and result['re_scored_values'] is not None and 'docking_score' not in row:
                            try:
                                docking_score = result['re_scored_values'].split(',')[0]
                                row['docking_score'] = float(docking_score)
                            except Exception as e:
                                logger.warning(f"Error extracting legacy re_scored_values for {row['barcode']}: {e}")
        
        # Create the report DataFrame
        report_df = pd.DataFrame(report_rows)
        
        # Save to CSV
        report_file = out_dir / "compound_tracking_report.csv"
        report_df.to_csv(report_file, index=False)
        logger.info(f"Compound tracking report saved to: {report_file}")
        
        # Return the dataframe for further use if needed
        return report_df
    
    except Exception as e:
        logger.error(f"Error generating tracking report: {e}")
        return None

def _ensure_scalar(value, default=None):
    """Ensure a value is a scalar (not DataFrame, Series, etc.) for DuckDB storage."""
    if value is None:
        return default
    if isinstance(value, pd.DataFrame):
        logger.warning(f"Attempted to store DataFrame as scalar, using default: {default}. DataFrame shape: {value.shape}")
        return default
    if isinstance(value, pd.Series):
        # If it's a Series with one value, extract it
        if len(value) == 1:
            try:
                return value.iloc[0]
            except Exception:
                return default
        logger.warning(f"Attempted to store Series as scalar, using default: {default}. Series length: {len(value)}")
        return default
    # Convert to string if it's not a basic type
    if not isinstance(value, (str, int, float, bool, type(None))):
        # Try to convert to string, but check if it's a complex type first
        try:
            if hasattr(value, '__iter__') and not isinstance(value, (str, bytes)):
                # It's an iterable but not a string/bytes - likely a list or other collection
                # For lists, we could join them, but for DuckDB we probably want None or empty string
                return default
            return str(value)
        except Exception:
            return default
    return value

def update_tracking_report(report_file, new_data, report_type="compound", duckdb_store: Optional["DuckDBStore"] = None):
    """
    Incrementally update the tracking report with new data.
    
    Args:
        report_file: Path to the report CSV file
        new_data: Dictionary containing the new data to add
        report_type: Type of data being added ("compound", "variant", or "docking")
        duckdb_store: Optional DuckDBStore instance to also write to DuckDB
    """
    try:
        # First, sanitize the entire new_data dict to ensure no DataFrames/Series
        sanitized_data = {}
        for key, value in new_data.items():
            # Check if value is DataFrame/Series before sanitizing
            if isinstance(value, (pd.DataFrame, pd.Series)):
                logger.warning(f"Found DataFrame/Series in new_data['{key}'] before sanitization. Type: {type(value)}")
            sanitized_value = _ensure_scalar(value, None)
            sanitized_data[key] = sanitized_value
        new_data = sanitized_data
        
        # Write to DuckDB if provided
        if duckdb_store is not None:
            try:
                if report_type == "compound":
                    # Write to molecules table
                    molecules_data = [{
                        "barcode": _ensure_scalar(new_data.get("barcode", ""), ""),
                        "smiles": _ensure_scalar(new_data.get("smiles", ""), ""),
                        "generation": None,  # Not stored in molecules table anymore
                        "status": _ensure_scalar(new_data.get("status", ""), ""),
                        "source": _ensure_scalar(new_data.get("source", ""), "")
                    }]
                    # Final check before passing to DuckDB
                    for m in molecules_data:
                        for k, v in m.items():
                            if isinstance(v, (pd.DataFrame, pd.Series)):
                                logger.error(f"CRITICAL: DataFrame/Series in molecules_data['{k}']! Type: {type(v)}")
                                m[k] = None
                    duckdb_store.upsert_molecules(molecules_data)
                elif report_type == "variant":
                    # Write to variants table
                    variant_data = [{
                        "barcode": _ensure_scalar(new_data.get("barcode", ""), ""),
                        "smiles": _ensure_scalar(new_data.get("smiles", ""), ""),
                        "score": _ensure_scalar(new_data.get("score"), None),
                        "status": _ensure_scalar(new_data.get("status", ""), ""),
                        "parent_id": _ensure_scalar(new_data.get("source_compound", new_data.get("parent_id", "")), "")
                    }]
                    # Final check before passing to DuckDB
                    for v in variant_data:
                        for k, val in v.items():
                            if isinstance(val, (pd.DataFrame, pd.Series)):
                                logger.error(f"CRITICAL: DataFrame/Series in variant_data['{k}']! Type: {type(val)}")
                                v[k] = None
                    duckdb_store.upsert_variants(variant_data)
                elif report_type == "variant_status_update":
                    # Update status in variants table
                    # If we only have barcode and status, try to get existing variant data
                    barcode = _ensure_scalar(new_data.get("barcode", ""), "")
                    if barcode:
                        existing_variant = duckdb_store.get_variant_by_barcode(barcode)
                        if existing_variant:
                            variant_data = [{
                                "barcode": barcode,
                                "smiles": _ensure_scalar(existing_variant.get("smiles", new_data.get("smiles", "")), ""),
                                "score": _ensure_scalar(existing_variant.get("score", new_data.get("score")), None),
                                "status": _ensure_scalar(new_data.get("status", existing_variant.get("status", "")), ""),
                                "parent_id": _ensure_scalar(existing_variant.get("parent_id", new_data.get("parent_id", "")), "")
                            }]
                        else:
                            # Fallback: use what we have
                            variant_data = [{
                                "barcode": barcode,
                                "smiles": _ensure_scalar(new_data.get("smiles", ""), ""),
                                "score": _ensure_scalar(new_data.get("score"), None),
                                "status": _ensure_scalar(new_data.get("status", ""), ""),
                                "parent_id": _ensure_scalar(new_data.get("parent_id", ""), "")
                            }]
                        # Final check before passing to DuckDB
                        for v in variant_data:
                            for k, val in v.items():
                                if isinstance(val, (pd.DataFrame, pd.Series)):
                                    logger.error(f"CRITICAL: DataFrame/Series in variant_data['{k}']! Type: {type(val)}")
                                    v[k] = None
                        duckdb_store.upsert_variants(variant_data)
                    else:
                        logger.warning("No barcode provided for variant status update in DuckDB")
                elif report_type == "docking":
                    # Update docking results - this is handled separately in the pipeline
                    # via upsert_docking_results, so we don't need to handle it here
                    pass
            except Exception as e:
                logger.warning(f"Failed to write to DuckDB: {e}")
        
        # Continue with CSV write (existing logic)
        # Create base columns for the report
        base_columns = [
            'barcode', 'smiles',
            'parent_id', 'status', 'source', 'timestamp'
        ]
        
        # Add type-specific columns
        if report_type == "variant":
            base_columns.extend(['source_compound', 'parent_barcode', 'score'])
        elif report_type == "docking":
            base_columns.extend(['docking_score', 'pose_count', 'result_file', 'all_scores', 'best_pose'])
        elif report_type == "variant_status_update":
            # For status updates, we only need to update existing rows
            pass
        
        # Add timestamp to the new data
        new_data['timestamp'] = datetime.now().isoformat()
        
        # Create or load existing report
        if report_file.exists():
            df = pd.read_csv(report_file)
            # Add any new columns that might be in the new data
            for col in new_data.keys():
                if col not in df.columns:
                    df[col] = None
        else:
            df = pd.DataFrame(columns=base_columns)
        
        # Handle different update types
        if report_type == "variant_status_update":
            # Update existing row based on barcode
            barcode = new_data.get('barcode')
            if barcode and not df.empty:
                mask = df['barcode'] == barcode
                if mask.any():
                    # Update existing row
                    for key, value in new_data.items():
                        if key in df.columns:
                            df.loc[mask, key] = value
                        else:
                            df[key] = None
                            df.loc[mask, key] = value
                else:
                    logger.warning(f"No existing row found for barcode {barcode} in status update")
            else:
                logger.warning(f"Invalid barcode for status update: {barcode}")
        else:
            # Convert new data to DataFrame row and append
            new_row = pd.DataFrame([new_data])
            df = pd.concat([df, new_row], ignore_index=True)
        
        # Save updated report
        df.to_csv(report_file, index=False)
        logger.debug(f"Updated tracking report with new {report_type} data")
        
    except Exception as e:
        logger.error(f"Error updating tracking report: {e}") 