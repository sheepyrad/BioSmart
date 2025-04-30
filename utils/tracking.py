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
                        # Extract best docking score and pose from pose_pred_out
                        if 'pose_pred_out' in result and result['pose_pred_out'] is not None:
                            try:
                                from utils.molecule_processing import extract_best_pose_and_score
                                best_score, best_pose = extract_best_pose_and_score(result['pose_pred_out'])
                                if best_score is not None:
                                    row['docking_score'] = best_score
                                if best_pose is not None:
                                    row['best_pose'] = best_pose
                            except Exception as e:
                                logger.warning(f"Error extracting pose data for {row['barcode']}: {e}")
                        # Fallback to re_scored_values if pose_pred_out processing fails
                        elif 're_scored_values' in result and result['re_scored_values'] is not None:
                            try:
                                docking_score = result['re_scored_values'].split(',')[0]
                                row['docking_score'] = float(docking_score)
                            except Exception as e:
                                logger.warning(f"Error extracting re_scored_values for {row['barcode']}: {e}")
        
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
            base_columns.extend(['docking_score', 'best_pose'])
        
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
        
        # Convert new data to DataFrame row
        new_row = pd.DataFrame([new_data])
        
        # Append new data
        df = pd.concat([df, new_row], ignore_index=True)
        
        # Save updated report
        df.to_csv(report_file, index=False)
        logger.debug(f"Updated tracking report with new {report_type} data")
        
    except Exception as e:
        logger.error(f"Error updating tracking report: {e}") 