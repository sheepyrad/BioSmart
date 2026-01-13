#!/usr/bin/env python3
"""
Script to convert SMILES from CSV to mol2 files using OpenBabel.
Names files as "BB {ID} Direct.mol2"
"""

import pandas as pd
import subprocess
import os
from pathlib import Path

# Path to obabel binary in conda environment
OBABEL_PATH = "/media/data/conrad_hku/miniforge3/envs/fronted/bin/obabel"


def convert_smiles_to_mol2(csv_path: str, output_dir: str):
    """
    Convert SMILES from CSV to mol2 files using obabel.
    
    Args:
        csv_path: Path to the CSV file containing ID and SMILES columns
        output_dir: Directory to save mol2 files
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Read CSV file
    df = pd.read_csv(csv_path)
    
    print(f"Found {len(df)} molecules to convert")
    print(f"Output directory: {output_dir}")
    
    successful = 0
    failed = 0
    
    for idx, row in df.iterrows():
        mol_id = row['ID']
        smiles = row['SMILES']
        
        # Create output filename: "BB {ID} Direct.mol2"
        output_filename = f"BB {mol_id} Direct.mol2"
        output_path = os.path.join(output_dir, output_filename)
        
        # Use obabel to convert SMILES to mol2
        # -ismi: input format is SMILES
        # -omol2: output format is mol2
        # --gen3d: generate 3D coordinates
        # -h: add hydrogens
        cmd = [
            OBABEL_PATH,
            '-ismi',
            '-omol2',
            '--gen3d',
            '-h',
            '-O', output_path
        ]
        
        try:
            # Run obabel with SMILES as stdin
            result = subprocess.run(
                cmd,
                input=smiles,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0 and os.path.exists(output_path):
                print(f"✓ Converted ID {mol_id}: {output_filename}")
                successful += 1
            else:
                print(f"✗ Failed ID {mol_id}: {result.stderr.strip()}")
                failed += 1
                
        except subprocess.TimeoutExpired:
            print(f"✗ Timeout for ID {mol_id}")
            failed += 1
        except Exception as e:
            print(f"✗ Error for ID {mol_id}: {e}")
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"Conversion complete!")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Total: {successful + failed}")


if __name__ == "__main__":
    # Input CSV file
    csv_path = "/home/conrad_hku/Drug_pipeline/Boltz_frag_valid/above0.8_dedup_3dsynth_boltz_direct.csv"
    
    # Output directory
    output_dir = "/home/conrad_hku/Drug_pipeline/mol2_convert"
    
    convert_smiles_to_mol2(csv_path, output_dir)
