"""Targets the scientist uploads or chooses from ~/BioSmart/inputs.

The host lists names in that folder. It does not accept a host path.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_TARGET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
_TARGET_SUFFIXES = (".pdb", ".cif", ".mmcif", ".ent")


class TargetRejected(ValueError):
    """The upload or the choice is not a Target in the inputs folder."""


class TargetNotFound(Exception):
    """No Target with this name is in the inputs folder."""


def inputs_dir() -> Path:
    override = os.environ.get("BIOSMART_INPUTS")
    if override:
        return Path(override).expanduser()
    return Path.home() / "BioSmart" / "inputs"


def list_targets(root: Path) -> list[dict[str, object]]:
    if not isinstance(root, Path):
        raise TypeError("root must be a path")
    if not root.is_dir():
        return []
    found: list[dict[str, object]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if path.is_symlink() or not path.is_file():
            continue
        if not _is_target_name(path.name):
            continue
        found.append({"id": path.name, "name": path.name, "bytes": path.stat().st_size})
    return found


def store_target(root: Path, filename: str, payload: bytes) -> dict[str, object]:
    """Write an uploaded Target into the inputs folder and return its name."""
    if not isinstance(root, Path):
        raise TypeError("root must be a path")
    if not isinstance(filename, str) or not isinstance(payload, bytes):
        raise TypeError("filename must be a string and payload must be bytes")
    if not payload:
        raise TargetRejected("A Target file is empty")
    name = _target_name(filename)
    try:
        root.mkdir(parents=True, exist_ok=True)
        folder = root.resolve()
        chosen = _unique_name(folder, name)
        destination = (folder / chosen).resolve()
        if destination.parent != folder:
            raise TargetRejected("Choose a Target from the list")
        partial = destination.with_name(destination.name + ".partial")
        partial.write_bytes(payload)
        partial.replace(destination)
    except OSError as exc:
        raise TargetRejected("The inputs folder could not store the Target") from exc
    return {"id": chosen, "name": chosen, "bytes": len(payload)}


def resolve_target(root: Path, target_id: str) -> dict[str, object]:
    """Return one Target that is already in the inputs folder."""
    if not isinstance(root, Path):
        raise TypeError("root must be a path")
    if not isinstance(target_id, str) or not _is_target_name(target_id):
        raise TargetRejected("Choose a Target from the list")
    if not root.is_dir():
        raise TargetNotFound(target_id)
    path = root / target_id
    if path.is_symlink():
        raise TargetNotFound(target_id)
    folder = root.resolve()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise TargetNotFound(target_id) from exc
    if resolved.parent != folder or not resolved.is_file():
        raise TargetNotFound(target_id)
    return {"id": target_id, "name": target_id, "bytes": resolved.stat().st_size}


def _is_target_name(name: str) -> bool:
    if not _TARGET_ID.fullmatch(name):
        return False
    lowered = name.lower()
    return any(lowered.endswith(suffix) for suffix in _TARGET_SUFFIXES)


def _target_name(filename: str) -> str:
    base = Path(filename).name
    if base != filename or not _is_target_name(base):
        raise TargetRejected("A Target is a PDB or mmCIF file with a plain file name")
    return base


def _unique_name(folder: Path, name: str) -> str:
    if not (folder / name).exists():
        return name
    stem = Path(name).stem
    suffix = Path(name).suffix
    for number in range(2, 1000):
        candidate = f"{stem}-{number}{suffix}"
        if _is_target_name(candidate) and not (folder / candidate).exists():
            return candidate
    raise TargetRejected("A Target with that name already exists")
