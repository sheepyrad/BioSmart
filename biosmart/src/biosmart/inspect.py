"""A Candidate's stored pose in the Pocket.

The Run database is the source of truth. This module does not read the Index.
A pose is drawn only when the Run recorded one. Otherwise the Candidate has
no stored pose.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

_CANDIDATE_ID = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._-"
_STRUCTURE_SUFFIXES = {".pdb", ".cif", ".mmcif", ".ent"}
_POSE_SUFFIXES = {".sdf", ".mol", ".pdb"}


class PoseMissing(LookupError):
    """The Run database has no Candidate with this id."""


class PoseError(ValueError):
    """The pose cannot be drawn."""


def candidate_pose(
    run_folder: Path,
    candidate_id: str,
    *,
    inputs_root: Path | None = None,
) -> dict[str, Any]:
    """The stored pose for one Candidate, beside the Pocket.

    ``pose`` is null when the Run database has no pose file for this Candidate.
    """
    if not isinstance(run_folder, Path):
        raise TypeError("run_folder must be a Path")
    if not isinstance(candidate_id, str) or not candidate_id or any(character not in _CANDIDATE_ID for character in candidate_id):
        raise PoseMissing(candidate_id)
    if inputs_root is not None and not isinstance(inputs_root, Path):
        raise TypeError("inputs_root must be a Path")

    row = _candidate_row(run_folder / "run.sqlite", candidate_id)
    if row is None:
        raise PoseMissing(candidate_id)
    smiles = row["canonical_smiles"]
    if not isinstance(smiles, str) or not smiles:
        raise PoseError("Candidate cannot be drawn")

    residues, reference_ligand = _pocket(run_folder)
    stored = _stored_pose(run_folder, row["pose_ref"])
    pose_atoms = _atoms_from_file(stored) if stored is not None else None
    if stored is not None and not pose_atoms:
        raise PoseError("Stored pose cannot be drawn")
    pocket_atoms = _pocket_atoms(_target_text(run_folder, inputs_root), set(residues))

    pocket: dict[str, Any] = {"residues": residues}
    if reference_ligand is not None:
        pocket["reference_ligand"] = reference_ligand
    return {
        "candidate_id": candidate_id,
        "canonical_smiles": smiles,
        "status": row["status"],
        "score": None if row["reward"] is None else float(row["reward"]),
        "failure_reason": row["failure_reason"],
        "pocket": pocket,
        "stored": pose_atoms is not None,
        "pose": None if pose_atoms is None else [_round_atom(atom) for atom in pose_atoms],
        "pocket_atoms": [_round_atom(atom) for atom in pocket_atoms],
    }


def _candidate_row(database: Path, candidate_id: str) -> sqlite3.Row | None:
    if not database.is_file():
        raise PoseError("Run folder is missing its Run database")
    uri = f"file:{database}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            """
            SELECT id, canonical_smiles, status, failure_reason, reward, pose_ref
            FROM candidates
            WHERE id = ?
            """,
            (candidate_id,),
        ).fetchone()
    finally:
        connection.close()


def _pocket(run_folder: Path) -> tuple[list[str], str | bool | None]:
    spec_path = run_folder / "spec.json"
    if not spec_path.is_file():
        return [], None
    try:
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], None
    if not isinstance(payload, dict):
        return [], None
    pocket = payload.get("pocket")
    if not isinstance(pocket, dict):
        return [], None
    raw = pocket.get("residues")
    residues = [item for item in raw if isinstance(item, str)] if isinstance(raw, list) else []
    ligand = pocket.get("reference_ligand")
    reference: str | bool | None = None
    if isinstance(ligand, str) and ligand.strip():
        name = Path(ligand).name
        reference = name if name == ligand else True
    return residues, reference


def _target_text(run_folder: Path, inputs_root: Path | None) -> str:
    structure = _target_structure(run_folder, inputs_root)
    if structure is None:
        return ""
    try:
        return structure.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _target_structure(run_folder: Path, inputs_root: Path | None) -> Path | None:
    target_dir = run_folder / "target"
    if target_dir.is_dir():
        for child in sorted(target_dir.iterdir()):
            if child.is_file() and child.suffix.lower() in _STRUCTURE_SUFFIXES:
                return child
    spec_path = run_folder / "spec.json"
    if inputs_root is None or not spec_path.is_file():
        return None
    try:
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    target = payload.get("target")
    if not isinstance(target, dict):
        return None
    structure = target.get("structure")
    if not isinstance(structure, str) or not structure:
        return None
    candidate = Path(structure) if Path(structure).is_absolute() else inputs_root / structure
    if not candidate.is_file() or candidate.suffix.lower() not in _STRUCTURE_SUFFIXES:
        return None
    try:
        resolved = candidate.resolve()
        root = inputs_root.resolve()
    except OSError:
        return None
    if resolved != root and root not in resolved.parents:
        return None
    return resolved


def _stored_pose(run_folder: Path, pose_ref: str | None) -> Path | None:
    if not isinstance(pose_ref, str) or not pose_ref:
        return None
    raw = Path(pose_ref)
    candidate = raw if raw.is_absolute() else run_folder / raw
    try:
        resolved = candidate.resolve()
        root = run_folder.resolve()
    except OSError:
        return None
    if resolved != root and root not in resolved.parents:
        return None
    if not resolved.is_file() or resolved.suffix.lower() not in _POSE_SUFFIXES:
        return None
    return resolved


def _atoms_from_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".pdb":
        return _pdb_atoms(text, residue=None)
    from rdkit import Chem

    parsed = Chem.MolFromMolBlock(text, sanitize=False, removeHs=False)
    if parsed is None:
        raise PoseError("Candidate cannot be drawn")
    return _heavy_atoms(parsed)


def _heavy_atoms(parsed: Any) -> list[dict[str, Any]]:
    if parsed.GetNumConformers() < 1:
        return []
    conformer = parsed.GetConformer()
    atoms: list[dict[str, Any]] = []
    for atom in parsed.GetAtoms():
        if atom.GetAtomicNum() == 1:
            continue
        position = conformer.GetAtomPosition(atom.GetIdx())
        atoms.append(
            {
                "element": atom.GetSymbol(),
                "x": float(position.x),
                "y": float(position.y),
                "z": float(position.z),
            }
        )
    return atoms


def _pocket_atoms(text: str, residues: set[str]) -> list[dict[str, Any]]:
    if not text or not residues:
        return []
    if "_atom_site." in text:
        return _mmcif_atoms(text, residues)
    return _pdb_atoms(text, residues)


def _pdb_atoms(text: str, residue: set[str] | None) -> list[dict[str, Any]]:
    atoms: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith(("ATOM", "HETATM")) or len(line) < 54:
            continue
        chain = (line[21] if len(line) > 21 else " ").strip() or "A"
        number = line[22:26].strip()
        residue_id = f"{chain}:{number}"
        if residue is not None and residue_id not in residue:
            continue
        name = line[12:16].strip() or "C"
        element = line[76:78].strip() if len(line) >= 78 else ""
        if not element:
            element = name[0]
        try:
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
        except ValueError:
            continue
        atoms.append({"residue": residue_id, "name": name, "element": element, "x": x, "y": y, "z": z})
    return atoms


def _mmcif_atoms(text: str, residues: set[str]) -> list[dict[str, Any]]:
    lines = text.splitlines()
    header: list[str] = []
    collecting = False
    atoms: list[dict[str, Any]] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("_atom_site."):
            collecting = True
            header.append(stripped.split(".", 1)[1])
            continue
        if not collecting:
            continue
        if stripped.startswith("#") or stripped.startswith("loop_") or stripped.startswith("_"):
            if atoms or not stripped.startswith("ATOM") and not stripped[:1].isdigit() and not stripped.startswith("HETATM"):
                if header and not stripped.startswith("ATOM") and not stripped.startswith("HETATM"):
                    break
            continue
        if not stripped or stripped.startswith("#"):
            break
        parts = stripped.split()
        if len(parts) < len(header):
            continue
        fields = dict(zip(header, parts, strict=False))
        chain = fields.get("auth_asym_id") or fields.get("label_asym_id") or "A"
        number = fields.get("auth_seq_id") or fields.get("label_seq_id") or ""
        residue_id = f"{chain}:{number}"
        if residue_id not in residues:
            continue
        try:
            x = float(fields["Cartn_x"])
            y = float(fields["Cartn_y"])
            z = float(fields["Cartn_z"])
        except (KeyError, ValueError):
            continue
        element = fields.get("type_symbol") or "C"
        name = fields.get("auth_atom_id") or fields.get("label_atom_id") or element
        atoms.append({"residue": residue_id, "name": name, "element": element, "x": x, "y": y, "z": z})
    return atoms


def _round_atom(atom: dict[str, Any]) -> dict[str, Any]:
    rounded = dict(atom)
    for key in ("x", "y", "z"):
        rounded[key] = round(float(atom[key]), 3)
    return rounded


__all__ = ["PoseError", "PoseMissing", "candidate_pose"]
