"""Start gate. A failed blocking Doctor check refuses Start.

The process that runs a Run has Hugging Face offline. It does not fetch weights.
``BIOSMART_SKIP_DOCTOR=1`` skips the gate for tests. Production Start leaves it unset.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from biosmart.doctor import DoctorReport, Workstation, discover, examine
from biosmart.engine import execute_run

SKIP_DOCTOR_ENV = "BIOSMART_SKIP_DOCTOR"


class StartRefused(Exception):
    def __init__(self, report: DoctorReport) -> None:
        if not isinstance(report, DoctorReport):
            raise TypeError("report must be a DoctorReport")
        failed = [check.id for check in report.checks if check.blocking and not check.ok]
        super().__init__(
            "Start refused. Blocking Doctor checks failed: " + ", ".join(failed)
        )
        self.report = report


@dataclass(frozen=True)
class RunContext:
    """Offline environment of the process that runs a Run."""

    env: Mapping[str, str]


def start_run(workstation: Workstation | None = None) -> DoctorReport:
    """Refuse Start when a blocking Doctor check fails. Does not fetch weights."""
    _validate_workstation(workstation)
    ws = discover() if workstation is None else workstation
    report = examine(ws)
    if not report.ready:
        raise StartRefused(report)
    _set_offline(ws)
    return report


def open_run(workstation: Workstation | None = None) -> RunContext:
    """Mark the process offline for a Run. Never syncs or downloads."""
    _validate_workstation(workstation)
    ws = discover() if workstation is None else workstation
    start_run(ws)
    return RunContext(
        env={
            "HF_HUB_OFFLINE": os.environ["HF_HUB_OFFLINE"],
            "TRANSFORMERS_OFFLINE": os.environ["TRANSFORMERS_OFFLINE"],
            "HF_HUB_CACHE": os.environ["HF_HUB_CACHE"],
            "BOLTZ_CACHE": os.environ["BOLTZ_CACHE"],
        }
    )


def prepare_run_process(workstation: Workstation | None = None) -> None:
    """Mark this process offline. Does not fetch weights and does not gate Start."""
    _validate_workstation(workstation)
    _set_offline(discover() if workstation is None else workstation)


def execute_guarded(
    spec_path: Path,
    runs_root: Path,
    registry: Path,
    workstation: Workstation | None = None,
) -> Path:
    """Start a Run. A failed blocking check returns before ``execute_run``."""
    _validate_workstation(workstation)
    if not isinstance(spec_path, Path) or not isinstance(runs_root, Path) or not isinstance(registry, Path):
        raise TypeError("spec_path, runs_root, and registry must be paths")
    if os.environ.get(SKIP_DOCTOR_ENV) == "1":
        _set_offline(workstation)
    else:
        start_run(workstation)
    return execute_run(spec_path, runs_root, registry)


def _validate_workstation(workstation: Workstation | None) -> None:
    if workstation is not None and not isinstance(workstation, Workstation):
        raise TypeError("workstation must be a Workstation")


def _set_offline(workstation: Workstation | None) -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if workstation is not None:
        os.environ["HF_HUB_CACHE"] = str(workstation.hf_cache)
        os.environ["BOLTZ_CACHE"] = str(workstation.boltz_cache)
