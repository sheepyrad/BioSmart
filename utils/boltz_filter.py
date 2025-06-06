import subprocess
import json
import logging
from pathlib import Path
from typing import List, Tuple, Callable, Union
import numpy as np

from Bio.PDB import PDBParser, MMCIFParser  
from Bio.PDB.cealign import CEAligner

# Import the new environment manager
from .environment_manager import env_manager

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------


def _run_cmd(cmd: List[str], log_cb: Callable[[str], None] | None = None, timeout: int | None = None) -> bool:
    """Run a subprocess command using the appropriate conda environment.

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
        # Determine which environment to use based on the command
        if cmd[0] == "boltz":
            # Use Boltz environment for Boltz commands with streaming output
            result = env_manager.run_tool(
                tool_name="boltz",
                command=cmd,
                timeout=timeout,
                capture_output=True,
                text=True,
                check=False,
                log_callback=log_cb,
                stream_output=True  # Enable real-time output streaming
            )
            
            if result.returncode == 0:
                return True
            else:
                if log_cb:
                    log_cb(f"[Boltz-1x] Command failed (exit {result.returncode}): {result.stderr.strip()}")
                return False
        else:
            # For other commands (like pdb_tofasta), use the main drug_pipeline environment
            # These are typically available in the main environment
            result = subprocess.run(
                cmd, 
                check=False, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                timeout=timeout
            )
            
            if result.returncode == 0:
                return True
            else:
                if log_cb:
                    log_cb(f"[Boltz-1x] Command failed (exit {result.returncode}): {result.stderr.strip()}")
                return False
                
    except subprocess.TimeoutExpired:
        if log_cb:
            log_cb(f"[Boltz-1x] Command timed out after {timeout} seconds")
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

    Returns:
        (passed_variants, failed_variants) – with updated ``status`` keys.
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
            log_callback(f"[Boltz-1x] Processing variant {barcode}")

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
            # Check for predictions directory, handle both direct and nested structures
            predictions_dir = boltz_output_dir / "predictions"
            if not predictions_dir.exists():
                # Check for nested structure (boltz creates a subdirectory named after input file)
                nested_dirs = [d for d in boltz_output_dir.iterdir() if d.is_dir() and (d / "predictions").exists()]
                if nested_dirs:
                    predictions_dir = nested_dirs[0] / "predictions"
                    if log_callback:
                        log_callback(f"[Boltz-1x] Found predictions in nested directory: {predictions_dir}")
                else:
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

            # Step 5 – Simple coordinate evaluation --------------------------------
            inside_box = any(_coords_within_box(coord, center, box_size) for coord in coords)
            
            if log_callback:
                log_callback(f"[Boltz-1x] {barcode} evaluation: {'PASS' if inside_box else 'FAIL'} (any atom within box)")

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