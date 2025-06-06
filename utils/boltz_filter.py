import subprocess
import json
import logging
from pathlib import Path
from typing import List, Tuple, Callable, Union
import numpy as np
import yaml

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
        log_cb("[Boltz-2] Executing: " + " ".join(cmd))
    
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
                    log_cb(f"[Boltz-2] Command failed (exit {result.returncode}): {result.stderr.strip()}")
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
                    log_cb(f"[Boltz-2] Command failed (exit {result.returncode}): {result.stderr.strip()}")
                return False
                
    except subprocess.TimeoutExpired:
        if log_cb:
            log_cb(f"[Boltz-2] Command timed out after {timeout} seconds")
        return False
    except Exception as exc:  # pragma: no cover
        if log_cb:
            log_cb(f"[Boltz-2] Unexpected error running command: {exc}")
        return False


def _extract_protein_sequence_from_pdb(pdb_file: Path, log_cb: Callable[[str], None] | None = None) -> str:
    """Extract protein sequence from PDB file using pdb_tofasta command.
    
    Args:
        pdb_file: Path to input PDB file.
        log_cb: Optional logging callback.
        
    Returns:
        Protein sequence as a single line string, or empty string if failed.
    """
    if log_cb:
        log_cb(f"[Boltz-2] Extracting protein sequence from PDB: {pdb_file}")
    
    try:
        result = subprocess.run(
            ["pdb_tofasta", str(pdb_file)], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True, 
            check=True,
            timeout=60  # 1 minute timeout for PDB conversion
        )
        
        # Parse FASTA output to extract sequence
        lines = result.stdout.strip().split('\n')
        sequence_lines = []
        
        for line in lines:
            line = line.strip()
            if not line.startswith('>') and line:
                # Remove any whitespace from sequence
                sequence_lines.append(line.replace(' ', ''))
        
        # Join all sequence lines into one
        sequence = ''.join(sequence_lines)
        
        if not sequence:
            if log_cb:
                log_cb(f"[Boltz-2] ERROR: No sequence extracted from {pdb_file}")
            return ""
            
        if log_cb:
            log_cb(f"[Boltz-2] Extracted sequence length: {len(sequence)}")
            
        return sequence
        
    except subprocess.CalledProcessError as exc:
        if log_cb:
            log_cb(f"[Boltz-2] pdb_tofasta failed (exit {exc.returncode}): {exc.stderr.strip()}")
        return ""
    except subprocess.TimeoutExpired:
        if log_cb:
            log_cb(f"[Boltz-2] pdb_tofasta timed out for {pdb_file}")
        return ""
    except Exception as exc:  # pragma: no cover
        if log_cb:
            log_cb(f"[Boltz-2] Unexpected error in pdb_tofasta: {exc}")
        return ""


def _create_boltz_yaml(yaml_path: Path, protein_sequence: str, smiles: str, log_cb: Callable[[str], None] | None = None) -> None:
    """Create YAML file for Boltz-2 prediction in the required format.
    
    Args:
        yaml_path: Path where the YAML file should be created.
        protein_sequence: Protein sequence string.
        smiles: SMILES string of the ligand.
        log_cb: Optional logging callback.
    """
    if not protein_sequence or not protein_sequence.strip():
        raise ValueError("Empty or invalid protein sequence provided")
    
    if not smiles or not smiles.strip():
        raise ValueError("Empty or invalid SMILES string provided")
    
    # Clean inputs
    protein_sequence = protein_sequence.strip()
    smiles = smiles.strip()
    
    # Create YAML structure
    yaml_data = {
        'version': 1,
        'sequences': [
            {
                'protein': {
                    'id': 'A',
                    'sequence': protein_sequence
                }
            },
            {
                'ligand': {
                    'id': 'B',
                    'smiles': smiles
                }
            }
        ],
        'properties': [
            {
                'affinity': {
                    'binder': 'B'
                }
            }
        ]
    }
    
    # Write YAML file
    try:
        with yaml_path.open('w', encoding='utf-8') as f:
            yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)
        
        if log_cb:
            log_cb(f"[Boltz-2] Created YAML file: {yaml_path}")
            
    except Exception as exc:
        if log_cb:
            log_cb(f"[Boltz-2] Failed to create YAML file {yaml_path}: {exc}")
        raise



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


def _parse_boltz_affinity(predictions_dir: Path, input_name: str = "input") -> dict:
    """Extract affinity predictions from Boltz-2 affinity JSON file.
    
    Args:
        predictions_dir: Path to the predictions directory produced by Boltz-2.
        input_name: Name of the input file (default "input").
        
    Returns:
        Dictionary containing affinity predictions, or empty dict if file not found.
    """
    affinity_file = predictions_dir / input_name / f"affinity_{input_name}.json"
    
    if not affinity_file.exists():
        return {}
    
    try:
        with open(affinity_file, 'r') as f:
            affinity_data = json.load(f)
        return affinity_data
    except Exception as exc:
        logging.warning(f"[Boltz-2] Failed to parse affinity file {affinity_file}: {exc}")
        return {}


def _parse_boltz_confidence(predictions_dir: Path, input_name: str = "input") -> dict:
    """Extract confidence scores from Boltz-2 confidence JSON file.
    
    Args:
        predictions_dir: Path to the predictions directory produced by Boltz-2.
        input_name: Name of the input file (default "input").
        
    Returns:
        Dictionary containing confidence scores, or empty dict if file not found.
    """
    confidence_file = predictions_dir / input_name / f"confidence_{input_name}_model_0.json"
    
    if not confidence_file.exists():
        return {}
    
    try:
        with open(confidence_file, 'r') as f:
            confidence_data = json.load(f)
        return confidence_data
    except Exception as exc:
        logging.warning(f"[Boltz-2] Failed to parse confidence file {confidence_file}: {exc}")
        return {}


def _parse_boltz_cif(
    predictions_dir: Path,
    input_name: str = "input",
    chain: str = "B",
    reference_pdb: Union[str, Path, None] = None,
) -> Tuple[List[Tuple[float, float, float]], dict, dict]:
    """Extract atomic coordinates and metadata from a Boltz-2 prediction.

    If *reference_pdb* is provided, the CIF structure will first be aligned to the
    reference structure using Bio.PDB's CE algorithm (``CEAligner``). This ensures
    the coordinates are expressed in the same reference frame as the input target
    structure before the ligand position is evaluated.

    Args:
        predictions_dir: Path to the predictions directory produced by Boltz-2.
        input_name: Name of the input file (default "input").
        chain: Chain identifier whose coordinates should be extracted (default "B").
        reference_pdb: Path to the reference PDB file to which the CIF structure
            should be aligned. If *None*, no alignment is performed.

    Returns:
        Tuple containing:
        - List of ``(x, y, z)`` tuples for all atoms in the requested chain
        - Dictionary of affinity predictions
        - Dictionary of confidence scores
    """
    # Locate the CIF file
    cif_path = predictions_dir / input_name / f"{input_name}_model_0.cif"
    
    if not cif_path.exists():
        raise FileNotFoundError(f"Boltz-2 CIF file not found: {cif_path}")

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
                f"[Boltz-2] Alignment of CIF to reference failed ({cif_path.name}): {exc}. Proceeding without alignment."
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

    # Parse affinity and confidence data ---------------------------------------
    affinity_data = _parse_boltz_affinity(predictions_dir, input_name)
    confidence_data = _parse_boltz_confidence(predictions_dir, input_name)

    return coords, affinity_data, confidence_data


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
    """Run the Boltz-2 blind-docking filter over a list of variants.

    The function executes the Boltz-2 workflow for each ligand using YAML format and determines 
    whether the ligand is positioned inside the predefined docking box. Variants that pass the 
    check are tagged with *PASSBLINDDOCK* while failures are tagged with *FAILBLINDDOCK* (or a 
    more specific error status).

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
    
    # Extract protein sequence once from the PDB file
    protein_sequence = _extract_protein_sequence_from_pdb(Path(pdb_file), log_callback)
    if not protein_sequence:
        # If we can't extract the protein sequence, fail all variants
        for variant in variants:
            variant["status"] = "BOLTZFAIL_PROTEIN_SEQUENCE"
            failed.append(variant)
        return passed, failed
    
    for variant in variants:
        barcode = variant.get("barcode", "UNKNOWN")
        smiles = variant.get("smiles")

        if not smiles:
            variant["status"] = "BOLTZFAIL_NOSMILES"
            failed.append(variant)
            continue

        if log_callback:
            log_callback(f"[Boltz-2] Processing variant {barcode}")

        try:
            # Prepare directories ---------------------------------------------------
            var_root = round_dir / "Boltz_result" / barcode
            var_root.mkdir(parents=True, exist_ok=True)
            
            input_yaml = var_root / "input.yaml"

            # Step 1 – Create YAML file --------------------------------------------
            _create_boltz_yaml(input_yaml, protein_sequence, smiles, log_callback)

            # Step 2 – Run Boltz-2 prediction with --use_potentials -----------
            boltz_output_dir = var_root
            boltz_success = False
            max_retries = 2
            
            for retry in range(max_retries):
                if log_callback and retry > 0:
                    log_callback(f"[Boltz-2] Retry {retry} for variant {barcode}")
                
                if _run_cmd(
                    [
                        "boltz", 
                        "predict", 
                        str(input_yaml), 
                        "--use_msa_server",
                        "--use_potentials",
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

            # Step 3 – Locate and parse CIF file -----------------------------------
            # Check for predictions directory, handle both direct and nested structures
            predictions_dir = boltz_output_dir / "predictions"
            if not predictions_dir.exists():
                # Check for nested structure (boltz creates a subdirectory named after input file)
                nested_dirs = [d for d in boltz_output_dir.iterdir() if d.is_dir() and (d / "predictions").exists()]
                if nested_dirs:
                    predictions_dir = nested_dirs[0] / "predictions"
                    if log_callback:
                        log_callback(f"[Boltz-2] Found predictions in nested directory: {predictions_dir}")
                else:
                    variant["status"] = "BOLTZFAIL_NOCIF"
                    failed.append(variant)
                    continue

            # Parse coordinates and metadata from the predicted structure
            coords, affinity_data, confidence_data = _parse_boltz_cif(
                predictions_dir, 
                input_name="input", 
                chain="B", 
                reference_pdb=pdb_file
            )
            
            if not coords:
                variant["status"] = "BOLTZFAIL_NOCIF"
                failed.append(variant)
                continue

            # Step 4 – Simple coordinate evaluation --------------------------------
            inside_box = any(_coords_within_box(coord, center, box_size) for coord in coords)
            
            # Add affinity and confidence data to variant
            if affinity_data:
                # Store primary affinity value
                if "affinity_pred_value" in affinity_data:
                    variant["affinity_pred_value"] = affinity_data["affinity_pred_value"]
                if "affinity_probability_binary" in affinity_data:
                    variant["affinity_probability_binary"] = affinity_data["affinity_probability_binary"]
                
                # Store additional affinity values if available
                for key in ["affinity_pred_value1", "affinity_probability_binary1", 
                           "affinity_pred_value2", "affinity_probability_binary2"]:
                    if key in affinity_data:
                        variant[key] = affinity_data[key]
                
                if log_callback:
                    affinity_val = affinity_data.get("affinity_pred_value", "N/A")
                    affinity_prob = affinity_data.get("affinity_probability_binary", "N/A")
                    log_callback(f"[Boltz-2] {barcode} affinity: {affinity_val} (probability: {affinity_prob})")
            
            if confidence_data:
                # Store key confidence metrics
                for key in ["confidence_score", "ptm", "iptm", "ligand_iptm", "protein_iptm", 
                           "complex_plddt", "complex_iplddt"]:
                    if key in confidence_data:
                        variant[key] = confidence_data[key]
                
                if log_callback and "confidence_score" in confidence_data:
                    conf_score = confidence_data["confidence_score"]
                    log_callback(f"[Boltz-2] {barcode} confidence score: {conf_score}")
            
            if log_callback:
                log_callback(f"[Boltz-2] {barcode} evaluation: {'PASS' if inside_box else 'FAIL'} (any atom within box)")

            if inside_box:
                variant["status"] = "PASSBLINDDOCK"
                passed.append(variant)
            else:
                variant["status"] = "FAILBLINDDOCK"
                failed.append(variant)
                
        except Exception as exc:  # pragma: no cover
            if log_callback:
                log_callback(f"[Boltz-2] Unexpected error for {barcode}: {exc}")
            variant["status"] = "BOLTZFAIL_ERROR"
            failed.append(variant)

    return passed, failed 