"""Weights the Doctor can see, and the one-shot sync that fetches them.

A Run never calls this module. Sync is only available as a Doctor fix.
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

# Same URLs Boltz-2 uses in download_boltz2. Synced here so a Run does not.
BOLTZ2_CONF_URLS = (
    "https://model-gateway.boltz.bio/boltz2_conf.ckpt",
    "https://huggingface.co/boltz-community/boltz-2/resolve/main/boltz2_conf.ckpt",
)
BOLTZ2_AFFINITY_URLS = (
    "https://model-gateway.boltz.bio/boltz2_aff.ckpt",
    "https://huggingface.co/boltz-community/boltz-2/resolve/main/boltz2_aff.ckpt",
)
BOLTZ2_CCD_URL = "https://huggingface.co/boltz-community/boltz-2/resolve/main/mols.tar"
BOLTZ2_CCD_ARCHIVE_MIN_BYTES = 500_000_000

POSE_GDRIVE_ID = "1xGC193o4DtSPzWFjmRIlPjmn7bLfMaCd"
FABIND_REPO = "KyGao/FABind_plus_model"
FLASHBIND_REPO = "clorf6/FlashBind"
ESM3_REPO = "EvolutionaryScale/esm3-sm-open-v1"
ESM3_MEMBERS = (
    "snapshots/local/data/weights/esm3_sm_open_v1.pth",
    "snapshots/local/data/weights/esm3_structure_encoder_v0.pth",
    "snapshots/local/data/weights/esm3_structure_decoder_v0.pth",
    "snapshots/local/data/weights/esm3_function_decoder_v0.pth",
)
ESM3_SNAPSHOT_FILES = tuple(path.split("snapshots/local/", 1)[1] for path in ESM3_MEMBERS)


class WeightRoots(Protocol):
    repo: Path
    boltz_cache: Path
    hf_cache: Path


@dataclass(frozen=True)
class AssetSpec:
    id: str
    dest: Path
    min_bytes: int
    directory: bool = False
    members: tuple[str, ...] = ()
    kind: str = "file"
    urls: tuple[str, ...] = ()
    repo_id: str = ""
    filename: str = ""


Fetcher = Callable[[AssetSpec], None]


def required_assets(workstation: WeightRoots) -> tuple[AssetSpec, ...]:
    if not isinstance(workstation.repo, Path):
        raise TypeError("repo must be a path")
    if not isinstance(workstation.boltz_cache, Path):
        raise TypeError("boltz_cache must be a path")
    if not isinstance(workstation.hf_cache, Path):
        raise TypeError("hf_cache must be a path")

    cgflow = workstation.repo / "cgflow"
    fabind = cgflow / "src" / "FlashBind" / "FABind_plus" / "ckpt"
    flashbind = cgflow / "src" / "FlashBind" / "checkpoints"
    boltz = workstation.boltz_cache
    return (
        AssetSpec(
            id="pose-model",
            dest=cgflow / "weights" / "cgflow_crossdock.ckpt",
            min_bytes=100_000_000,
            kind="gdown",
            repo_id=POSE_GDRIVE_ID,
        ),
        AssetSpec(
            id="fabind-checkpoint",
            dest=fabind / "fabind_plus_best_ckpt.bin",
            min_bytes=50_000_000,
            kind="hf",
            repo_id=FABIND_REPO,
            filename="fabind_plus_best_ckpt.bin",
        ),
        AssetSpec(
            id="fabind-confidence",
            dest=fabind / "confidence_model.bin",
            min_bytes=50_000_000,
            kind="hf",
            repo_id=FABIND_REPO,
            filename="confidence_model.bin",
        ),
        AssetSpec(
            id="flashbind-binary-1",
            dest=flashbind / "binary_1.ckpt",
            min_bytes=10_000_000,
            kind="hf",
            repo_id=FLASHBIND_REPO,
            filename="binary_1.ckpt",
        ),
        AssetSpec(
            id="flashbind-binary-2",
            dest=flashbind / "binary_2.ckpt",
            min_bytes=10_000_000,
            kind="hf",
            repo_id=FLASHBIND_REPO,
            filename="binary_2.ckpt",
        ),
        AssetSpec(
            id="flashbind-value-1",
            dest=flashbind / "value_1.ckpt",
            min_bytes=10_000_000,
            kind="hf",
            repo_id=FLASHBIND_REPO,
            filename="value_1.ckpt",
        ),
        AssetSpec(
            id="flashbind-value-2",
            dest=flashbind / "value_2.ckpt",
            min_bytes=10_000_000,
            kind="hf",
            repo_id=FLASHBIND_REPO,
            filename="value_2.ckpt",
        ),
        AssetSpec(
            id="boltz2-structure",
            dest=boltz / "boltz2_conf.ckpt",
            min_bytes=500_000_000,
            kind="url",
            urls=BOLTZ2_CONF_URLS,
        ),
        AssetSpec(
            id="boltz2-affinity",
            dest=boltz / "boltz2_aff.ckpt",
            min_bytes=500_000_000,
            kind="url",
            urls=BOLTZ2_AFFINITY_URLS,
        ),
        AssetSpec(
            id="boltz2-ccd-archive",
            dest=boltz / "mols.tar",
            min_bytes=BOLTZ2_CCD_ARCHIVE_MIN_BYTES,
            kind="url",
            urls=(BOLTZ2_CCD_URL,),
        ),
        AssetSpec(
            id="boltz2-ccd",
            dest=boltz / "mols",
            min_bytes=1,
            directory=True,
            kind="extract",
        ),
        AssetSpec(
            id="esm3",
            dest=workstation.hf_cache / "models--EvolutionaryScale--esm3-sm-open-v1",
            min_bytes=10_000_000,
            directory=True,
            members=ESM3_MEMBERS,
            kind="snapshot",
            repo_id=ESM3_REPO,
        ),
    )


def is_lfs_pointer(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size > 512:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return text.startswith("version https://git-lfs.github.com/spec/v1")


def _file_ok(path: Path, min_bytes: int) -> bool:
    if min_bytes < 1:
        raise ValueError("min_bytes must be positive")
    if not path.is_file() or is_lfs_pointer(path):
        return False
    return path.stat().st_size >= min_bytes


def _esm3_present(root: Path, min_bytes: int) -> bool:
    snapshots = root / "snapshots"
    if not snapshots.is_dir():
        return False
    for snapshot in snapshots.iterdir():
        if not snapshot.is_dir():
            continue
        if all(_file_ok(snapshot / relative, min_bytes) for relative in ESM3_SNAPSHOT_FILES):
            return True
    return False


def asset_present(spec: AssetSpec) -> bool:
    if not isinstance(spec, AssetSpec):
        raise TypeError("spec must be an AssetSpec")
    if spec.directory:
        if spec.id == "esm3":
            return _esm3_present(spec.dest, spec.min_bytes)
        if spec.members:
            return all(_file_ok(spec.dest / member, spec.min_bytes) for member in spec.members)
        if spec.kind == "extract":
            return _ccd_extract_present(spec)
        return False
    return _file_ok(spec.dest, spec.min_bytes)


def missing_assets(workstation: WeightRoots) -> tuple[AssetSpec, ...]:
    return tuple(spec for spec in required_assets(workstation) if not asset_present(spec))


def weight_label(asset_id: str) -> str:
    """Glossary name for a weight. Asset ids stay internal."""
    if not isinstance(asset_id, str) or not asset_id:
        raise ValueError("asset_id must be a non-empty string")
    if asset_id == "pose-model":
        return "Pose model"
    if asset_id.startswith("fabind"):
        return "FABind+"
    if asset_id.startswith("flashbind"):
        return "FlashBind"
    if asset_id.startswith("boltz2"):
        return "Boltz-2"
    if asset_id == "esm3":
        return "ESM3"
    return asset_id


def sync_assets(workstation: WeightRoots, *, fetch: Fetcher | None = None) -> tuple[str, ...]:
    """Download weights that are not already on disk. Not called by a Run."""
    fetcher = fetch if fetch is not None else default_fetch
    if not callable(fetcher):
        raise TypeError("fetch must be callable")
    synced: list[str] = []
    for spec in missing_assets(workstation):
        fetcher(spec)
        if not asset_present(spec):
            raise RuntimeError(
                f"Asset sync did not produce {weight_label(spec.id)} at {spec.dest}"
            )
        synced.append(spec.id)
    return tuple(synced)


def default_fetch(spec: AssetSpec) -> None:
    if not isinstance(spec, AssetSpec):
        raise TypeError("spec must be an AssetSpec")
    if spec.kind == "url":
        _fetch_urls(spec)
    elif spec.kind == "hf":
        _fetch_hf(spec)
    elif spec.kind == "gdown":
        _fetch_gdown(spec)
    elif spec.kind == "extract":
        _extract_ccd(spec)
    elif spec.kind == "snapshot":
        _fetch_snapshot(spec)
    else:
        raise ValueError(f"Unknown asset kind {spec.kind!r} for {weight_label(spec.id)}")


def _fetch_urls(spec: AssetSpec) -> None:
    if not spec.urls:
        raise ValueError(f"{weight_label(spec.id)} has no download URL")
    spec.dest.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in spec.urls:
        try:
            urllib.request.urlretrieve(url, spec.dest)  # noqa: S310
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            errors.append(f"{url}: {exc}")
            _discard_download(spec.dest)
            continue
        if _file_ok(spec.dest, spec.min_bytes):
            return
        errors.append(f"{url}: downloaded file is not a weight")
        _discard_download(spec.dest)
    raise RuntimeError(f"Failed to download {weight_label(spec.id)}: {'; '.join(errors)}")


def _discard_download(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()


def _fetch_hf(spec: AssetSpec) -> None:
    if not spec.repo_id or not spec.filename:
        raise ValueError(f"{weight_label(spec.id)} is missing a Hugging Face repo or filename")
    url = f"https://huggingface.co/{spec.repo_id}/resolve/main/{spec.filename}"
    _fetch_urls(AssetSpec(id=spec.id, dest=spec.dest, min_bytes=spec.min_bytes, kind="url", urls=(url,)))


def _fetch_gdown(spec: AssetSpec) -> None:
    if not spec.repo_id:
        raise ValueError(f"{weight_label(spec.id)} is missing a Google Drive id")
    gdown = shutil.which("gdown")
    if gdown is None:
        raise RuntimeError(
            "Syncing the Pose model needs gdown on PATH. "
            f"The Drive file id is {spec.repo_id}."
        )
    spec.dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([gdown, "--id", spec.repo_id, "-O", str(spec.dest)], check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Failed to download {weight_label(spec.id)} at {spec.dest}"
        ) from exc


def _extract_ccd(spec: AssetSpec) -> None:
    archive = spec.dest.parent / "mols.tar"
    label = weight_label(spec.id)
    if not archive.is_file():
        raise RuntimeError(f"Failed to download {label}: CCD archive is missing at {archive}")
    destination = spec.dest.parent
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as handle:
        if hasattr(tarfile, "data_filter"):
            try:
                handle.extractall(destination, filter="data")
            except (tarfile.TarError, OSError, ValueError) as exc:
                raise RuntimeError(f"Failed to download {label} at {destination}") from exc
            return
        _extract_archive_checked(handle, destination, label)


def _extract_archive_checked(handle: tarfile.TarFile, destination: Path, label: str) -> None:
    """Refuse links and paths that leave destination, then extract each member."""
    root = destination.resolve()
    members = handle.getmembers()
    for member in members:
        if member.issym() or member.islnk():
            raise RuntimeError(f"Failed to download {label}: archive contains a link")
        if not _member_inside(root, member.name):
            raise RuntimeError(
                f"Failed to download {label}: archive member leaves the destination"
            )
    for member in members:
        handle.extract(member, destination)


def _ccd_extract_present(spec: AssetSpec) -> bool:
    """True for the expected CCD extract.

    A leftover pickle is not enough when ``mols.tar`` is a real weight. The
    archive's file members have to be on disk. Without a readable archive, a
    directory of pickles is still the cache.
    """
    archive = spec.dest.parent / "mols.tar"
    members = (
        _tar_file_members(archive)
        if _file_ok(archive, BOLTZ2_CCD_ARCHIVE_MIN_BYTES)
        else None
    )
    if members:
        root = spec.dest.parent.resolve()
        return all(_extracted_member(root, member) for member in members)
    if not spec.dest.is_dir():
        return False
    return any(
        path.is_file() and path.stat().st_size >= spec.min_bytes
        for path in spec.dest.glob("*.pkl")
    )


def _tar_file_members(archive: Path) -> list[tarfile.TarInfo] | None:
    try:
        with tarfile.open(archive) as handle:
            return [
                member
                for member in handle.getmembers()
                if member.isfile() and not member.issym() and not member.islnk()
            ]
    except (tarfile.TarError, OSError):
        return None


def _extracted_member(root: Path, member: tarfile.TarInfo) -> bool:
    if member.size < 1 or not _member_inside(root, member.name):
        return False
    path = root / member.name
    return path.is_file() and path.stat().st_size == member.size


def _member_inside(root: Path, name: str) -> bool:
    if not name or Path(name).is_absolute():
        return False
    try:
        (root / name).resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _fetch_snapshot(spec: AssetSpec) -> None:
    if not spec.repo_id:
        raise ValueError(f"{weight_label(spec.id)} is missing a Hugging Face repo")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "Syncing ESM3 needs huggingface_hub and a Hugging Face token "
            "(HF_TOKEN) readable by the Doctor."
        ) from exc
    snapshot_download(repo_id=spec.repo_id, cache_dir=str(spec.dest.parent))
