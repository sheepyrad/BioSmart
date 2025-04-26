"""
Utility functions for molecule processing in the drug discovery pipeline.
"""

import logging
from pathlib import Path
from rdkit import Chem
import pandas as pd

# Get logger for this module
logger = logging.getLogger(__name__)

def extract_smiles_from_sdf(sdf_file):
    """
    Extract SMILES strings from an SDF file.
    
    Args:
        sdf_file: Path to the SDF file
        
    Returns:
        List of dicts with compound_id and smiles
    """
    compounds = []
    try:
        # Read molecules from SDF
        supplier = Chem.SDMolSupplier(str(sdf_file))
        
        for idx, mol in enumerate(supplier):
            if mol is not None:
                # Generate compound ID based on the file name and index
                compound_id = f"{sdf_file.stem}_mol_{idx+1}"
                smiles = Chem.MolToSmiles(mol)
                compounds.append({"compound_id": compound_id, "smiles": smiles})
    except Exception as e:
        logger.error(f"Error extracting SMILES from SDF: {e}")
    
    logger.info(f"Extracted {len(compounds)} SMILES strings from {sdf_file}")
    return compounds

def smiles_to_sdf(smiles_list, output_file):
    """
    Convert a list of SMILES strings to an SDF file.
    
    Args:
        smiles_list: List of dicts with 'smiles' and ID ('variant_id' or other id field)
        output_file: Path to save the SDF file
        
    Returns:
        Path to the created SDF file or None if failed
    """
    try:
        writer = Chem.SDWriter(str(output_file))
        
        for item in smiles_list:
            smiles = item['smiles']
            
            # Get the ID (could be compound_id, variant_id, etc.)
            id_field = next((k for k in item.keys() if k.endswith('_id')), None)
            id_value = item.get(id_field, "unknown")
            
            mol = Chem.MolFromSmiles(smiles)
            if mol:
                # Add properties to the molecule
                mol.SetProp("_Name", id_value)
                mol.SetProp("SMILES", smiles)
                
                # Add barcode and tracking information
                if 'barcode' in item:
                    mol.SetProp("BARCODE", item['barcode'])
                if 'parent_id' in item:
                    mol.SetProp("PARENT_ID", item['parent_id'])
                if 'source_compound' in item:
                    mol.SetProp("SOURCE_COMPOUND", item['source_compound'])
                if 'generation' in item:
                    mol.SetProp("GENERATION", item['generation'])
                
                writer.write(mol)
            else:
                logger.warning(f"Could not convert SMILES to molecule: {smiles}")
        
        writer.close()
        logger.info(f"Created SDF file with {len(smiles_list)} molecules: {output_file}")
        return output_file
    
    except Exception as e:
        logger.error(f"Error converting SMILES to SDF: {e}")
        return None

def extract_best_pose_and_score(pose_pred_str):
    """
    Extract the best docking pose and score from the pose prediction output.
    
    Args:
        pose_pred_str: String or dict representation of pose prediction output
        
    Returns:
        Tuple of (best_score, best_pose_name)
    """
    try:
        # Convert string representation to dictionary
        import ast
        
        # Check if the pose_pred_str is already a dictionary
        if isinstance(pose_pred_str, dict):
            pose_dict = pose_pred_str
        elif pose_pred_str is None:
            return None, None
        else:
            # Try to safely evaluate the string representation
            pose_dict = ast.literal_eval(pose_pred_str)
        
        # Find the pose with the best (lowest) score
        best_score = float('inf')
        best_pose = None
        
        for pose_name, pose_data in pose_dict.items():
            # The pose_data is a list where the first element is a list of scores
            # and the second element is the path to the pose file
            if pose_data and isinstance(pose_data[0], list) and pose_data[0]:
                score = pose_data[0][0]  # Get the first score from the first list
                if score < best_score:
                    best_score = score
                    best_pose = pose_name
        
        if best_pose:
            return best_score, best_pose.replace('.pdbqt', '')
        else:
            return None, None
    
    except Exception as e:
        # Try to extract the best score directly from the string if parsing failed
        try:
            if isinstance(pose_pred_str, str):
                # Look for patterns like [[-6.2, ...]] to extract the best score
                import re
                score_match = re.search(r'\[\[([-\d\.]+)', pose_pred_str)
                if score_match:
                    return float(score_match.group(1)), "unknown_pose"
        except:
            pass
        
        logger.warning(f"Error extracting pose data: {e}")
        return None, None 