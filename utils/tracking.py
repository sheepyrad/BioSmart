"""
Utility functions for tracking and reporting in the drug discovery pipeline.
"""

import logging
from pathlib import Path
import pandas as pd
from datetime import datetime

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
                'compound_id': comp.get('compound_id', 'unknown'),
                'barcode': comp.get('barcode', 'unknown'),
                'generation': comp.get('generation', '1'),
                'round': comp.get('round', 1),
                'smiles': comp.get('smiles', ''),
                'parent_id': 'NONE',
                'status': 'GENERATED',
                'source': 'AI_GENERATION'
            }
            report_rows.append(row)
        
        # Add all variants
        for var in variants:
            row = {
                'compound_id': var.get('variant_id', 'unknown'),
                'barcode': var.get('barcode', 'unknown'),
                'generation': var.get('generation', '2'),
                'round': var.get('round', 1),
                'smiles': var.get('smiles', ''),
                'parent_id': var.get('source_compound', 'unknown'),
                'parent_barcode': next((c.get('barcode') for c in compounds if c.get('compound_id') == var.get('source_compound')), 'unknown'),
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

def update_tracking_report(report_file, new_data, report_type="compound"):
    """
    Incrementally update the tracking report with new data.
    
    Args:
        report_file: Path to the report CSV file
        new_data: Dictionary containing the new data to add
        report_type: Type of data being added ("compound", "variant", or "docking")
    """
    try:
        # Create base columns for the report
        base_columns = [
            'compound_id', 'barcode', 'generation', 'round', 'smiles',
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