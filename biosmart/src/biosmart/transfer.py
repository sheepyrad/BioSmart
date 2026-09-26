"""Export top Candidates, and archive or import a Run folder.

The Run database inside the Run folder is the source of truth. Export reads
that database. Importing a Run folder or one compressed archive of it rebuilds
the Index.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from biosmart.index import RunFolderError, import_run_folder
from biosmart.storage import connect

_FORMATS = frozenset({"sdf", "csv"})
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_SETUID = 0o4000
_SETGID = 0o2000
_COLUMNS = (
    "candidate_id",
    "canonical_smiles",
    "reward",
    "status",
    "iteration",
    "round_no",
    "route",
)


class ExportError(ValueError):
    """Top-N export cannot be written."""


def export_top(run_folder: Path, *, export_format: str, top: int) -> tuple[bytes, str, str]:
    """Return the top Candidates as SDF (route in an SD tag) or CSV.

    The bytes, media type, and download name come from the Run database.
    """
    if not isinstance(run_folder, Path):
        raise TypeError("run_folder must be a Path")
    if export_format not in _FORMATS:
        raise ExportError("format must be sdf or csv")
    if isinstance(top, bool) or not isinstance(top, int) or top < 1:
        raise ExportError("top must be at least 1")
    manifest = _read_manifest(run_folder)
    run_id = str(manifest["run_id"])
    rows = _top_rows(run_folder / "run.sqlite", top)
    filename = f"{run_id}-top-{top}.{export_format}"
    if export_format == "csv":
        return _csv(rows), "text/csv; charset=utf-8", filename
    return _sdf(rows), "chemical/x-mdl-sdfile", filename


def write_run_archive(run_folder: Path, destination: Path) -> Path:
    """Write one ``.tar.zst`` of the Run folder. Provenance and Scorer files are included."""
    if not isinstance(run_folder, Path):
        raise TypeError("run_folder must be a Path")
    if not isinstance(destination, Path):
        raise TypeError("destination must be a Path")
    if not run_folder.is_dir():
        raise RunFolderError("Run folder is missing")
    manifest = _read_manifest(run_folder)
    run_id = str(manifest["run_id"])
    if run_folder.name != run_id:
        raise RunFolderError("Run folder name does not match its manifest")
    database = run_folder / "run.sqlite"
    if not database.is_file():
        raise RunFolderError("Run folder is missing its Run database")
    if not destination.name.endswith(".tar.zst"):
        raise RunFolderError("Archive destination must be a .tar.zst file")
    if destination.exists() and destination.is_dir():
        raise RunFolderError("Archive destination must be a file")
    if _is_inside(run_folder, destination):
        raise RunFolderError("Archive destination must be outside the Run folder")

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial_tar = destination.with_name(f".{destination.name}.tar")
    partial_zst = destination.with_name(f".{destination.name}.partial")
    try:
        _checkpoint(database)
        with tarfile.open(partial_tar, mode="w") as tar:
            tar.add(run_folder, arcname=run_id, filter=_archive_filter)
        _zstd_compress_file(partial_tar, partial_zst)
        partial_zst.replace(destination)
    finally:
        partial_tar.unlink(missing_ok=True)
        if partial_zst.exists():
            partial_zst.unlink(missing_ok=True)
    return destination


def import_run_archive(runs_root: Path, registry: Path, archive: Path) -> dict[str, Any]:
    """Unpack one Run archive into the Runs root and rebuild its Index rows."""
    if not isinstance(runs_root, Path):
        raise TypeError("runs_root must be a Path")
    if not isinstance(registry, Path):
        raise TypeError("registry must be a Path")
    if not isinstance(archive, Path):
        raise TypeError("archive must be a Path")
    if not archive.is_file():
        raise RunFolderError("Archive is missing")
    if not archive.name.endswith(".tar.zst"):
        raise RunFolderError("Archive must be a .tar.zst file")
    runs_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runs_root) as tmp:
        work = Path(tmp)
        extracted = _extract_run_folder(archive, work)
        return import_run_folder(runs_root, registry, extracted)


def _top_rows(database: Path, top: int) -> list[sqlite3.Row]:
    if not database.is_file():
        raise ExportError("Run folder is missing its Run database")
    uri = f"file:{database}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return list(
            connection.execute(
                """
                SELECT id, canonical_smiles, reward, status, iteration, round_no, route_json
                FROM candidates
                WHERE status = 'scored' AND reward IS NOT NULL
                ORDER BY reward DESC, id ASC
                LIMIT ?
                """,
                (top,),
            )
        )
    finally:
        connection.close()


def _csv(rows: list[sqlite3.Row]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "candidate_id": row["id"],
                "canonical_smiles": row["canonical_smiles"],
                "reward": row["reward"],
                "status": row["status"],
                "iteration": row["iteration"],
                "round_no": row["round_no"],
                "route": row["route_json"] or "",
            }
        )
    return buffer.getvalue().encode("utf-8")


def _sdf(rows: list[sqlite3.Row]) -> bytes:
    from rdkit import Chem
    from rdkit.Chem import AllChem

    blocks: list[str] = []
    for row in rows:
        candidate_id = str(row["id"])
        smiles = str(row["canonical_smiles"])
        parsed = Chem.MolFromSmiles(smiles)
        if parsed is None:
            raise ExportError(f"Candidate {candidate_id} cannot be written as SDF")
        AllChem.Compute2DCoords(parsed)
        parsed.SetProp("_Name", candidate_id)
        block = Chem.MolToMolBlock(parsed).rstrip("\n")
        reward = row["reward"]
        tags = (
            ("route", "" if row["route_json"] is None else str(row["route_json"])),
            ("candidate_id", candidate_id),
            ("canonical_smiles", smiles),
            ("reward", "" if reward is None else repr(float(reward))),
        )
        tagged = "\n".join(f"> <{name}>\n{value}\n" for name, value in tags)
        blocks.append(f"{block}\n{tagged}\n$$$$")
    text = "\n".join(blocks)
    if text:
        text += "\n"
    return text.encode("utf-8")


def _read_manifest(run_folder: Path) -> dict[str, Any]:
    path = run_folder / "run.json"
    if not path.is_file():
        raise RunFolderError("Run folder is missing its manifest")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RunFolderError("Run manifest is not an object")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not _valid_run_id(run_id):
        raise RunFolderError("Run manifest is missing its run id")
    if not (run_folder / "run.sqlite").is_file():
        raise RunFolderError("Run folder is missing its Run database")
    return payload


def _checkpoint(database: Path) -> None:
    with connect(database) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _archive_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if info.issym() or info.islnk():
        return None
    if info.name.endswith(".sqlite-wal") or info.name.endswith(".sqlite-shm"):
        return None
    return info


def _is_inside(folder: Path, path: Path) -> bool:
    resolved = path.resolve()
    root = folder.resolve()
    return resolved == root or root in resolved.parents


def _zstd_compress_file(source: Path, dest: Path) -> None:
    try:
        import zstandard
    except ImportError:
        zstandard = None
    if zstandard is not None:
        compressor = zstandard.ZstdCompressor(level=3)
        with source.open("rb") as src, dest.open("wb") as out:
            compressor.copy_stream(src, out)
        return
    completed = subprocess.run(
        ["zstd", "-q", "-f", "-o", str(dest), str(source)],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RunFolderError("Archiving a Run needs zstd")


def _zstd_decompress_to(source: Path, dest: Path) -> None:
    try:
        import zstandard
    except ImportError:
        zstandard = None
    if zstandard is not None:
        decompressor = zstandard.ZstdDecompressor()
        with source.open("rb") as src, dest.open("wb") as out:
            decompressor.copy_stream(src, out)
        return
    completed = subprocess.run(
        ["zstd", "-d", "-q", "-f", "-o", str(dest), str(source)],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RunFolderError("Archive is not a compressed Run folder")


def _valid_run_id(run_id: str) -> bool:
    return len(run_id) == 32 and all(character in "0123456789abcdef" for character in run_id)


def _extract_run_folder(archive: Path, work: Path) -> Path:
    with archive.open("rb") as handle:
        header = handle.read(4)
    if header != _ZSTD_MAGIC:
        raise RunFolderError("Archive is not a compressed Run folder")
    tar_path = work / "run.tar"
    unpacked = work / "unpacked"
    unpacked.mkdir()
    _zstd_decompress_to(archive, tar_path)
    try:
        with tarfile.open(tar_path, mode="r:") as tar:
            members = tar.getmembers()
            if not members:
                raise RunFolderError("Archive must contain one Run folder")
            tops = {
                Path(member.name).parts[0]
                for member in members
                if member.name not in {"", "."}
            }
            if len(tops) != 1:
                raise RunFolderError("Archive must contain one Run folder")
            root_name = next(iter(tops))
            for member in members:
                _reject_unsafe_member(member, unpacked)
            for member in members:
                _extract_member(tar, member, unpacked)
    except tarfile.TarError as exc:
        raise RunFolderError("Archive is not a compressed Run folder") from exc
    extracted = unpacked / root_name
    if not extracted.is_dir():
        raise RunFolderError("Archive must contain one Run folder")
    manifest = _read_manifest(extracted)
    if manifest["run_id"] != root_name:
        raise RunFolderError("Archive Run folder does not match its manifest")
    return extracted


def _reject_unsafe_member(member: tarfile.TarInfo, destination: Path) -> None:
    """Refuse links, special files, and setuid or setgid regular files before any write.

    A directory may carry the setgid bit. Linux copies that bit onto directories
    created under a setgid parent, and the archive records it. Extraction still
    writes the directory as mode ``0o755``.
    """
    _reject_escaping_member(member, destination)
    if not member.isdir() and not member.isreg():
        raise RunFolderError("Archive member is not a Run folder file")
    mode = 0 if member.mode is None else member.mode
    if member.isreg() and mode & (_SETUID | _SETGID):
        raise RunFolderError("Archive member is not a Run folder file")
    if member.isdir() and mode & _SETUID:
        raise RunFolderError("Archive member is not a Run folder file")


def _extract_member(tar: tarfile.TarFile, member: tarfile.TarInfo, destination: Path) -> None:
    """Write one directory or regular file. Archive mode bits are not applied."""
    target = (destination / member.name).resolve()
    root = destination.resolve()
    if target != root and root not in target.parents:
        raise RunFolderError("Archive member escapes the Run folder")
    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
        os.chmod(target, 0o755)
        return
    source = tar.extractfile(member)
    if source is None:
        raise RunFolderError("Archive member is not a Run folder file")
    target.parent.mkdir(parents=True, exist_ok=True)
    with source, target.open("wb") as handle:
        shutil.copyfileobj(source, handle)
    executable = bool((0 if member.mode is None else member.mode) & 0o111)
    os.chmod(target, 0o755 if executable else 0o644)


def _reject_escaping_member(member: tarfile.TarInfo, destination: Path) -> None:
    name = member.name
    if not name or name.startswith("/") or name.startswith("\\"):
        raise RunFolderError("Archive member escapes the Run folder")
    parts = Path(name).parts
    if ".." in parts or parts[0] in {"", ".", ".."}:
        raise RunFolderError("Archive member escapes the Run folder")
    if member.issym() or member.islnk():
        raise RunFolderError("Archive member escapes the Run folder")
    target = (destination / name).resolve()
    root = destination.resolve()
    if target != root and root not in target.parents:
        raise RunFolderError("Archive member escapes the Run folder")


__all__ = ["ExportError", "export_top", "import_run_archive", "write_run_archive"]
