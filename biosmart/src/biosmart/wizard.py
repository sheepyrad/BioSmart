"""Wizard facts for starting a Run from the localhost host.

Advanced controls are the Run spec schema fields marked for the scientist.
Uploads are stored by the server. The wizard never accepts a typed host path.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from biosmart.eta import estimate_eta_seconds
from biosmart.inputs import inputs_dir
from biosmart.presets import PRESET_BUDGETS, PresetName
from biosmart.residues import read_structure, sequence_for
from biosmart.spec import RunSpec

_PRESET_LABELS: dict[PresetName, str] = {
    "quick": "Quick",
    "standard": "Standard",
    "thorough": "Thorough",
}
_LIGAND_SUFFIXES = {".sdf", ".mol", ".mol2", ".pdb"}
_ALIGNMENT_SUFFIXES = {".a3m", ".fasta", ".fa", ".aln"}
_TARGET_SUFFIXES = {".pdb", ".cif", ".mmcif", ".ent"}


class StartRejected(ValueError):
    """The wizard payload is not a Run the server can start."""


def selectable_scorers() -> list[dict[str, str]]:
    """Boltz-2 and FlashBind. FABind+ is the Pose provider, not a Scorer."""
    scorers = [
        {
            "id": "boltz2",
            "name": "Boltz-2",
            "pocket": "residues",
            "prompt": "Boltz-2 asks for selected residues.",
            "summary": "Co-folding Scorer. It predicts the Target–Candidate complex and an affinity.",
        },
        {
            "id": "flashbind",
            "name": "FlashBind",
            "pocket": "reference_ligand",
            "prompt": "FlashBind asks for a Reference ligand.",
            "pose_provider": "FABind+",
            "summary": "Affinity Scorer. It scores a docked pose.",
        },
    ]
    if os.environ.get("BIOSMART_WIZARD_FAKE") == "1":
        scorers.append(
            {
                "id": "fake",
                "name": "FakeScorer",
                "pocket": "residues",
                "prompt": "Selected residues define this Pocket.",
                "summary": "CPU Scorer for a workstation where a GPU is not required.",
            }
        )
    return scorers


def ligands_dir() -> Path:
    override = os.environ.get("BIOSMART_LIGANDS")
    if override:
        return Path(override).expanduser()
    return inputs_dir() / "ligands"


def alignments_dir() -> Path:
    override = os.environ.get("BIOSMART_ALIGNMENTS")
    if override:
        return Path(override).expanduser()
    return inputs_dir() / "alignments"


def store_reference_ligand(root: Path, filename: str, payload: bytes) -> dict[str, object]:
    stored = _store_upload(
        root,
        filename,
        payload,
        suffixes=_LIGAND_SUFFIXES,
        rejected="A Reference ligand is an SDF, MOL, MOL2, or PDB file with a plain file name",
    )
    return stored


def store_alignment(root: Path, filename: str, payload: bytes) -> dict[str, object]:
    return _store_upload(
        root,
        filename,
        payload,
        suffixes=_ALIGNMENT_SUFFIXES,
        rejected="Upload an alignment file with a plain file name",
    )


def describe_presets(runs_root: Path) -> dict[str, object]:
    """Named Budgets. The ETA comes from recorded Scoring-round durations."""
    if not isinstance(runs_root, Path):
        raise TypeError("runs_root must be a Path")
    rounds = observed_scoring_rounds(runs_root)
    presets: list[dict[str, object]] = []
    for name, (iterations, candidates) in PRESET_BUDGETS.items():
        eta = None
        if rounds:
            eta = estimate_eta_seconds(
                rounds,
                iterations=iterations,
                candidates_per_iteration=candidates,
                completed_iterations=0,
            )
        presets.append(
            {
                "id": name,
                "name": _PRESET_LABELS[name],
                "iterations": iterations,
                "candidates_per_iteration": candidates,
                "eta_seconds": eta,
            }
        )
    return {"presets": presets}


def observed_scoring_rounds(runs_root: Path) -> list[tuple[int, float]]:
    """(Candidates sent, seconds) from every Run database under the Runs root."""
    if not runs_root.is_dir():
        return []
    rounds: list[tuple[int, float]] = []
    for database in sorted(runs_root.glob("*/run.sqlite")):
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            try:
                rows = connection.execute("SELECT n_sent, secs FROM scoring_rounds").fetchall()
            except sqlite3.Error:
                continue
        finally:
            connection.close()
        for n_sent, secs in rows:
            if isinstance(n_sent, int) and not isinstance(n_sent, bool) and n_sent >= 1:
                if isinstance(secs, (int, float)) and not isinstance(secs, bool) and secs >= 0:
                    rounds.append((n_sent, float(secs)))
    return rounds


def advanced_fields(schema: Mapping[str, Any] | None = None) -> list[dict[str, object]]:
    """Walk the Run spec schema for controls the wizard did not already ask for."""
    document = dict(schema) if schema is not None else RunSpec.model_json_schema()
    found: list[dict[str, object]] = []

    def resolve(node: object) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            cursor: object = document
            for part in ref[2:].split("/"):
                if not isinstance(cursor, dict) or part not in cursor:
                    return {}
                cursor = cursor[part]
            if not isinstance(cursor, dict):
                return {}
            merged = dict(cursor)
            for key, value in node.items():
                if key != "$ref":
                    merged[key] = value
            return merged
        return node

    def walk(node: object, prefix: str) -> None:
        resolved = resolve(node)
        properties = resolved.get("properties")
        if not isinstance(properties, dict):
            return
        for key, prop in properties.items():
            if not isinstance(key, str):
                continue
            child = resolve(prop)
            path = f"{prefix}.{key}" if prefix else key
            if child.get("advanced") is True:
                widget = child.get("widget")
                if not isinstance(widget, str) or not widget:
                    widget = "number" if child.get("type") == "integer" else "text"
                field: dict[str, object] = {
                    "path": path,
                    "title": child.get("title") if isinstance(child.get("title"), str) else key,
                    "widget": widget,
                }
                accept = child.get("accept")
                if isinstance(accept, str) and accept:
                    field["accept"] = accept
                found.append(field)
            if isinstance(child.get("properties"), dict):
                walk(child, path)

    walk(document, "")
    return found


def progress_from_events(events: list[Mapping[str, Any]]) -> dict[str, object]:
    """Latest Iteration, Scoring round, and ETA from the engine event stream."""
    iteration = None
    iterations = None
    candidates = None
    round_no = None
    eta: float | None = None
    for event in events:
        kind = event.get("type")
        if kind == "run.started":
            iterations = _optional_int(event.get("iterations"))
            candidates = _optional_int(event.get("candidates_per_iteration"))
        elif kind in {"round.started", "round.finished", "iteration"}:
            recorded_iteration = _optional_int(event.get("iteration"))
            if recorded_iteration is not None:
                iteration = recorded_iteration
            recorded_round = _optional_int(event.get("round_no"))
            if recorded_round is not None:
                round_no = recorded_round
            recorded_eta = event.get("eta_seconds")
            if isinstance(recorded_eta, (int, float)) and not isinstance(recorded_eta, bool):
                eta = float(recorded_eta)
    return {
        "iteration": iteration,
        "iterations": iterations,
        "candidates_per_iteration": candidates,
        "round_no": round_no,
        "eta_seconds": eta,
    }


def prepare_start_payload(
    payload: Mapping[str, Any],
    *,
    inputs_root: Path,
    ligands_root: Path,
    alignments_root: Path,
) -> dict[str, Any]:
    """Replace uploaded ids with stored files. A typed host path is rejected."""
    if not isinstance(payload, Mapping):
        raise StartRejected("Run spec must be an object")
    spec: dict[str, Any] = dict(payload)
    target = spec.get("target")
    if isinstance(target, Mapping):
        spec["target"] = _resolve_target(dict(target), inputs_root, alignments_root, spec.get("scorer"), spec.get("pocket"))
    pocket = spec.get("pocket")
    if isinstance(pocket, Mapping):
        spec["pocket"] = _resolve_pocket(dict(pocket), ligands_root)
    return spec


def _resolve_target(
    target: dict[str, Any],
    inputs_root: Path,
    alignments_root: Path,
    scorer: object,
    pocket: object,
) -> dict[str, Any]:
    structure = target.get("structure")
    name = target.get("name")
    chosen = structure.strip() if isinstance(structure, str) else ""
    if not chosen and isinstance(name, str) and _structure_file(inputs_root, name) is not None:
        chosen = name
    if chosen:
        if not _plain_name(chosen):
            raise StartRejected("Choose a Target from the list")
        stored = _structure_file(inputs_root, chosen)
        if stored is None:
            raise StartRejected("Choose a Target from the list")
        target["structure"] = str(stored)
    elif "structure" in target and target["structure"] in {None, ""}:
        target.pop("structure", None)

    msa = target.get("msa")
    if msa in {None, ""}:
        target.pop("msa", None)
    elif isinstance(msa, str):
        if not _plain_name(msa):
            raise StartRejected("Upload an alignment file")
        stored_msa = _file_inside(alignments_root, msa)
        if stored_msa is None:
            raise StartRejected("Upload an alignment file")
        target["msa"] = str(stored_msa)
    sequence = target.get("sequence")
    needs_sequence = scorer == "boltz2" and (not isinstance(sequence, str) or not sequence.strip())
    structure_path = target.get("structure")
    if needs_sequence and isinstance(structure_path, str):
        residues: list[str] = []
        if isinstance(pocket, Mapping) and isinstance(pocket.get("residues"), list):
            residues = [item for item in pocket["residues"] if isinstance(item, str)]
        filled = sequence_for(read_structure(Path(structure_path)), residues)
        if filled:
            target["sequence"] = filled
    return target


def _resolve_pocket(pocket: dict[str, Any], ligands_root: Path) -> dict[str, Any]:
    ligand = pocket.get("reference_ligand")
    if ligand in {None, ""}:
        pocket.pop("reference_ligand", None)
        return pocket
    if not isinstance(ligand, str) or not _plain_name(ligand):
        raise StartRejected("Upload a Reference ligand")
    stored = _file_inside(ligands_root, ligand)
    if stored is None:
        raise StartRejected("Upload a Reference ligand")
    pocket["reference_ligand"] = str(stored)
    return pocket


def _store_upload(
    root: Path,
    filename: str,
    payload: bytes,
    *,
    suffixes: set[str],
    rejected: str,
) -> dict[str, object]:
    if not isinstance(root, Path):
        raise TypeError("root must be a path")
    if not isinstance(filename, str) or not isinstance(payload, bytes):
        raise TypeError("filename must be a string and payload must be bytes")
    if not payload:
        raise StartRejected(rejected)
    base = Path(filename).name
    if base != filename or not _plain_name(base) or Path(base).suffix.lower() not in suffixes:
        raise StartRejected(rejected)
    try:
        root.mkdir(parents=True, exist_ok=True)
        folder = root.resolve()
        chosen = _unique_name(folder, base, suffixes)
        destination = (folder / chosen).resolve()
        if destination.parent != folder:
            raise StartRejected(rejected)
        partial = destination.with_name(destination.name + ".partial")
        partial.write_bytes(payload)
        partial.replace(destination)
    except OSError as exc:
        raise StartRejected(rejected) from exc
    return {"id": chosen, "name": chosen, "bytes": len(payload)}


def _plain_name(value: str) -> bool:
    if not value or "/" in value or "\\" in value or value.startswith("~"):
        return False
    return Path(value).name == value and value not in {".", ".."}


def _structure_file(root: Path, name: str) -> Path | None:
    if Path(name).suffix.lower() not in _TARGET_SUFFIXES:
        return None
    return _file_inside(root, name)


def _file_inside(root: Path, name: str) -> Path | None:
    if not _plain_name(name) or not root.is_dir():
        return None
    path = root / name
    if path.is_symlink() or not path.is_file():
        return None
    try:
        folder = root.resolve()
        resolved = path.resolve()
    except OSError:
        return None
    if resolved.parent != folder:
        return None
    return resolved


def _unique_name(folder: Path, name: str, suffixes: set[str]) -> str:
    if not (folder / name).exists():
        return name
    stem = Path(name).stem
    suffix = Path(name).suffix
    for number in range(2, 1000):
        candidate = f"{stem}-{number}{suffix}"
        if Path(candidate).suffix.lower() in suffixes and _plain_name(candidate) and not (folder / candidate).exists():
            return candidate
    raise StartRejected("A file with that name already exists")


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
