import subprocess
import json
import logging
from pathlib import Path
from typing import List, Tuple, Callable, Union
import numpy as np

from Bio.PDB import PDBParser, MMCIFParser  
from Bio.PDB.cealign import CEAligner

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------


def _run_cmd(cmd: List[str], log_cb: Callable[[str], None] | None = None, timeout: int | None = None) -> bool:
    """Run a subprocess command.

    Args:
        cmd: Command split into a list.
        log_cb: Optional logging callback.
        timeout: Timeout in seconds.

    Returns:
        True if the command exits with code 0, else False.
    """
    if log_cb:
        log_cb("[Boltz-1x] Executing: " + " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return True
    except subprocess.CalledProcessError as exc:
        if log_cb:
            log_cb(f"[Boltz-1x] Command failed (exit {exc.returncode}): {exc.stderr.strip()}")
        return False
    except Exception as exc:  # pragma: no cover
        if log_cb:
            log_cb(f"[Boltz-1x] Unexpected error running command: {exc}")
        return False


def _pdb_to_fasta(pdb_file: Path, output_fasta: Path, log_cb: Callable[[str], None] | None = None) -> bool:
    """Convert PDB to FASTA using pdb_tofasta command.
    
    Args:
        pdb_file: Path to input PDB file.
        output_fasta: Path to output FASTA file.
        log_cb: Optional logging callback.
        
    Returns:
        True if conversion successful, False otherwise.
    """
    if log_cb:
        log_cb(f"[Boltz-1x] Converting PDB to FASTA: {pdb_file} -> {output_fasta}")
    
    try:
        with open(output_fasta, 'w') as f:
            result = subprocess.run(
                ["pdb_tofasta", str(pdb_file)], 
                stdout=f, 
                stderr=subprocess.PIPE, 
                text=True, 
                check=True,
                timeout=60  # 1 minute timeout for PDB conversion
            )
        
        # Verify the output file was created and is not empty
        if not output_fasta.exists() or output_fasta.stat().st_size == 0:
            if log_cb:
                log_cb(f"[Boltz-1x] ERROR: pdb_tofasta produced no output for {pdb_file}")
            return False
            
        return True
    except subprocess.CalledProcessError as exc:
        if log_cb:
            log_cb(f"[Boltz-1x] pdb_tofasta failed (exit {exc.returncode}): {exc.stderr.strip()}")
        return False
    except subprocess.TimeoutExpired:
        if log_cb:
            log_cb(f"[Boltz-1x] pdb_tofasta timed out for {pdb_file}")
        return False
    except Exception as exc:  # pragma: no cover
        if log_cb:
            log_cb(f"[Boltz-1x] Unexpected error in pdb_tofasta: {exc}")
        return False


def _fix_protein_fasta_format(fasta_path: Path, log_cb: Callable[[str], None] | None = None) -> None:
    """Fix the protein FASTA format to match Boltz-1x requirements.
    
    Changes >PDB|A to >A|protein| and removes whitespace from sequence lines.
    
    Args:
        fasta_path: Path to the FASTA file to fix.
        log_cb: Optional logging callback.
    """
    if not fasta_path.exists():
        raise FileNotFoundError(f"FASTA file not found: {fasta_path}")
    
    # Read the original content
    with fasta_path.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()
    
    # Process the lines
    fixed_lines = []
    current_sequence = []
    
    for line in lines:
        line = line.strip()
        if line.startswith(">"):
            # If we have accumulated sequence lines, join them
            if current_sequence:
                fixed_lines.append("".join(current_sequence) + "\n")
                current_sequence = []
            
            # Fix the header format
            if line.startswith(">PDB|A"):
                fixed_lines.append(">A|protein|\n")
            else:
                fixed_lines.append(line + "\n")
        else:
            # Accumulate sequence lines (remove any whitespace)
            if line:
                current_sequence.append(line.replace(" ", ""))
    
    # Don't forget the last sequence if file doesn't end with newline
    if current_sequence:
        fixed_lines.append("".join(current_sequence) + "\n")
    
    # Write back the fixed content
    with fasta_path.open("w", encoding="utf-8") as fh:
        fh.writelines(fixed_lines)
    
    if log_cb:
        log_cb(f"[Boltz-1x] Fixed protein FASTA format: {fasta_path}")


def _add_ligand_to_fasta(fasta_path: Path, smiles: str, log_cb: Callable[[str], None] | None = None) -> None:
    """Append ligand SMILES to FASTA file in Boltz-1x format.
    
    Args:
        fasta_path: Path to the FASTA file to modify.
        smiles: SMILES string of the ligand.
        log_cb: Optional logging callback.
    """
    if not fasta_path.exists():
        raise FileNotFoundError(f"FASTA file not found: {fasta_path}")
    
    # Validate SMILES string
    if not smiles or not smiles.strip():
        raise ValueError("Empty or invalid SMILES string provided")
    
    # Clean the SMILES string (remove whitespace)
    smiles = smiles.strip()
    
    # Verify the FASTA file has content before appending
    with fasta_path.open("r", encoding="utf-8") as fh:
        content = fh.read().strip()
        if not content:
            raise ValueError("Empty FASTA file - cannot append ligand")
        if not content.startswith(">"):
            raise ValueError("Invalid FASTA format - file does not start with '>'")
    
    ligand_entry = f">B|smiles\n{smiles}\n"
    
    with fasta_path.open("a", encoding="utf-8") as fh:
        fh.write(ligand_entry)
    
    if log_cb:
        log_cb(f"[Boltz-1x] Added ligand SMILES to FASTA: {smiles}")


# -----------------------------------------------------------------------------
# Coordinate parsing helpers
# -----------------------------------------------------------------------------


def _coords_within_box(coord: Tuple[float, float, float], center: Tuple[float, float, float], box: Tuple[float, float, float]) -> bool:
    """Check if a coordinate lies within a defined rectangular box."""
    x, y, z = coord
    cx, cy, cz = center
    sx, sy, sz = box
    return (
        cx - sx / 2 <= x <= cx + sx / 2
        and cy - sy / 2 <= y <= cy + sy / 2
        and cz - sz / 2 <= z <= cz + sz / 2
    )


def _parse_boltz_cif(
    predictions_dir: Path,
    input_name: str = "input",
    chain: str = "B",
    reference_pdb: Union[str, Path, None] = None,
) -> List[Tuple[float, float, float]]:
    """Extract atomic coordinates for a chain from a Boltz-1x CIF file, optionally after alignment.

    If *reference_pdb* is provided, the CIF structure will first be aligned to the
    reference structure using Bio.PDB's CE algorithm (``CEAligner``). This ensures
    the coordinates are expressed in the same reference frame as the input target
    structure before the ligand position is evaluated.

    Args:
        predictions_dir: Path to the predictions directory produced by Boltz-1x.
        input_name: Name of the input file (default "input").
        chain: Chain identifier whose coordinates should be extracted (default "B").
        reference_pdb: Path to the reference PDB file to which the CIF structure
            should be aligned. If *None*, no alignment is performed.

    Returns:
        List of ``(x, y, z)`` tuples for all atoms in the requested chain.
    """
    # Locate the CIF file
    cif_path = predictions_dir / input_name / f"{input_name}_model_0.cif"
    
    if not cif_path.exists():
        raise FileNotFoundError(f"Boltz-1x CIF file not found: {cif_path}")

    # Parse the CIF structure ---------------------------------------------------
    cif_parser = MMCIFParser(QUIET=True)
    structure = cif_parser.get_structure("pred", str(cif_path))

    # Optional alignment step ---------------------------------------------------
    if reference_pdb is not None:
        try:
            pdb_parser = PDBParser(QUIET=True)
            ref_structure = pdb_parser.get_structure("ref", str(reference_pdb))

            aligner = CEAligner()
            # The CEAligner aligns backbone atoms (Cα) and transforms *structure* in place
            aligner.set_reference(ref_structure)
            aligner.align(structure, transform=True)
            
        except Exception as exc:  # pragma: no cover – alignment failures shouldn't crash
            logging.warning(
                f"[Boltz-1x] Alignment of CIF to reference failed ({cif_path.name}): {exc}. Proceeding without alignment."
            )

    # Collect coordinates for the requested chain ------------------------------
    coords: List[Tuple[float, float, float]] = []
    for model in structure:
        for ch in model:
            if ch.id != chain:
                continue
            for atom in ch.get_atoms():
                x, y, z = atom.coord
                coords.append((float(x), float(y), float(z)))

    return coords


def _calculate_geometric_center(coords: List[Tuple[float, float, float]]) -> Tuple[float, float, float]:
    """Calculate the geometric center (centroid) of a set of coordinates.
    
    Args:
        coords: List of (x, y, z) coordinate tuples.
        
    Returns:
        (x, y, z) tuple representing the geometric center.
    """
    if not coords:
        raise ValueError("Cannot calculate center of empty coordinate list")
    
    coords_array = np.array(coords)
    center = np.mean(coords_array, axis=0)
    return tuple(center)


def _calculate_bounding_box(coords: List[Tuple[float, float, float]]) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Calculate the bounding box of a set of coordinates.
    
    Args:
        coords: List of (x, y, z) coordinate tuples.
        
    Returns:
        Tuple of (min_coords, max_coords) where each is an (x, y, z) tuple.
    """
    if not coords:
        raise ValueError("Cannot calculate bounding box of empty coordinate list")
    
    coords_array = np.array(coords)
    min_coords = tuple(np.min(coords_array, axis=0))
    max_coords = tuple(np.max(coords_array, axis=0))
    return min_coords, max_coords


def _fraction_atoms_in_box(coords: List[Tuple[float, float, float]], center: Tuple[float, float, float], box: Tuple[float, float, float]) -> float:
    """Calculate the fraction of atoms that are inside the docking box.
    
    Args:
        coords: List of (x, y, z) coordinate tuples.
        center: Center of the docking box (x, y, z).
        box: Dimensions of the docking box (x, y, z).
        
    Returns:
        Fraction of atoms inside the box (0.0 to 1.0).
    """
    if not coords:
        return 0.0
    
    atoms_inside = sum(1 for coord in coords if _coords_within_box(coord, center, box))
    return atoms_inside / len(coords)


def _bounding_box_overlap(coords: List[Tuple[float, float, float]], center: Tuple[float, float, float], box: Tuple[float, float, float]) -> float:
    """Calculate the overlap between ligand bounding box and docking box.
    
    Args:
        coords: List of (x, y, z) coordinate tuples.
        center: Center of the docking box (x, y, z).
        box: Dimensions of the docking box (x, y, z).
        
    Returns:
        Overlap volume as fraction of ligand bounding box volume.
    """
    if not coords:
        return 0.0
    
    # Calculate ligand bounding box
    min_coords, max_coords = _calculate_bounding_box(coords)
    
    # Calculate docking box bounds
    cx, cy, cz = center
    sx, sy, sz = box
    dock_min = (cx - sx/2, cy - sy/2, cz - sz/2)
    dock_max = (cx + sx/2, cy + sy/2, cz + sz/2)
    
    # Calculate intersection
    intersect_min = (
        max(min_coords[0], dock_min[0]),
        max(min_coords[1], dock_min[1]),
        max(min_coords[2], dock_min[2])
    )
    intersect_max = (
        min(max_coords[0], dock_max[0]),
        min(max_coords[1], dock_max[1]),
        min(max_coords[2], dock_max[2])
    )
    
    # Check if there's any overlap
    if (intersect_min[0] >= intersect_max[0] or 
        intersect_min[1] >= intersect_max[1] or 
        intersect_min[2] >= intersect_max[2]):
        return 0.0
    
    # Calculate volumes
    intersect_volume = ((intersect_max[0] - intersect_min[0]) * 
                       (intersect_max[1] - intersect_min[1]) * 
                       (intersect_max[2] - intersect_min[2]))
    
    ligand_volume = ((max_coords[0] - min_coords[0]) * 
                    (max_coords[1] - min_coords[1]) * 
                    (max_coords[2] - min_coords[2]))
    
    return intersect_volume / ligand_volume if ligand_volume > 0 else 0.0


def _evaluate_ligand_position(
    coords: List[Tuple[float, float, float]], 
    center: Tuple[float, float, float], 
    box: Tuple[float, float, float],
    method: str = "geometric_center"
) -> Tuple[bool, dict]:
    """Evaluate if ligand is properly positioned in the docking box using various methods.
    
    Args:
        coords: List of (x, y, z) coordinate tuples for the ligand.
        center: Center of the docking box (x, y, z).
        box: Dimensions of the docking box (x, y, z).
        method: Evaluation method - "any_atom", "geometric_center", "majority_atoms", 
                "bounding_box_overlap", or "combined".
        
    Returns:
        Tuple of (passes_filter, metrics_dict) where metrics_dict contains
        detailed evaluation metrics.
    """
    if not coords:
        return False, {"error": "No coordinates provided"}
    
    # Calculate all metrics
    metrics = {}
    
    # Basic metrics
    any_atom_inside = any(_coords_within_box(coord, center, box) for coord in coords)
    metrics["any_atom_inside"] = any_atom_inside
    
    geometric_center = _calculate_geometric_center(coords)
    center_inside = _coords_within_box(geometric_center, center, box)
    metrics["geometric_center_inside"] = center_inside
    metrics["geometric_center"] = geometric_center
    
    fraction_inside = _fraction_atoms_in_box(coords, center, box)
    metrics["fraction_atoms_inside"] = fraction_inside
    
    overlap_fraction = _bounding_box_overlap(coords, center, box)
    metrics["bounding_box_overlap"] = overlap_fraction
    
    # Apply the selected method
    if method == "any_atom":
        passes = any_atom_inside
    elif method == "geometric_center":
        passes = center_inside
    elif method == "majority_atoms":
        passes = fraction_inside > 0.5
    elif method == "bounding_box_overlap":
        passes = overlap_fraction > 0.1  # At least 10% overlap
    elif method == "combined":
        # Combined approach: center inside OR significant overlap OR majority of atoms
        passes = (center_inside or 
                 overlap_fraction > 0.3 or 
                 fraction_inside > 0.6)
    else:
        raise ValueError(f"Unknown evaluation method: {method}")
    
    metrics["method_used"] = method
    metrics["passes_filter"] = passes
    
    return passes, metrics


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def boltz_filter_variants(
    variants: List[dict],
    pdb_file: Union[str, Path],
    round_dir: Path,
    center: Tuple[float, float, float],
    box_size: Tuple[int, int, int],
    log_callback: Union[Callable[[str], None], None] = None,
    evaluation_method: str = "combined",
) -> Tuple[List[dict], List[dict]]:
    """Run the Boltz-1x blind-docking filter over a list of variants.

    The function executes the Boltz-1x workflow for each ligand and determines whether the
    ligand is positioned inside the predefined docking box. Variants that pass the check are
    tagged with *PASSBLINDDOCK* while failures are tagged with *FAILBLINDDOCK* (or a more
    specific error status).

    Args:
        variants: List of variant dictionaries (each *must* have ``barcode`` and ``smiles`` keys).
        pdb_file: Path to the target protein PDB file.
        round_dir: Path corresponding to the current round directory (e.g., *.../round_1*).
        center: Docking box centre (x, y, z).
        box_size: Docking box dimensions (x, y, z).
        log_callback: Optional logger function.
        evaluation_method: Method for evaluating ligand position - "any_atom", "geometric_center", 
                          "majority_atoms", "bounding_box_overlap", or "combined" (default).

    Returns:
        (passed_variants, failed_variants) – with updated ``status`` keys and evaluation metrics.
    """
    pdb_file = str(pdb_file)

    passed: List[dict] = []
    failed: List[dict] = []
    
    for variant in variants:
        barcode = variant.get("barcode", "UNKNOWN")
        smiles = variant.get("smiles")

        if not smiles:
            variant["status"] = "BOLTZFAIL_NOSMILES"
            failed.append(variant)
            continue

        if log_callback:
            log_callback(f"[Boltz-1x] Processing variant {barcode} using {evaluation_method} evaluation")

        try:
            # Prepare directories ---------------------------------------------------
            var_root = round_dir / "Boltz_result" / barcode
            var_root.mkdir(parents=True, exist_ok=True)
            
            input_fasta = var_root / "input.fasta"

            # Step 1 – Convert PDB to FASTA ----------------------------------------
            if not _pdb_to_fasta(Path(pdb_file), input_fasta, log_callback):
                variant["status"] = "BOLTZFAIL_TOFASTA"
                failed.append(variant)
                continue

            # Step 1.5 – Fix protein FASTA format ----------------------------------
            _fix_protein_fasta_format(input_fasta, log_callback)

            # Step 2 – Add ligand SMILES to FASTA ----------------------------------
            _add_ligand_to_fasta(input_fasta, smiles, log_callback)

            # Step 3 – Run Boltz-1x prediction -------------------------------------
            boltz_output_dir = var_root
            boltz_success = False
            max_retries = 2
            
            for retry in range(max_retries):
                if log_callback and retry > 0:
                    log_callback(f"[Boltz-1x] Retry {retry} for variant {barcode}")
                
                if _run_cmd(
                    [
                        "boltz", 
                        "predict", 
                        str(input_fasta), 
                        "--use_msa_server", 
                        "--out_dir", 
                        str(boltz_output_dir)
                    ],
                    log_callback,
                    timeout=600  # 10 minute timeout for Boltz prediction
                ):
                    boltz_success = True
                    break
                    
                # If not the last retry, wait a bit before retrying
                if retry < max_retries - 1:
                    import time
                    time.sleep(30)  # Wait 30 seconds before retry
            
            if not boltz_success:
                variant["status"] = "BOLTZFAIL_PREDICT"
                failed.append(variant)
                continue

            # Step 4 – Locate and parse CIF file -----------------------------------
            predictions_dir = boltz_output_dir / "predictions"
            if not predictions_dir.exists():
                variant["status"] = "BOLTZFAIL_NOCIF"
                failed.append(variant)
                continue

            # Parse coordinates from the predicted structure
            coords = _parse_boltz_cif(
                predictions_dir, 
                input_name="input", 
                chain="B", 
                reference_pdb=pdb_file
            )
            
            if not coords:
                variant["status"] = "BOLTZFAIL_NOCIF"
                failed.append(variant)
                continue

            # Step 5 – Evaluate coordinates using improved methods ----------------
            inside_box, metrics = _evaluate_ligand_position(coords, center, box_size, evaluation_method)
            
            # Store evaluation metrics in the variant
            variant["boltz_metrics"] = metrics
            
            if log_callback:
                log_callback(f"[Boltz-1x] {barcode} evaluation: {metrics}")

            if inside_box:
                variant["status"] = "PASSBLINDDOCK"
                passed.append(variant)
            else:
                variant["status"] = "FAILBLINDDOCK"
                failed.append(variant)
                
        except Exception as exc:  # pragma: no cover
            if log_callback:
                log_callback(f"[Boltz-1x] Unexpected error for {barcode}: {exc}")
            variant["status"] = "BOLTZFAIL_ERROR"
            failed.append(variant)

    return passed, failed 


def get_evaluation_method_info() -> dict:
    """Get information about available ligand position evaluation methods.
    
    Returns:
        Dictionary with method names as keys and descriptions as values.
    """
    return {
        "any_atom": {
            "description": "Passes if ANY ligand atom is inside the docking box",
            "use_case": "Very permissive - good for initial screening",
            "pros": "High sensitivity, catches partial binding",
            "cons": "May accept ligands that are mostly outside the box"
        },
        "geometric_center": {
            "description": "Passes if the geometric center of the ligand is inside the box",
            "use_case": "Balanced approach - ligand center must be in target region",
            "pros": "Good balance of specificity and sensitivity",
            "cons": "May reject ligands with center outside but significant overlap"
        },
        "majority_atoms": {
            "description": "Passes if >50% of ligand atoms are inside the docking box",
            "use_case": "Ensures most of the ligand is in the target region",
            "pros": "High specificity, ensures good binding site occupancy",
            "cons": "May be too strict for large ligands or edge cases"
        },
        "bounding_box_overlap": {
            "description": "Passes if >10% of ligand bounding box overlaps with docking box",
            "use_case": "Good for irregularly shaped ligands or binding sites",
            "pros": "Accounts for ligand shape and size",
            "cons": "May be less intuitive than atom-based methods"
        },
        "combined": {
            "description": "Passes if center is inside OR >30% bounding box overlap OR >60% atoms inside",
            "use_case": "Recommended default - combines multiple criteria",
            "pros": "Robust, handles various ligand shapes and binding modes",
            "cons": "More complex logic, may need tuning for specific systems"
        }
    }


def analyze_ligand_positioning(
    coords: List[Tuple[float, float, float]], 
    center: Tuple[float, float, float], 
    box: Tuple[float, float, float]
) -> dict:
    """Analyze ligand positioning using all available methods for comparison.
    
    Args:
        coords: List of (x, y, z) coordinate tuples for the ligand.
        center: Center of the docking box (x, y, z).
        box: Dimensions of the docking box (x, y, z).
        
    Returns:
        Dictionary with results from all evaluation methods.
    """
    methods = ["any_atom", "geometric_center", "majority_atoms", "bounding_box_overlap", "combined"]
    results = {}
    
    for method in methods:
        passes, metrics = _evaluate_ligand_position(coords, center, box, method)
        results[method] = {
            "passes": passes,
            "metrics": metrics
        }
    
    return results 