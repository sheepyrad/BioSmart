import subprocess
import json
import logging
from pathlib import Path
from typing import List, Tuple, Callable, Union

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
        log_cb("[Protenix] Executing: " + " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return True
    except subprocess.CalledProcessError as exc:
        if log_cb:
            log_cb(f"[Protenix] Command failed (exit {exc.returncode}): {exc.stderr.strip()}")
        return False
    except Exception as exc:  # pragma: no cover
        if log_cb:
            log_cb(f"[Protenix] Unexpected error running command: {exc}")
        return False


def _add_ligand_to_json(json_path: Path, smiles: str, log_cb: Callable[[str], None] | None = None) -> None:
    """Append ligand information to the Protenix input JSON."""
    if not json_path.exists():
        raise FileNotFoundError(f"JSON not found: {json_path}")

    with json_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, list) or not data:
        raise ValueError("Unexpected Protenix JSON structure – expected list with at least one element.")

    ligand_entry = {
        "ligand": {
            "ligand": smiles,
            "count": 1,
        }
    }

    data[0].setdefault("sequences", []).append(ligand_entry)

    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=4)

    if log_cb:
        log_cb(f"[Protenix] Added ligand SMILES to JSON: {smiles}")


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


def _parse_cif_coords(
    cif_path: Path,
    chain: str = "B",
    reference_pdb: Union[str, Path, None] = None,
) -> List[Tuple[float, float, float]]:
    """Extract atomic coordinates for a chain from a CIF file, optionally after alignment.

    If *reference_pdb* is provided, the CIF structure will first be aligned to the
    reference structure using Bio.PDB's CE algorithm (``CEAligner``). This ensures
    the coordinates are expressed in the same reference frame as the input target
    structure before the ligand position is evaluated.

    Args:
        cif_path: Path to the mmCIF file produced by Protenix.
        chain: Chain identifier whose coordinates should be extracted (default "B").
        reference_pdb: Path to the reference PDB file to which the CIF structure
            should be aligned. If *None*, no alignment is performed.

    Returns:
        List of ``(x, y, z)`` tuples for all atoms in the requested chain.
    """

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
                f"[Protenix] Alignment of CIF to reference failed ({cif_path.name}): {exc}. Proceeding without alignment."
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


def protenix_filter_variants(
    variants: List[dict],
    pdb_file: Union[str, Path],
    round_dir: Path,
    center: Tuple[float, float, float],
    box_size: Tuple[int, int, int],
    log_callback: Union[Callable[[str], None], None] = None,
    seeds: int = 101,
) -> Tuple[List[dict], List[dict]]:
    """Run the Protenix blind-docking filter over a list of variants.

    The function executes the Protenix workflow for each ligand and determines whether the
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
        seeds: Random seed for Protenix prediction (defaults to ``101``).

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
            variant["status"] = "PROTENIXFAIL_NOSMILES"
            failed.append(variant)
            continue

        if log_callback:
            log_callback(f"[Protenix] Processing variant {barcode}")

        try:
            # Prepare directories ---------------------------------------------------
            var_root = round_dir / "Protenix_result" / barcode
            json_dir = var_root / "json"
            msa_dir = var_root / "msa"
            pred_dir = var_root / "prediction"

            json_dir.mkdir(parents=True, exist_ok=True)
            msa_dir.mkdir(parents=True, exist_ok=True)
            pred_dir.mkdir(parents=True, exist_ok=True)

            # Step 1 – tojson --------------------------------------------------------
            if not _run_cmd(["protenix", "tojson", "--input", pdb_file, "--out_dir", str(json_dir)], log_callback):
                variant["status"] = "PROTENIXFAIL_TOJSON"
                failed.append(variant)
                continue

            json_files = list(json_dir.glob("*.json"))
            if not json_files:
                variant["status"] = "PROTENIXFAIL_NOJSON"
                failed.append(variant)
                continue
            base_json = json_files[0]

            # Step 2 – add ligand ----------------------------------------------------
            _add_ligand_to_json(base_json, smiles, log_callback)

            # Step 3 – msa -----------------------------------------------------------
            if not _run_cmd(["protenix", "msa", "--input", str(base_json), "--out_dir", str(msa_dir)], log_callback):
                variant["status"] = "PROTENIXFAIL_MSA"
                failed.append(variant)
                continue

            msa_json_candidates = list(base_json.parent.glob(f"{base_json.stem}-add-msa.json"))
            if not msa_json_candidates:
                msa_json_candidates = list(base_json.parent.glob("*-add-msa.json"))
            if not msa_json_candidates:
                variant["status"] = "PROTENIXFAIL_NO_MSA_JSON"
                failed.append(variant)
                continue
            msa_json = msa_json_candidates[0]

            # Step 4 – predict -------------------------------------------------------
            if not _run_cmd(
                [
                    "protenix",
                    "predict",
                    "--input",
                    str(msa_json),
                    "--out_dir",
                    str(pred_dir),
                    "--seeds",
                    str(seeds),
                ],
                log_callback,
            ):
                variant["status"] = "PROTENIXFAIL_PREDICT"
                failed.append(variant)
                continue

            # Step 5 – locate CIF ----------------------------------------------------
            cif_files = list(pred_dir.rglob("*_sample_0.cif"))
            if not cif_files:
                variant["status"] = "PROTENIXFAIL_NOCIF"
                failed.append(variant)
                continue
            cif_path = cif_files[0]

            # Step 6 – evaluate coordinates -----------------------------------------
            coords = _parse_cif_coords(cif_path, chain="B", reference_pdb=pdb_file)
            inside_box = any(_coords_within_box(c, center, box_size) for c in coords)

            if inside_box:
                variant["status"] = "PASSBLINDDOCK"
                passed.append(variant)
            else:
                variant["status"] = "FAILBLINDDOCK"
                failed.append(variant)
        except Exception as exc:  # pragma: no cover
            if log_callback:
                log_callback(f"[Protenix] Unexpected error for {barcode}: {exc}")
            variant["status"] = "PROTENIXFAIL_ERROR"
            failed.append(variant)

    return passed, failed 