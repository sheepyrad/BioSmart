"""Doctor readiness.

The Doctor is the seam. A workstation can Start a Run only when the blocking
checks pass: GPU, VRAM, environments, weights, and a Building-block library.
Asset sync is a Doctor fix. A Run does not fetch weights.
"""

from __future__ import annotations

import os
import shutil
import urllib.request
from dataclasses import replace
from pathlib import Path

import pytest

from biosmart.assets import required_assets
from biosmart.doctor import GpuSnapshot, Workstation, apply_fix, examine
from biosmart.start import StartRefused, execute_guarded, open_run, start_run

VRAM_FLOOR_MIB = 24 * 1024
ENV_NAMES = ("server", "default", "fabind", "flashaffinity")


def _write_interpreter(path: Path, *, ok: bool, message: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if ok:
        path.write_text("#!/bin/sh\nexit 0\n")
    else:
        path.write_text(f"#!/bin/sh\necho {message!r} >&2\nexit 1\n")
    path.chmod(0o755)


def _materialise(spec) -> None:
    if spec.directory:
        spec.dest.mkdir(parents=True, exist_ok=True)
        names = spec.members or ("marker.pkl",)
        for name in names:
            path = spec.dest / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                handle.truncate(spec.min_bytes)
        return
    spec.dest.parent.mkdir(parents=True, exist_ok=True)
    with spec.dest.open("wb") as handle:
        handle.truncate(spec.min_bytes)


def _ready(tmp_path: Path) -> Workstation:
    repo = tmp_path / "repo"
    repo.mkdir()
    interpreters = {
        name: tmp_path / "envs" / name / "python" for name in ENV_NAMES
    }
    for path in interpreters.values():
        _write_interpreter(path, ok=True)
    library = tmp_path / "libraries" / "enamine-stock"
    (library / "blocks").mkdir(parents=True)
    (library / "workflow.yaml").write_text("version: 1\n")
    workstation = Workstation(
        repo=repo,
        libraries_dir=tmp_path / "libraries",
        boltz_cache=tmp_path / "boltz",
        hf_cache=tmp_path / "hf",
        interpreters=interpreters,
        gpu=(GpuSnapshot("NVIDIA GeForce RTX 3090", VRAM_FLOOR_MIB, 0),),
    )
    for spec in required_assets(workstation):
        _materialise(spec)
    return workstation


def test_doctor_reports_gpu_vram_environments_weights_and_library(tmp_path: Path) -> None:
    report = examine(_ready(tmp_path))

    assert [check.id for check in report.checks] == [
        "gpu",
        "vram",
        "environments",
        "weights",
        "library",
    ]
    assert report.ready
    assert report.check("gpu").summary.startswith("NVIDIA GeForce RTX 3090")
    assert report.check("vram").ok
    assert "24576" in report.check("vram").summary
    assert report.check("library").ok
    assert "enamine-stock" in report.check("library").detail


def test_missing_building_block_library_refuses_start(tmp_path: Path) -> None:
    workstation = _ready(tmp_path)
    shutil.rmtree(workstation.libraries_dir)
    workstation.libraries_dir.mkdir()

    report = examine(workstation)

    assert report.check("library").ok is False
    assert report.check("library").blocking is True
    with pytest.raises(StartRefused, match="Start refused") as raised:
        start_run(workstation)
    assert "library" in str(raised.value)


def test_vram_below_24gb_refuses_start(tmp_path: Path) -> None:
    workstation = replace(
        _ready(tmp_path),
        gpu=(GpuSnapshot("small-gpu", 8192, 0),),
    )

    report = examine(workstation)

    assert report.check("vram").ok is False
    assert report.check("vram").blocking is True
    with pytest.raises(StartRefused, match="vram"):
        start_run(workstation)


def test_missing_gpu_refuses_start(tmp_path: Path) -> None:
    workstation = replace(_ready(tmp_path), gpu=())

    assert examine(workstation).check("gpu").ok is False
    with pytest.raises(StartRefused, match="gpu"):
        start_run(workstation)


def test_environment_import_failure_is_blocking(tmp_path: Path) -> None:
    workstation = _ready(tmp_path)
    _write_interpreter(
        workstation.interpreters["flashaffinity"],
        ok=False,
        message="OSError: libc.so.6: version GLIBC_2.32 not found (required by torch_scatter)",
    )

    report = examine(workstation)
    environments = report.check("environments")

    assert environments.ok is False
    assert environments.blocking is True
    assert "flashaffinity" in environments.detail
    assert "GLIBC_2.32" in environments.detail
    assert "server" in environments.detail
    with pytest.raises(StartRefused, match="environments"):
        start_run(workstation)


def test_missing_weights_are_reported_and_block_start(tmp_path: Path) -> None:
    workstation = _ready(tmp_path)
    for asset_id in ("pose-model", "fabind-checkpoint", "fabind-confidence", "boltz2-structure"):
        asset = next(spec for spec in required_assets(workstation) if spec.id == asset_id)
        asset.dest.unlink()

    report = examine(workstation)

    detail = report.check("weights").detail
    assert report.check("weights").ok is False
    assert report.check("weights").blocking is True
    assert "Pose model" in detail
    assert "FABind+" in detail
    assert "Boltz-2" in detail
    assert "fabind-checkpoint" not in detail
    assert "fabind-confidence" not in detail
    assert "boltz2-" not in detail
    assert report.check("weights").fix == "weights"
    with pytest.raises(StartRefused, match="weights"):
        start_run(workstation)


def test_doctor_fix_syncs_weights(tmp_path: Path) -> None:
    workstation = _ready(tmp_path)
    pose = next(spec for spec in required_assets(workstation) if spec.id == "pose-model")
    pose.dest.unlink()
    fetched: list[str] = []

    def fetch(spec) -> None:
        fetched.append(spec.id)
        _materialise(spec)

    report = apply_fix("weights", workstation, fetch=fetch)

    assert fetched == ["pose-model"]
    assert report.check("weights").ok
    assert report.ready


def test_a_run_does_not_fetch_weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workstation = _ready(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        "biosmart.assets.default_fetch",
        lambda *args, **kwargs: calls.append("fetch"),
    )
    monkeypatch.setattr(
        urllib.request,
        "urlretrieve",
        lambda *args, **kwargs: calls.append("url"),
    )

    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    open_run(workstation)

    assert calls == []
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert os.environ["BOLTZ_CACHE"] == str(workstation.boltz_cache)

    pose = next(spec for spec in required_assets(workstation) if spec.id == "pose-model")
    pose.dest.unlink()
    with pytest.raises(StartRefused, match="weights"):
        open_run(workstation)
    assert calls == []


def test_failed_blocking_check_does_not_execute_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BIOSMART_SKIP_DOCTOR", raising=False)
    calls: list[object] = []
    monkeypatch.setattr(
        "biosmart.start.execute_run",
        lambda *args, **kwargs: calls.append(args),
    )
    workstation = _ready(tmp_path)
    shutil.rmtree(workstation.libraries_dir)
    workstation.libraries_dir.mkdir()

    with pytest.raises(StartRefused, match="library"):
        execute_guarded(
            tmp_path / "spec.json",
            tmp_path / "runs",
            tmp_path / "registry.sqlite",
            workstation,
        )
    assert calls == []


def test_passing_checks_start_the_run_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BIOSMART_SKIP_DOCTOR", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    seen: dict[str, str | None] = {}

    def spy(spec_path: Path, runs_root: Path, registry: Path) -> Path:
        seen["hf"] = os.environ.get("HF_HUB_OFFLINE")
        seen["tf"] = os.environ.get("TRANSFORMERS_OFFLINE")
        return tmp_path / "ran"

    monkeypatch.setattr("biosmart.start.execute_run", spy)
    folder = execute_guarded(
        tmp_path / "spec.json",
        tmp_path / "runs",
        tmp_path / "registry.sqlite",
        _ready(tmp_path),
    )
    assert folder == tmp_path / "ran"
    assert seen == {"hf": "1", "tf": "1"}
