"""Presets and ETA. Thorough is not executed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from biosmart.eta import estimate_eta_seconds
from biosmart.presets import PRESET_BUDGETS
from biosmart.spec import RunSpec

REPO = Path(__file__).resolve().parents[1]
BIOSMART_SRC = REPO / "biosmart" / "src"


def _spec(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "scorer": "fake",
        "seed": 7,
        "budget": {"iterations": 2, "candidates_per_iteration": 2},
        "target": {"name": "ns5-fixture"},
        "pocket": {"residues": ["A:42"]},
        "library": {"id": "fixture-library"},
    }
    payload.update(overrides)
    return payload


def test_presets_are_the_named_budgets() -> None:
    assert PRESET_BUDGETS == {
        "quick": (100, 16),
        "standard": (1000, 32),
        "thorough": (2000, 64),
    }
    thorough = RunSpec.model_validate(
        _spec(preset="thorough", budget=None, scorer="fake")
    )
    assert thorough.budget is not None
    assert thorough.budget.iterations == 2000
    assert thorough.budget.candidates_per_iteration == 64
    with pytest.raises(ValidationError):
        RunSpec.model_validate(
            _spec(
                preset="thorough",
                budget={"iterations": 1, "candidates_per_iteration": 32},
            )
        )


def test_boltz2_pocket_is_selected_residues() -> None:
    sequence = "ACDEFGHIK"
    with pytest.raises(ValidationError, match="selected residues"):
        RunSpec.model_validate(
            _spec(
                scorer="boltz2",
                budget={"iterations": 1, "candidates_per_iteration": 1},
                target={"name": "NS5", "sequence": sequence},
                pocket={"residues": []},
            )
        )
    with pytest.raises(ValidationError, match="CHAIN:NUMBER"):
        RunSpec.model_validate(
            _spec(
                scorer="boltz2",
                budget={"iterations": 1, "candidates_per_iteration": 1},
                target={"name": "NS5", "sequence": sequence},
                pocket={"residues": ["ligand.mol2"]},
            )
        )
    spec = RunSpec.model_validate(
        _spec(
            scorer="boltz2",
            budget={"iterations": 1, "candidates_per_iteration": 32},
            target={"name": "NS5", "sequence": sequence},
            pocket={"residues": ["A:16", "A:67"]},
        )
    )
    assert spec.pocket.residues == ["A:16", "A:67"]
    assert spec.budget is not None
    assert (spec.budget.iterations, spec.budget.candidates_per_iteration) == (1, 32)


def test_eta_uses_recorded_round_durations_only() -> None:
    assert (
        estimate_eta_seconds(
            [],
            iterations=2000,
            candidates_per_iteration=64,
            completed_iterations=0,
        )
        is None
    )
    eta = estimate_eta_seconds(
        [(32, 10.0)],
        iterations=2000,
        candidates_per_iteration=64,
        completed_iterations=1,
    )
    remaining = (2000 - 1) * 64
    assert eta == pytest.approx(10.0 / 32 * remaining)
    assert (
        estimate_eta_seconds(
            [(16, 4.0), (16, 8.0)],
            iterations=2,
            candidates_per_iteration=16,
            completed_iterations=2,
        )
        == 0
    )


def test_fake_run_eta_comes_from_scoring_rounds(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(_spec()))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["BIOSMART_RUNS_ROOT"] = str(runs_root)
    env["BIOSMART_REGISTRY"] = str(tmp_path / "registry.sqlite")
    env["BIOSMART_SKIP_DOCTOR"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = ""
    completed = subprocess.run(
        [sys.executable, "-m", "biosmart", "run", str(spec_path)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    run_folder = next(path for path in runs_root.iterdir() if path.is_dir())
    events = [
        json.loads(line)
        for line in (run_folder / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    finished = [event for event in events if event["type"] == "round.finished"]
    assert [event["round_no"] for event in finished] == [1, 2]
    assert finished[0]["eta_seconds"] == pytest.approx(finished[0]["secs"])
    assert finished[1]["eta_seconds"] == 0


def test_quick_preset_run_uses_100_by_16(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    spec_path = tmp_path / "spec.json"
    payload = _spec()
    del payload["budget"]
    payload["preset"] = "quick"
    spec_path.write_text(json.dumps(payload))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["BIOSMART_RUNS_ROOT"] = str(runs_root)
    env["BIOSMART_REGISTRY"] = str(tmp_path / "registry.sqlite")
    env["BIOSMART_SKIP_DOCTOR"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = ""
    completed = subprocess.run(
        [sys.executable, "-m", "biosmart", "run", str(spec_path)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    run_folder = next(path for path in runs_root.iterdir() if path.is_dir())
    stored = json.loads((run_folder / "spec.json").read_text())
    assert stored["preset"] == "quick"
    assert stored["budget"] == {"iterations": 100, "candidates_per_iteration": 16}
    events = [
        json.loads(line)
        for line in (run_folder / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert events[0]["preset"] == "quick"
    assert events[0]["iterations"] == 100
    assert events[0]["candidates_per_iteration"] == 16
    assert events[-1]["type"] == "run.finished"
    assert sum(event["type"] == "iteration" for event in events) == 100
