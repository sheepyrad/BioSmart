"""Coordinates a Scorer returned for one Candidate.

These are the predicted pose. Nothing here builds a conformer from SMILES.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

_WATER = {"HOH", "WAT", "DOD", "TIP", "SOL"}
_STRUCTURE_SUFFIXES = {".sdf", ".mol", ".pdb"}


@dataclass(frozen=True)
class PoseAtom:
    element: str
    x: float
    y: float
    z: float


def pose_from_payload(value: object) -> tuple[PoseAtom, ...] | None:
    """Parse atoms a Scorer returned. None when the Scorer returned no pose."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("pose must be a list of atoms")
    if not value:
        return None
    atoms: list[PoseAtom] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("pose atom must be an object")
        element = item.get("element")
        if not isinstance(element, str) or not element.isalpha() or not 1 <= len(element) <= 2:
            raise ValueError("pose element is invalid")
        atoms.append(
            PoseAtom(
                element=element.upper(),
                x=_coordinate(item.get("x")),
                y=_coordinate(item.get("y")),
                z=_coordinate(item.get("z")),
            )
        )
    return tuple(atoms)


def pose_to_json(atoms: tuple[PoseAtom, ...]) -> list[dict[str, float | str]]:
    return [{"element": atom.element, "x": atom.x, "y": atom.y, "z": atom.z} for atom in atoms]


def write_pose_pdb(path: Path, atoms: tuple[PoseAtom, ...]) -> None:
    """Write predicted coordinates. The file is the stored pose."""
    if not atoms:
        raise ValueError("pose has no atoms")
    lines = [_pdb_line(index, atom) for index, atom in enumerate(atoms, start=1)]
    lines.append("END")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def atoms_from_pose_record(path: Path, lmdb_key: str) -> tuple[PoseAtom, ...] | None:
    """Read a pose file a Pose provider already wrote. Missing files yield None."""
    if not isinstance(path, Path) or not isinstance(lmdb_key, str) or not lmdb_key:
        return None
    suffix = path.suffix.lower()
    try:
        if path.is_file() and suffix in _STRUCTURE_SUFFIXES:
            return _atoms_from_structure_file(path)
        if suffix == ".lmdb" or (path.is_dir() and (path / "data.mdb").is_file()):
            return _atoms_from_lmdb(path, lmdb_key)
    except (OSError, ValueError):
        return None
    return None


def ligand_pose_from_prediction(out_dir: Path, stem: str) -> tuple[PoseAtom, ...] | None:
    """Ligand atoms from a structure file Boltz-2 already wrote for this Candidate."""
    if not isinstance(out_dir, Path) or not out_dir.is_dir():
        return None
    if not isinstance(stem, str) or not stem or "/" in stem or "\\" in stem:
        return None
    matches = sorted(out_dir.rglob(f"{stem}_model_0.pdb"))
    if not matches:
        matches = [path for path in sorted(out_dir.rglob(f"{stem}*.pdb")) if "confidence" not in path.name]
    for path in matches:
        try:
            atoms = _ligand_atoms(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if atoms:
            return atoms
    return None


def _coordinate(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("pose coordinate must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("pose coordinate must be finite")
    return number


def _coord_field(value: float) -> str:
    text = f"{value:8.3f}"
    if len(text) != 8:
        raise ValueError("pose coordinate does not fit a structure file")
    return text


def _pdb_line(serial: int, atom: PoseAtom) -> str:
    if serial > 99999:
        raise ValueError("pose has too many atoms")
    element = atom.element.upper()
    atom_name = f" {element:<3s}" if len(element) == 1 else f"{element:<4s}"
    return (
        f"HETATM{serial:5d} {atom_name}"
        f" LIG L{1:4d}    "
        f"{_coord_field(atom.x)}{_coord_field(atom.y)}{_coord_field(atom.z)}"
        f"  1.00  0.00          {element:>2s}"
    )


def _atoms_from_structure_file(path: Path) -> tuple[PoseAtom, ...] | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".pdb":
        ligand = _ligand_atoms(text)
        return ligand or _pdb_atoms(text)
    return _sdf_atoms(text)


def _ligand_atoms(text: str) -> tuple[PoseAtom, ...] | None:
    atoms: list[PoseAtom] = []
    for line in text.splitlines():
        if not line.startswith("HETATM") or len(line) < 54:
            continue
        residue = line[17:20].strip().upper()
        if residue in _WATER:
            continue
        parsed = _pdb_atom(line)
        if parsed is not None:
            atoms.append(parsed)
    return tuple(atoms) if atoms else None


def _pdb_atoms(text: str) -> tuple[PoseAtom, ...] | None:
    atoms: list[PoseAtom] = []
    for line in text.splitlines():
        if not line.startswith(("ATOM", "HETATM")) or len(line) < 54:
            continue
        parsed = _pdb_atom(line)
        if parsed is not None:
            atoms.append(parsed)
    return tuple(atoms) if atoms else None


def _pdb_atom(line: str) -> PoseAtom | None:
    name = line[12:16].strip() or "C"
    element = line[76:78].strip() if len(line) >= 78 else ""
    if not element:
        element = name[0]
    if not element.isalpha():
        return None
    try:
        return PoseAtom(element.upper(), float(line[30:38]), float(line[38:46]), float(line[46:54]))
    except ValueError:
        return None


def _sdf_atoms(text: str) -> tuple[PoseAtom, ...] | None:
    from rdkit import Chem

    parsed = Chem.MolFromMolBlock(text, sanitize=False, removeHs=False)
    if parsed is None or parsed.GetNumConformers() < 1:
        return None
    conformer = parsed.GetConformer()
    atoms: list[PoseAtom] = []
    for atom in parsed.GetAtoms():
        position = conformer.GetAtomPosition(atom.GetIdx())
        atoms.append(PoseAtom(atom.GetSymbol().upper(), float(position.x), float(position.y), float(position.z)))
    return tuple(atoms) if atoms else None


def _atoms_from_lmdb(path: Path, key: str) -> tuple[PoseAtom, ...] | None:
    try:
        import lmdb
    except ImportError:
        return None
    environment = lmdb.open(str(path), readonly=True, lock=False, subdir=path.is_dir())
    try:
        with environment.begin() as transaction:
            raw = transaction.get(key.encode("utf-8"))
    finally:
        environment.close()
    if not raw:
        return None
    return _sdf_atoms(raw.decode("utf-8", errors="replace"))
