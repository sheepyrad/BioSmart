"""Start gate. A failed blocking Doctor check refuses Start.

Opening a Run points at weights already on disk and does not fetch them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from biosmart.doctor import DoctorReport, Workstation, discover, examine


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
    """Local environment for a Run. Offline: weights are not fetched."""

    env: Mapping[str, str]


def start_run(workstation: Workstation | None = None) -> DoctorReport:
    """Refuse Start when a blocking Doctor check fails. Does not fetch weights."""
    if workstation is not None and not isinstance(workstation, Workstation):
        raise TypeError("workstation must be a Workstation")
    report = examine(workstation)
    if not report.ready:
        raise StartRefused(report)
    return report


def open_run(workstation: Workstation | None = None) -> RunContext:
    """Begin a Run against weights already on disk. Never syncs or downloads."""
    if workstation is not None and not isinstance(workstation, Workstation):
        raise TypeError("workstation must be a Workstation")
    ws = discover() if workstation is None else workstation
    start_run(ws)
    return RunContext(
        env={
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_CACHE": str(ws.hf_cache),
            "BOLTZ_CACHE": str(ws.boltz_cache),
        }
    )
