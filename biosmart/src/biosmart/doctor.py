"""Doctor: whether this workstation can Start a Run."""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from biosmart.assets import Fetcher, missing_assets, sync_assets

VRAM_FLOOR_MIB = 24 * 1024
ENV_PROBES = {
    "server": "import fastapi",
    "default": "import torch, boltz",
    "fabind": "import torch",
    "flashaffinity": "import torch, torch_scatter",
}
IMPORT_TIMEOUT_S = 180


@dataclass(frozen=True)
class GpuSnapshot:
    name: str
    memory_mib: int
    utilization_pct: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("GPU name must be a non-empty string")
        if not isinstance(self.memory_mib, int) or isinstance(self.memory_mib, bool):
            raise TypeError("memory_mib must be an int")
        if self.memory_mib < 0:
            raise ValueError("memory_mib must be >= 0")
        if not isinstance(self.utilization_pct, int) or isinstance(self.utilization_pct, bool):
            raise TypeError("utilization_pct must be an int")
        if self.utilization_pct < 0 or self.utilization_pct > 100:
            raise ValueError("utilization_pct must be between 0 and 100")


@dataclass(frozen=True)
class Workstation:
    repo: Path
    libraries_dir: Path
    boltz_cache: Path
    hf_cache: Path
    interpreters: dict[str, Path]
    # None queries nvidia-smi. An empty tuple means the probe found no GPU.
    gpu: tuple[GpuSnapshot, ...] | None = None

    def __post_init__(self) -> None:
        for field in ("repo", "libraries_dir", "boltz_cache", "hf_cache"):
            if not isinstance(getattr(self, field), Path):
                raise TypeError(f"{field} must be a path")
        if not isinstance(self.interpreters, dict):
            raise TypeError("interpreters must be a dict of environment name to interpreter path")
        for name, path in self.interpreters.items():
            if not isinstance(name, str) or not name:
                raise ValueError("environment name must be a non-empty string")
            if not isinstance(path, Path):
                raise TypeError(f"interpreter for {name} must be a path")
        if self.gpu is not None:
            if not isinstance(self.gpu, tuple):
                raise TypeError("gpu must be a tuple of GpuSnapshot or None")
            for snapshot in self.gpu:
                if not isinstance(snapshot, GpuSnapshot):
                    raise TypeError("gpu entries must be GpuSnapshot values")


@dataclass(frozen=True)
class Check:
    id: str
    name: str
    ok: bool
    blocking: bool
    summary: str
    detail: str
    fix: str | None = None


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[Check, ...]

    @property
    def ready(self) -> bool:
        return all(check.ok for check in self.checks if check.blocking)

    def check(self, check_id: str) -> Check:
        if not isinstance(check_id, str) or not check_id:
            raise ValueError("check_id must be a non-empty string")
        for item in self.checks:
            if item.id == check_id:
                return item
        raise KeyError(check_id)


def repo_root() -> Path:
    # biosmart/src/biosmart/doctor.py -> repository root
    return Path(__file__).resolve().parents[3]


def discover() -> Workstation:
    repo = repo_root()
    libraries = Path(
        os.environ.get("BIOSMART_LIBRARIES", Path.home() / "BioSmart" / "libraries")
    ).expanduser()
    boltz = Path(os.environ.get("BOLTZ_CACHE", Path.home() / ".boltz")).expanduser()
    hf_value = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    hf_cache = Path(hf_value).expanduser() if hf_value else Path.home() / ".cache" / "huggingface" / "hub"
    interpreters = {
        name: repo / ".pixi" / "envs" / name / "bin" / "python" for name in ENV_PROBES
    }
    return Workstation(
        repo=repo,
        libraries_dir=libraries,
        boltz_cache=boltz,
        hf_cache=hf_cache,
        interpreters=interpreters,
        gpu=None,
    )


def examine(workstation: Workstation | None = None) -> DoctorReport:
    ws = discover() if workstation is None else workstation
    if not isinstance(ws, Workstation):
        raise TypeError("workstation must be a Workstation")
    gpus = query_gpus() if ws.gpu is None else ws.gpu
    checks = (
        _gpu_check(gpus),
        _vram_check(gpus),
        _environment_check(ws),
        _weights_check(ws),
        _library_check(ws),
    )
    return DoctorReport(checks)


def apply_fix(
    check_id: str,
    workstation: Workstation | None = None,
    *,
    fetch: Fetcher | None = None,
) -> DoctorReport:
    """Run the automated fix for a Doctor check. Weights sync is the only fix."""
    if check_id != "weights":
        raise ValueError(f"Doctor check {check_id!r} has no automated fix")
    ws = discover() if workstation is None else workstation
    if not isinstance(ws, Workstation):
        raise TypeError("workstation must be a Workstation")
    sync_assets(ws, fetch=fetch)
    return examine(ws)


def render(report: DoctorReport) -> str:
    if not isinstance(report, DoctorReport):
        raise TypeError("report must be a DoctorReport")
    lines = ["Doctor"]
    for check in report.checks:
        state = "pass" if check.ok else "fail"
        lines.append(f"  {check.id:<14} {state:<4}  {check.summary}")
        if not check.ok:
            for line in check.detail.splitlines():
                lines.append(f"    {line}")
            if check.fix:
                lines.append(f"    fix: biosmart doctor fix {check.fix}")
    if report.ready:
        lines.append("Workstation can Start a Run.")
    else:
        lines.append("Start refused.")
    return "\n".join(lines)


def report_payload(report: DoctorReport) -> dict[str, object]:
    if not isinstance(report, DoctorReport):
        raise TypeError("report must be a DoctorReport")
    return {
        "ready": report.ready,
        "checks": [asdict(check) for check in report.checks],
    }


def query_gpus() -> tuple[GpuSnapshot, ...]:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ()
    if proc.returncode != 0:
        return ()
    gpus: list[GpuSnapshot] = []
    for line in proc.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            gpus.append(GpuSnapshot(parts[0], int(parts[1]), int(parts[2])))
        except (TypeError, ValueError):
            continue
    return tuple(gpus)


def _gpu_check(gpus: tuple[GpuSnapshot, ...]) -> Check:
    if not gpus:
        return Check(
            id="gpu",
            name="GPU",
            ok=False,
            blocking=True,
            summary="No GPU reported",
            detail="nvidia-smi did not report a GPU.",
        )
    names = ", ".join(gpu.name for gpu in gpus)
    detail = "\n".join(
        f"{gpu.name}: {gpu.memory_mib} MiB, utilization {gpu.utilization_pct}%"
        for gpu in gpus
    )
    return Check(
        id="gpu",
        name="GPU",
        ok=True,
        blocking=True,
        summary=names,
        detail=detail,
    )


def _vram_check(gpus: tuple[GpuSnapshot, ...]) -> Check:
    if not gpus:
        return Check(
            id="vram",
            name="VRAM",
            ok=False,
            blocking=True,
            summary="No GPU to measure",
            detail=f"VRAM floor is {VRAM_FLOOR_MIB} MiB.",
        )
    best = max(gpus, key=lambda gpu: gpu.memory_mib)
    ok = best.memory_mib >= VRAM_FLOOR_MIB
    summary = f"{best.memory_mib} MiB (floor {VRAM_FLOOR_MIB} MiB)"
    detail = summary if ok else f"{best.name} has {summary}"
    return Check(
        id="vram",
        name="VRAM",
        ok=ok,
        blocking=True,
        summary=summary,
        detail=detail,
    )


def _environment_check(workstation: Workstation) -> Check:
    lines: list[str] = []
    failed: list[str] = []
    for name, statement in ENV_PROBES.items():
        interpreter = workstation.interpreters.get(name)
        if interpreter is None:
            failed.append(name)
            lines.append(f"{name}: interpreter is not configured")
            continue
        ok, message = _probe_import(interpreter, statement)
        lines.append(f"{name}: {message}")
        if not ok:
            failed.append(name)
    if failed:
        summary = f"{', '.join(failed)} not ready"
    else:
        summary = f"{len(ENV_PROBES)} environments import"
    return Check(
        id="environments",
        name="Environments",
        ok=not failed,
        blocking=True,
        summary=summary,
        detail="\n".join(lines),
    )


def _probe_import(interpreter: Path, statement: str) -> tuple[bool, str]:
    if not interpreter.is_file():
        return False, f"pixi environment is not installed ({interpreter})"
    try:
        proc = subprocess.run(
            [str(interpreter), "-c", statement],
            capture_output=True,
            text=True,
            timeout=IMPORT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"import timed out after {IMPORT_TIMEOUT_S}s"
    except OSError as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, "import ok"
    err = (proc.stderr or proc.stdout or "").strip()
    last = err.splitlines()[-1] if err else f"exit {proc.returncode}"
    return False, last


def _weights_check(workstation: Workstation) -> Check:
    missing = missing_assets(workstation)
    if not missing:
        return Check(
            id="weights",
            name="Weights",
            ok=True,
            blocking=True,
            summary="Weights are present",
            detail="Pose model, FABind+, FlashBind, Boltz-2, and ESM3 are on disk.",
        )
    detail = "\n".join(f"{_weight_label(spec.id)}: {spec.dest}" for spec in missing)
    labels: list[str] = []
    for spec in missing:
        label = _weight_label(spec.id)
        if label not in labels:
            labels.append(label)
    return Check(
        id="weights",
        name="Weights",
        ok=False,
        blocking=True,
        summary="Missing " + ", ".join(labels),
        detail=detail,
        fix="weights",
    )


def _weight_label(asset_id: str) -> str:
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


def _library_check(workstation: Workstation) -> Check:
    libraries = find_libraries(workstation.libraries_dir)
    if not libraries:
        return Check(
            id="library",
            name="Building-block library",
            ok=False,
            blocking=True,
            summary="No Building-block library",
            detail=f"No Building-block library in {workstation.libraries_dir}",
        )
    names = ", ".join(path.name for path in libraries)
    return Check(
        id="library",
        name="Building-block library",
        ok=True,
        blocking=True,
        summary=f"{len(libraries)} Building-block library",
        detail=names,
    )


def find_libraries(root: Path) -> tuple[Path, ...]:
    if not isinstance(root, Path):
        raise TypeError("root must be a path")
    if not root.is_dir():
        return ()
    found: list[Path] = []
    candidates = [root, *sorted(path for path in root.iterdir() if path.is_dir())]
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        if _is_library(path):
            seen.add(resolved)
            found.append(path)
    return tuple(found)


def _is_library(path: Path) -> bool:
    workflow = (path / "workflow.yaml").is_file() or (path / "workflow.yml").is_file()
    blocks = (path / "blocks").is_dir()
    stamped = (path / "library.json").is_file()
    return (workflow and blocks) or stamped
