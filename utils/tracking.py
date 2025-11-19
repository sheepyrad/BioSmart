"""
Utility functions for tracking and reporting in the drug discovery pipeline.
"""

import logging
from pathlib import Path
import pandas as pd
from datetime import datetime
from typing import Optional, TYPE_CHECKING, List

if TYPE_CHECKING:
    from utils.duckdb_store import DuckDBStore

# Get logger for this module
logger = logging.getLogger(__name__)

# Helper functions for DataFrame pipe operations
def _ensure_columns(df: pd.DataFrame, required_columns: List[str]) -> pd.DataFrame:
    """Ensure DataFrame has all required columns, adding None if missing."""
    for col in required_columns:
        if col not in df.columns:
            df[col] = None
    return df

def _load_or_create_dataframe(report_file: Path, base_columns: List[str]) -> pd.DataFrame:
    """Load DataFrame from CSV or create empty one with base columns."""
    if report_file.exists():
        return pd.read_csv(report_file)
    return pd.DataFrame(columns=base_columns)

def _update_status_by_barcode(df: pd.DataFrame, barcode: str, updates: dict) -> pd.DataFrame:
    """Update DataFrame rows matching barcode with new values."""
    if df.empty or not barcode:
        return df
    mask = df['barcode'] == barcode
    if mask.any():
        for key, value in updates.items():
            if key not in df.columns:
                df[key] = None
            df.loc[mask, key] = value
    return df

def _append_new_row(df: pd.DataFrame, new_data: dict) -> pd.DataFrame:
    """Append new row to DataFrame."""
    new_row = pd.DataFrame([new_data])
    return pd.concat([df, new_row], ignore_index=True)

def _append_new_rows(df: pd.DataFrame, new_rows_df: pd.DataFrame) -> pd.DataFrame:
    """Append multiple new rows to DataFrame."""
    return pd.concat([df, new_rows_df], ignore_index=True)

def _update_statuses_batch(df: pd.DataFrame, status_map: dict, timestamp: str) -> pd.DataFrame:
    """Batch update statuses for multiple barcodes."""
    if df.empty:
        return df
    mask = df['barcode'].isin(status_map.keys())
    if mask.any():
        df.loc[mask, 'status'] = df.loc[mask, 'barcode'].map(status_map)
        df.loc[mask, 'timestamp'] = timestamp
    return df

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
        
        # Create or load existing report using pipe
        df = (
            _load_or_create_dataframe(report_file, base_columns)
            .pipe(_ensure_columns, required_columns=list(new_data.keys()))
        )
        
        # Handle different update types using pipe
        if report_type == "variant_status_update":
            # Update existing row based on barcode
            barcode = new_data.get('barcode')
            if barcode:
                df = df.pipe(_update_status_by_barcode, barcode=barcode, updates=new_data)
            else:
                logger.warning(f"Invalid barcode for status update: {barcode}")
        else:
            # Append new row using pipe
            df = df.pipe(_append_new_row, new_data=new_data)
        
        # Save updated report
        df.to_csv(report_file, index=False)
        logger.debug(f"Updated tracking report with new {report_type} data")
        
    except Exception as e:
        logger.error(f"Error updating tracking report: {e}")

def batch_update_variant_statuses(
    variants_data: list,
    report_file: Path,
    duckdb_store: Optional["DuckDBStore"] = None
):
    """
    Batch update variant statuses in both DuckDB and CSV.
    Much more efficient than calling update_tracking_report individually.
    
    Args:
        variants_data: List of dicts with at least 'barcode' and 'status' keys
        report_file: Path to the CSV report file
        duckdb_store: Optional DuckDBStore instance
    """
    if not variants_data:
        return
    
    try:
        # Batch update DuckDB if provided
        if duckdb_store is not None:
            try:
                # Get all barcodes
                barcodes = [_ensure_scalar(v.get("barcode", ""), "") for v in variants_data if v.get("barcode")]
                
                if barcodes:
                    # Fetch all existing variants in one query
                    existing_variants = duckdb_store.get_variants_by_barcodes(barcodes)
                    
                    # Prepare variant data for DuckDB update
                    variant_updates = []
                    for variant in variants_data:
                        barcode = _ensure_scalar(variant.get("barcode", ""), "")
                        if barcode:
                            existing_variant = existing_variants.get(barcode)
                            if existing_variant:
                                variant_updates.append({
                                    "barcode": barcode,
                                    "smiles": _ensure_scalar(existing_variant.get("smiles", variant.get("smiles", "")), ""),
                                    "score": _ensure_scalar(existing_variant.get("score", variant.get("score")), None),
                                    "status": _ensure_scalar(variant.get("status", existing_variant.get("status", "")), ""),
                                    "parent_id": _ensure_scalar(existing_variant.get("parent_id", variant.get("parent_id", "")), "")
                                })
                            else:
                                # Fallback: use what we have
                                variant_updates.append({
                                    "barcode": barcode,
                                    "smiles": _ensure_scalar(variant.get("smiles", ""), ""),
                                    "score": _ensure_scalar(variant.get("score"), None),
                                    "status": _ensure_scalar(variant.get("status", ""), ""),
                                    "parent_id": _ensure_scalar(variant.get("parent_id", ""), "")
                                })
                    
                    if variant_updates:
                        duckdb_store.upsert_variants(variant_updates)
            except Exception as e:
                logger.warning(f"Failed to batch update DuckDB: {e}")
        
        # Batch update CSV using pipe
        report_file = Path(report_file)
        now = datetime.now().isoformat()
        
        # Create a mapping of barcode to status
        status_map = {_ensure_scalar(v.get("barcode", ""), ""): _ensure_scalar(v.get("status", ""), "") 
                     for v in variants_data if v.get("barcode")}
        
        # Load existing report and update statuses using pipe
        base_columns = ['barcode', 'smiles', 'parent_id', 'status', 'source', 'timestamp']
        df = (
            _load_or_create_dataframe(report_file, base_columns)
            .pipe(_update_statuses_batch, status_map=status_map, timestamp=now)
        )
        
        # Save updated report
        df.to_csv(report_file, index=False)
        logger.debug(f"Batch updated {len(variants_data)} variant statuses in CSV")
        
    except Exception as e:
        logger.error(f"Error batch updating variant statuses: {e}")

def batch_update_compounds(
    compounds_data: list,
    round_report: Path,
    master_report: Path,
    duckdb_store: Optional["DuckDBStore"] = None
):
    """
    Batch update compounds in both DuckDB and CSV.
    More efficient than calling update_tracking_report individually for each compound.
    
    Args:
        compounds_data: List of dicts with compound data
        round_report: Path to the round CSV report file
        master_report: Path to the master CSV report file
        duckdb_store: Optional DuckDBStore instance
    """
    if not compounds_data:
        return
    
    try:
        # Batch update DuckDB if provided
        if duckdb_store is not None:
            try:
                molecules_data = []
                for compound in compounds_data:
                    molecules_data.append({
                        "barcode": _ensure_scalar(compound.get("barcode", ""), ""),
                        "smiles": _ensure_scalar(compound.get("smiles", ""), ""),
                        "generation": None,  # Not stored in molecules table anymore
                        "status": _ensure_scalar(compound.get("status", ""), ""),
                        "source": _ensure_scalar(compound.get("source", ""), "")
                    })
                
                if molecules_data:
                    duckdb_store.upsert_molecules(molecules_data)
            except Exception as e:
                logger.warning(f"Failed to batch update DuckDB for compounds: {e}")
        
        # Batch update CSV files using pipe
        now = datetime.now().isoformat()
        base_columns = ['barcode', 'smiles', 'parent_id', 'status', 'source', 'timestamp']
        
        # Prepare new rows
        new_rows = []
        for compound in compounds_data:
            new_row = {
                'barcode': _ensure_scalar(compound.get("barcode", ""), ""),
                'smiles': _ensure_scalar(compound.get("smiles", ""), ""),
                'parent_id': _ensure_scalar(compound.get("parent_id", "NONE"), "NONE"),
                'status': _ensure_scalar(compound.get("status", ""), ""),
                'source': _ensure_scalar(compound.get("source", ""), ""),
                'timestamp': now
            }
            new_rows.append(new_row)
        
        if new_rows:
            new_df = pd.DataFrame(new_rows)
            
            for report_file in [round_report, master_report]:
                report_file = Path(report_file)
                
                # Load existing report and append new rows using pipe
                df = (
                    _load_or_create_dataframe(report_file, base_columns)
                    .pipe(_append_new_rows, new_rows_df=new_df)
                )
                df.to_csv(report_file, index=False)
        
        logger.debug(f"Batch updated {len(compounds_data)} compounds in CSV")
        
    except Exception as e:
        logger.error(f"Error batch updating compounds: {e}")

def batch_update_variants(
    variants_data: list,
    round_report: Path,
    master_report: Path,
    duckdb_store: Optional["DuckDBStore"] = None
):
    """
    Batch update variants in both DuckDB and CSV.
    More efficient than calling update_tracking_report individually for each variant.
    
    Args:
        variants_data: List of dicts with variant data
        round_report: Path to the round CSV report file
        master_report: Path to the master CSV report file
        duckdb_store: Optional DuckDBStore instance
    """
    if not variants_data:
        return
    
    try:
        # Batch update DuckDB if provided
        if duckdb_store is not None:
            try:
                variant_updates = []
                for variant in variants_data:
                    variant_updates.append({
                        "barcode": _ensure_scalar(variant.get("barcode", ""), ""),
                        "smiles": _ensure_scalar(variant.get("smiles", ""), ""),
                        "score": _ensure_scalar(variant.get("score"), None),
                        "status": _ensure_scalar(variant.get("status", ""), ""),
                        "parent_id": _ensure_scalar(variant.get("source_compound", variant.get("parent_id", "")), "")
                    })
                
                if variant_updates:
                    duckdb_store.upsert_variants(variant_updates)
            except Exception as e:
                logger.warning(f"Failed to batch update DuckDB for variants: {e}")
        
        # Batch update CSV files using pipe
        now = datetime.now().isoformat()
        base_columns = ['barcode', 'smiles', 'parent_id', 'status', 'source', 'timestamp', 
                       'source_compound', 'parent_barcode', 'score']
        
        # Prepare new rows
        new_rows = []
        for variant in variants_data:
            new_row = {
                'barcode': _ensure_scalar(variant.get("barcode", ""), ""),
                'smiles': _ensure_scalar(variant.get("smiles", ""), ""),
                'parent_id': _ensure_scalar(variant.get("source_compound", variant.get("parent_id", "")), ""),
                'status': _ensure_scalar(variant.get("status", ""), ""),
                'source': _ensure_scalar(variant.get("source", "RETROSYNTHESIS"), "RETROSYNTHESIS"),
                'timestamp': now,
                'source_compound': _ensure_scalar(variant.get("source_compound", ""), ""),
                'parent_barcode': _ensure_scalar(variant.get("parent_barcode", ""), ""),
                'score': _ensure_scalar(variant.get("score"), None)
            }
            new_rows.append(new_row)
        
        if new_rows:
            new_df = pd.DataFrame(new_rows)
            
            for report_file in [round_report, master_report]:
                report_file = Path(report_file)
                
                # Load existing report, ensure columns, and append new rows using pipe
                df = (
                    _load_or_create_dataframe(report_file, base_columns)
                    .pipe(_ensure_columns, required_columns=base_columns)
                    .pipe(_append_new_rows, new_rows_df=new_df)
                )
                df.to_csv(report_file, index=False)
        
        logger.debug(f"Batch updated {len(variants_data)} variants in CSV")
        
    except Exception as e:
        logger.error(f"Error batch updating variants: {e}") 