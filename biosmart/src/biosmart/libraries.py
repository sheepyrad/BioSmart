"""Build a Building-block library from an Enamine Stock file."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

STOCK_SOURCE = "Enamine Stock"
STALE_AFTER_DAYS = 30


class LibraryBuildError(Exception):
    """The Stock file could not be turned into a Building-block library."""


@dataclass(frozen=True)
class Library:
    id: str
    source: str
    created_at: datetime
    druglike: bool
    path: Path
    supplier_file: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "druglike": self.druglike,
            "path": str(self.path),
            "supplier_file": self.supplier_file,
        }


def default_libraries_root() -> Path:
    override = os.environ.get("BIOSMART_LIBRARIES_ROOT")
    if override:
        return Path(override)
    return Path.home() / "BioSmart" / "libraries"


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        script = parent / "cgflow" / "data" / "scripts" / "a_stock_to_smi.py"
        if script.is_file():
            return parent
    raise LibraryBuildError("CGFlow Stock extraction script was not found")


def build_stock_library(
    source_file: Path,
    libraries_root: Path,
    *,
    druglike: bool = False,
    cpu: int | None = None,
) -> Library:
    """Build a Building-block library from an Enamine Stock zip or SDF.

    The drug-like filter stays off unless ``druglike`` is set. Each build
    writes a new directory beside any libraries already there.
    """
    if not source_file.is_file():
        raise LibraryBuildError(f"Enamine Stock file not found: {source_file}")

    libraries_root.mkdir(parents=True, exist_ok=True)
    workers = cpu if cpu is not None else len(os.sched_getaffinity(0))
    scripts = find_repo_root() / "cgflow" / "data" / "scripts"
    protocol = find_repo_root() / "cgflow" / "data" / "template" / "real"
    created_at = datetime.now(timezone.utc)
    library_id = "enamine-stock-" + created_at.strftime("%Y%m%dT%H%M%S%fZ")
    if druglike:
        library_id += "-druglike"
    library_dir = libraries_root / library_id

    with tempfile.TemporaryDirectory(dir=libraries_root) as work_name:
        work = Path(work_name)
        sdf = _materialize_sdf(source_file, work)
        raw_smi = work / "stock.smi"
        _run(
            [
                sys.executable,
                str(scripts / "a_stock_to_smi.py"),
                "-b",
                str(sdf),
                "-o",
                str(raw_smi),
                "--cpu",
                str(workers),
            ]
        )
        supplier = _with_header(raw_smi, work / "supplier.smi")
        if druglike:
            filtered = work / "druglike.smi"
            _run(
                [
                    sys.executable,
                    str(scripts / "b_druglike_filter.py"),
                    "-b",
                    str(supplier),
                    "-o",
                    str(filtered),
                ]
            )
            supplier = _with_header(filtered, work / "supplier-druglike.smi")

        try:
            _run(
                [
                    sys.executable,
                    str(scripts / "c_create_env.py"),
                    "-b",
                    str(supplier),
                    "-p",
                    str(protocol),
                    "-o",
                    str(library_dir),
                    "--cpu",
                    str(workers),
                ]
            )
        except LibraryBuildError:
            if library_dir.exists():
                shutil.rmtree(library_dir)
            raise
        shutil.copyfile(supplier, library_dir / "supplier.smi")

    library = Library(
        id=library_id,
        source=STOCK_SOURCE,
        created_at=created_at,
        druglike=druglike,
        path=library_dir,
        supplier_file=source_file.name,
    )
    (library_dir / "library.json").write_text(json.dumps(library.to_dict(), indent=2) + "\n")
    return library


def list_libraries(libraries_root: Path) -> tuple[Library, ...]:
    if not libraries_root.is_dir():
        return ()
    found: list[Library] = []
    for meta_path in sorted(libraries_root.glob("*/library.json")):
        found.append(_read_library(meta_path))
    found.sort(key=lambda library: (library.created_at, library.id))
    return tuple(found)


def default_library(libraries_root: Path) -> Library | None:
    libraries = list_libraries(libraries_root)
    if not libraries:
        return None
    return libraries[-1]


def describe_libraries(
    libraries_root: Path,
    *,
    now: datetime | None = None,
    stale_after_days: int = STALE_AFTER_DAYS,
) -> dict[str, object]:
    """Libraries for the host page: newest first, default marked, staleness as a reminder.

    The reminder does not refuse Start. A missing root is an empty list.
    """
    if not isinstance(libraries_root, Path):
        raise TypeError("libraries_root must be a path")
    if isinstance(stale_after_days, bool) or not isinstance(stale_after_days, int):
        raise TypeError("stale_after_days must be an int")
    if stale_after_days < 1:
        raise ValueError("stale_after_days must be positive")
    libraries = list_libraries(libraries_root)
    chosen = libraries[-1] if libraries else None
    items: list[dict[str, object]] = []
    for library in reversed(libraries):
        _recorded, reminder = recorded_library(
            library.id,
            libraries_root,
            now=now,
            stale_after_days=stale_after_days,
        )
        items.append(
            {
                "id": library.id,
                "source": library.source,
                "created_at": library.created_at.isoformat(),
                "druglike": library.druglike,
                "supplier_file": library.supplier_file,
                "default": chosen is not None and library.id == chosen.id,
                "reminder": reminder,
            }
        )
    return {
        "default_id": None if chosen is None else chosen.id,
        "stale_after_days": stale_after_days,
        "libraries": items,
    }


def recorded_library(
    library_id: str,
    libraries_root: Path | None,
    *,
    now: datetime | None = None,
    stale_after_days: int = STALE_AFTER_DAYS,
) -> tuple[dict[str, object], str | None]:
    """Metadata a Run records for the library it used, plus a staleness reminder.

    A missing library is not a reminder. The Run still starts; presence is a
    separate check.
    """
    if libraries_root is None:
        return {"id": library_id}, None
    chosen = next((library for library in list_libraries(libraries_root) if library.id == library_id), None)
    if chosen is None:
        return {"id": library_id}, None

    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    reminder: str | None = None
    if moment - chosen.created_at > timedelta(days=stale_after_days):
        reminder = f"Building-block library {chosen.id} is older than {stale_after_days} days."
    return chosen.to_dict(), reminder


def _read_library(meta_path: Path) -> Library:
    payload = json.loads(meta_path.read_text())
    created_at = datetime.fromisoformat(str(payload["created_at"]))
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return Library(
        id=str(payload["id"]),
        source=str(payload["source"]),
        created_at=created_at,
        druglike=bool(payload["druglike"]),
        path=Path(str(payload["path"])),
        supplier_file=str(payload["supplier_file"]),
    )


def _materialize_sdf(source_file: Path, work: Path) -> Path:
    if source_file.suffix.lower() == ".sdf":
        return source_file
    if source_file.suffix.lower() != ".zip":
        raise LibraryBuildError(
            f"Enamine Stock input must be a .zip or .sdf, got {source_file.name}"
        )
    with zipfile.ZipFile(source_file) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".sdf") and not name.endswith("/")
        ]
        if len(names) != 1:
            raise LibraryBuildError(
                f"Enamine Stock zip must contain one SDF, found {len(names)} in {source_file.name}"
            )
        dest = work / Path(names[0]).name
        with archive.open(names[0]) as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out, length=1024 * 1024)
    return dest


def _with_header(smi_path: Path, dest: Path) -> Path:
    # c_create_env.py and b_druglike_filter.py both skip the first line.
    body = smi_path.read_text()
    if body.startswith("smiles\t"):
        dest.write_text(body)
    else:
        dest.write_text("smiles\tid\n" + body)
    return dest


def _run(args: list[str]) -> None:
    completed = subprocess.run(args, stdout=sys.stderr, stderr=sys.stderr)
    if completed.returncode != 0:
        raise LibraryBuildError(f"command failed ({completed.returncode}): {args[0]} {Path(args[1]).name}")
