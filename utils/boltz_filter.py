import subprocess
import json
import logging
from pathlib import Path
from typing import List, Tuple, Callable, Union

from Bio.PDB import PDBParser, MMCIFParser  
from Bio.PDB.Superimposer import Superimposer

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

            # Extract CA atoms from both structures for alignment
            ref_ca_atoms = []
            moving_ca_atoms = []
            
            # Get CA atoms from reference structure (first model, first chain)
            ref_model = list(ref_structure)[0]
            ref_chain = list(ref_model)[0]
            for residue in ref_chain:
                if residue.has_id('CA'):
                    ref_ca_atoms.append(residue['CA'])
            
            # Get CA atoms from moving structure (first model, first chain that's not the ligand chain)
            moving_model = list(structure)[0]
            for chain in moving_model:
                if chain.id != "B":  # Skip ligand chain (B)
                    for residue in chain:
                        if residue.has_id('CA'):
                            moving_ca_atoms.append(residue['CA'])
                    break  # Only use first protein chain
            
            # Ensure we have the same number of CA atoms for alignment
            min_length = min(len(ref_ca_atoms), len(moving_ca_atoms))
            if min_length < 3:
                raise ValueError("Insufficient CA atoms for alignment")
            
            ref_ca_atoms = ref_ca_atoms[:min_length]
            moving_ca_atoms = moving_ca_atoms[:min_length]
            
            # Perform superimposition
            superimposer = Superimposer()
            superimposer.set_atoms(ref_ca_atoms, moving_ca_atoms)
            
            # Apply transformation to all atoms in the structure
            all_atoms = []
            for model in structure:
                for chain in model:
                    for residue in chain:
                        for atom in residue:
                            all_atoms.append(atom)
            
            superimposer.apply(all_atoms)
            
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

            # Step 5 – Evaluate coordinates ----------------------------------------
            inside_box = any(_coords_within_box(c, center, box_size) for c in coords)

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