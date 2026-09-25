"""Pocket grid from selected residues.

Used by the Boltz-2 optimization entry point to place the generation box
on the residues that define the Pocket.
"""

import time
from pathlib import Path
from typing import Optional

import numpy as np
from Bio.PDB import PDBParser


def generate_grid_config(
    pdb_path: str | Path,
    residues: list[str],
    output_dir: Optional[Path] = None,
) -> dict:
    """
    Generate grid configuration based on PDB file and targeted residues.

    Parameters
    ----------
    pdb_path : str | Path
        Path to PDB file
    residues : list[str]
        List of residues for targeted docking (format: ['A:123', 'B:456'])
    output_dir : Optional[Path]
        Directory to save config file

    Returns
    -------
    dict with config_path, grid_dimensions, config_text

    Raises
    ------
    ValueError
        If no residues specified or no atoms found
    RuntimeError
        If grid generation fails
    """
    if not residues:
        raise ValueError("target_residues must be provided for targeted grid box generation.")

    try:
        parser = PDBParser(QUIET=True)
        structure = parser.get_structure("protein", pdb_path)

        coords = []
        # Extract coordinates of specific residues
        for residue_spec in residues:
            residue_spec = residue_spec.strip()
            chain_id, res_id = residue_spec.split(":")
            chain_id = chain_id.strip()
            res_id = res_id.strip()

            for chain in structure.get_chains():
                if chain.id == chain_id:
                    for res in chain.get_residues():
                        if res.id[1] == int(res_id):  # Match residue number
                            for atom in res:
                                coords.append(atom.coord)

        if not coords:
            raise ValueError("No atoms found for the specified residues.")

        coords = np.array(coords)
        min_coords = coords.min(axis=0)
        max_coords = coords.max(axis=0)

        # Use center of mass (centroid) for tighter fit around target residues
        # This positions the box more optimally to cover just the target residues
        center = coords.mean(axis=0)
        size = max_coords - min_coords

        # Create configuration file for grid box
        config_text = f"""center_x = {center[0]}
center_y = {center[1]}
center_z = {center[2]}
size_x = {size[0]}
size_y = {size[1]}
size_z = {size[2]}"""

        # Generate a unique filename using timestamp
        timestamp = int(time.time())
        config_filename = f"config_targeted_{timestamp}.txt"

        if output_dir is None:
            output_dir = Path.cwd()
        else:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

        config_path = output_dir / config_filename

        with open(config_path, "w") as f:
            f.write(config_text)

        # Extract grid dimensions to return
        grid_dimensions = {
            "center_x": float(center[0]),
            "center_y": float(center[1]),
            "center_z": float(center[2]),
            "size_x": float(size[0]),
            "size_y": float(size[1]),
            "size_z": float(size[2]),
        }

        return {
            "config_path": str(config_path),
            "config_filename": config_filename,
            "grid_dimensions": grid_dimensions,
            "config_text": config_text,
        }

    except Exception as e:
        raise RuntimeError(f"Error during grid generation: {str(e)}") from e
