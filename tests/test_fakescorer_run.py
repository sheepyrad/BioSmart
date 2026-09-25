"""FakeScorer Run seam.

Drive ``biosmart run`` with a FakeScorer and read only the event stream, the
Run folder, and the Index. The Run finishes on CPU. Stop pauses a Run and
Resume continues it. The test does not read worker standard streams, log
lines, or the React UI.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BIOSMART_SRC = REPO / "biosmart" / "src"

# Seed 7 walks a fixed catalog from index ``7 % 6 == 1`` and scores the k-th
# Candidate as ``-((7 * 10 + k) % 100) / 100``. These literals are that walk.
EXPECTED_CANDIDATES = (
    ("CCN", -0.70),
    ("CC(=O)O", -0.71),
    ("c1ccccc1", -0.72),
    ("CCC", -0.73),
)


def test_fakescorer_run_writes_events_run_folder_and_index(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry = tmp_path / "registry.sqlite"
    runs_root.mkdir()
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "scorer": "fake",
                "seed": 7,
                "budget": {"iterations": 2, "candidates_per_iteration": 2},
                "target": {"name": "ns5-fixture"},
                "pocket": {"residues": ["A:42"]},
                "library": {"id": "fixture-library"},
            }
        )
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["BIOSMART_RUNS_ROOT"] = str(runs_root)
    env["BIOSMART_REGISTRY"] = str(registry)
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

    run_folders = [path for path in runs_root.iterdir() if path.is_dir()]
    assert len(run_folders) == 1
    run_folder = run_folders[0]

    stored_spec = json.loads((run_folder / "spec.json").read_text())
    assert stored_spec["scorer"] == "fake"
    assert stored_spec["seed"] == 7
    assert stored_spec["budget"]["iterations"] == 2
    assert stored_spec["budget"]["candidates_per_iteration"] == 2

    events = [
        json.loads(line)
        for line in (run_folder / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert events[0]["type"] == "run.started"
    assert events[-1]["type"] == "run.finished"
    assert all(event["type"] != "run.failed" for event in events)

    run_id = events[0]["run_id"]
    iterations = [event for event in events if event["type"] == "iteration"]
    assert [event["iteration"] for event in iterations] == [1, 2]

    assert [event["round_no"] for event in events if event["type"] == "round.started"] == [1, 2]
    finished_rounds = [event for event in events if event["type"] == "round.finished"]
    assert [event["round_no"] for event in finished_rounds] == [1, 2]
    assert [event["n_sent"] for event in finished_rounds] == [2, 2]
    assert [event["n_ok"] for event in finished_rounds] == [2, 2]

    candidates = [event for event in events if event["type"] == "candidate"]
    assert [event["canonical_smiles"] for event in candidates] == [
        smiles for smiles, _reward in EXPECTED_CANDIDATES
    ]
    assert [event["reward"] for event in candidates] == pytest.approx(
        [reward for _smiles, reward in EXPECTED_CANDIDATES]
    )
    assert [event["iteration"] for event in candidates] == [1, 1, 2, 2]
    assert [event["status"] for event in candidates] == ["scored", "scored", "scored", "scored"]

    provenance = json.loads((run_folder / "provenance.json").read_text())
    assert provenance["seed"] == 7
    assert provenance["scorer"] == "fake"
    assert provenance["gpu"] is None
    assert provenance["target"]["name"] == "ns5-fixture"
    assert provenance["pocket"]["residues"] == ["A:42"]
    assert provenance["library"]["id"] == "fixture-library"
    assert provenance["spec_sha256"] == hashlib.sha256((run_folder / "spec.json").read_bytes()).hexdigest()

    manifest = json.loads((run_folder / "run.json").read_text())
    assert manifest["run_id"] == run_id
    assert manifest["status"] == "finished"

    with sqlite3.connect(run_folder / "run.sqlite") as run_db:
        rows = run_db.execute(
            "SELECT canonical_smiles, reward, status FROM candidates ORDER BY id"
        ).fetchall()
    assert [smiles for smiles, _reward, _status in rows] == [
        smiles for smiles, _reward in EXPECTED_CANDIDATES
    ]
    assert [reward for _smiles, reward, _status in rows] == pytest.approx(
        [reward for _smiles, reward in EXPECTED_CANDIDATES]
    )
    assert [status for _smiles, _reward, status in rows] == ["scored"] * 4

    with sqlite3.connect(f"file:{registry}?mode=ro", uri=True) as index:
        indexed = index.execute(
            """
            SELECT canonical_smiles, best_score, status
            FROM candidate_index
            WHERE run_id = ?
            ORDER BY candidate_id
            """,
            (run_id,),
        ).fetchall()
    assert [smiles for smiles, _score, _status in indexed] == [
        smiles for smiles, _reward in EXPECTED_CANDIDATES
    ]
    assert [score for _smiles, score, _status in indexed] == pytest.approx(
        [reward for _smiles, reward in EXPECTED_CANDIDATES]
    )
    assert [status for _smiles, _score, status in indexed] == ["scored"] * 4


def test_fakescorer_failure_records_provenance_and_failed_index(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry = tmp_path / "registry.sqlite"
    runs_root.mkdir()
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "scorer": "fake",
                "seed": 7,
                "budget": {"iterations": 1, "candidates_per_iteration": 1},
                "target": {"name": "ns5-fixture"},
                "pocket": {"residues": ["A:42"]},
                "library": {"id": "fixture-library"},
            }
        )
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["BIOSMART_RUNS_ROOT"] = str(runs_root)
    env["BIOSMART_REGISTRY"] = str(registry)
    env["BIOSMART_FAKE_SCORER_FAIL"] = "1"
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
    assert completed.returncode != 0

    run_folders = [path for path in runs_root.iterdir() if path.is_dir()]
    assert len(run_folders) == 1
    run_folder = run_folders[0]

    events = [
        json.loads(line)
        for line in (run_folder / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert events[0]["type"] == "run.started"
    assert events[-1]["type"] == "run.failed"
    assert all(event["type"] != "run.finished" for event in events)
    run_id = events[0]["run_id"]

    failed = [event for event in events if event["type"] == "candidate"]
    assert [event["canonical_smiles"] for event in failed] == ["CCN"]
    assert [event["status"] for event in failed] == ["failed"]

    provenance = json.loads((run_folder / "provenance.json").read_text())
    assert provenance["seed"] == 7
    assert provenance["scorer"] == "fake"
    assert provenance["gpu"] is None
    assert provenance["target"]["name"] == "ns5-fixture"
    assert provenance["pocket"]["residues"] == ["A:42"]
    assert provenance["library"]["id"] == "fixture-library"
    assert provenance["spec_sha256"] == hashlib.sha256((run_folder / "spec.json").read_bytes()).hexdigest()

    with sqlite3.connect(f"file:{registry}?mode=ro", uri=True) as index:
        indexed = index.execute(
            """
            SELECT canonical_smiles, status
            FROM candidate_index
            WHERE run_id = ?
            ORDER BY candidate_id
            """,
            (run_id,),
        ).fetchall()
    assert indexed == [("CCN", "failed")]


def _read_events(run_folder: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (run_folder / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]


def _wait_until_iteration_held(proc: subprocess.Popen[str], runs_root: Path, iteration: int) -> Path:
    """Wait until a Scoring round has finished and the Run is still executing."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr is not None else ""
            raise AssertionError(f"Run exited {proc.returncode} before Stop; stderr={stderr}")
        folders = [path for path in runs_root.iterdir() if path.is_dir()]
        if len(folders) == 1:
            events_path = folders[0] / "events.jsonl"
            if events_path.is_file():
                events = _read_events(folders[0])
                held = any(
                    event.get("type") == "iteration" and event.get("iteration") == iteration
                    for event in events
                )
                if held:
                    return folders[0]
        time.sleep(0.05)
    raise AssertionError("Run did not reach the held Iteration")


def test_stop_pauses_fakescorer_run_and_resume_continues(tmp_path: Path) -> None:
    """Stop flushes the policy checkpoint and the Scorer cache, then Resume continues that Run."""
    runs_root = tmp_path / "runs"
    registry = tmp_path / "registry.sqlite"
    runs_root.mkdir()
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "scorer": "fake",
                "seed": 7,
                "budget": {"iterations": 2, "candidates_per_iteration": 2},
                "target": {"name": "ns5-fixture"},
                "pocket": {"residues": ["A:42"]},
                "library": {"id": "fixture-library"},
            }
        )
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["BIOSMART_RUNS_ROOT"] = str(runs_root)
    env["BIOSMART_REGISTRY"] = str(registry)
    env["BIOSMART_FAKE_SCORER_BLOCK_ROUND"] = "2"
    env["CUDA_VISIBLE_DEVICES"] = ""

    proc = subprocess.Popen(
        [sys.executable, "-m", "biosmart", "run", str(spec_path)],
        cwd=REPO,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    run_folder = _wait_until_iteration_held(proc, runs_root, iteration=1)
    proc.send_signal(signal.SIGTERM)
    stdout, stderr = proc.communicate(timeout=30)
    assert proc.returncode == 0, stderr
    assert stdout.strip() == str(run_folder)

    run_folders = [path for path in runs_root.iterdir() if path.is_dir()]
    assert run_folders == [run_folder]

    events = _read_events(run_folder)
    assert events[0]["type"] == "run.started"
    assert [event["type"] for event in events[-2:]] == ["checkpoint", "run.paused"]
    assert all(event["type"] != "run.failed" for event in events)
    assert all(event["type"] != "run.finished" for event in events)
    run_id = events[0]["run_id"]
    assert events[-1]["run_id"] == run_id
    checkpoint_event = events[-2]
    assert checkpoint_event["run_id"] == run_id
    assert checkpoint_event["iteration"] == 1
    assert checkpoint_event["round_no"] == 1
    assert checkpoint_event["checkpoint"] == "checkpoints/policy.json"
    assert checkpoint_event["scorer_cache_flushed"] is True
    assert checkpoint_event["scorer_cache_entries"] == 2

    checkpoint = json.loads((run_folder / "checkpoints" / "policy.json").read_text())
    assert checkpoint["run_id"] == run_id
    assert checkpoint["seed"] == 7
    assert checkpoint["scorer"] == "fake"
    assert checkpoint["completed_iteration"] == 1
    assert checkpoint["completed_round"] == 1
    assert checkpoint["candidates_scored"] == 2
    assert checkpoint["scorer_cache_flushed"] is True
    assert checkpoint["scorer_cache_entries"] == 2

    manifest = json.loads((run_folder / "run.json").read_text())
    assert manifest["run_id"] == run_id
    assert manifest["status"] == "paused"
    assert manifest["scorer"] == "fake"
    assert manifest["seed"] == 7

    paused_candidates = [event for event in events if event["type"] == "candidate"]
    assert [event["canonical_smiles"] for event in paused_candidates] == [
        smiles for smiles, _reward in EXPECTED_CANDIDATES[:2]
    ]
    assert [event["reward"] for event in paused_candidates] == pytest.approx(
        [reward for _smiles, reward in EXPECTED_CANDIDATES[:2]]
    )
    assert [event["iteration"] for event in events if event["type"] == "iteration"] == [1]
    assert [event["round_no"] for event in events if event["type"] == "round.finished"] == [1]

    provenance = json.loads((run_folder / "provenance.json").read_text())
    assert provenance["run_id"] == run_id
    assert provenance["seed"] == 7
    assert provenance["scorer"] == "fake"
    assert provenance["spec_sha256"] == hashlib.sha256((run_folder / "spec.json").read_bytes()).hexdigest()

    with sqlite3.connect(run_folder / "run.sqlite") as run_db:
        rows = run_db.execute(
            "SELECT canonical_smiles, reward, status FROM candidates ORDER BY id"
        ).fetchall()
    assert [smiles for smiles, _reward, _status in rows] == [
        smiles for smiles, _reward in EXPECTED_CANDIDATES[:2]
    ]
    assert [reward for _smiles, reward, _status in rows] == pytest.approx(
        [reward for _smiles, reward in EXPECTED_CANDIDATES[:2]]
    )

    with sqlite3.connect(f"file:{registry}?mode=ro", uri=True) as index:
        indexed = index.execute(
            """
            SELECT canonical_smiles, best_score, status
            FROM candidate_index
            WHERE run_id = ?
            ORDER BY candidate_id
            """,
            (run_id,),
        ).fetchall()
    assert [smiles for smiles, _score, _status in indexed] == [
        smiles for smiles, _reward in EXPECTED_CANDIDATES[:2]
    ]
    assert [score for _smiles, score, _status in indexed] == pytest.approx(
        [reward for _smiles, reward in EXPECTED_CANDIDATES[:2]]
    )
    assert [status for _smiles, _score, status in indexed] == ["scored", "scored"]

    resume_env = os.environ.copy()
    resume_env["PYTHONPATH"] = str(BIOSMART_SRC)
    resume_env["BIOSMART_RUNS_ROOT"] = str(runs_root)
    resume_env["BIOSMART_REGISTRY"] = str(registry)
    resume_env["CUDA_VISIBLE_DEVICES"] = ""
    resumed = subprocess.run(
        [sys.executable, "-m", "biosmart", "run", "--resume", str(run_folder)],
        cwd=REPO,
        env=resume_env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert resumed.stdout.strip() == str(run_folder)
    assert [path for path in runs_root.iterdir() if path.is_dir()] == [run_folder]

    events = _read_events(run_folder)
    assert events[0]["type"] == "run.started"
    assert events[0]["run_id"] == run_id
    assert events[-1]["type"] == "run.finished"
    assert events[-1]["run_id"] == run_id
    assert [event["type"] for event in events if event["type"] == "run.paused"] == ["run.paused"]
    assert all(event["type"] != "run.failed" for event in events)
    assert [event["iteration"] for event in events if event["type"] == "iteration"] == [1, 2]
    assert [event["round_no"] for event in events if event["type"] == "round.finished"] == [1, 2]

    candidates = [event for event in events if event["type"] == "candidate"]
    assert [event["canonical_smiles"] for event in candidates] == [
        smiles for smiles, _reward in EXPECTED_CANDIDATES
    ]
    assert [event["reward"] for event in candidates] == pytest.approx(
        [reward for _smiles, reward in EXPECTED_CANDIDATES]
    )
    assert [event["iteration"] for event in candidates] == [1, 1, 2, 2]
    assert [event["status"] for event in candidates] == ["scored", "scored", "scored", "scored"]

    manifest = json.loads((run_folder / "run.json").read_text())
    assert manifest["run_id"] == run_id
    assert manifest["status"] == "finished"

    with sqlite3.connect(run_folder / "run.sqlite") as run_db:
        rows = run_db.execute(
            "SELECT canonical_smiles, reward, status FROM candidates ORDER BY id"
        ).fetchall()
    assert [smiles for smiles, _reward, _status in rows] == [
        smiles for smiles, _reward in EXPECTED_CANDIDATES
    ]
    assert [reward for _smiles, reward, _status in rows] == pytest.approx(
        [reward for _smiles, reward in EXPECTED_CANDIDATES]
    )

    with sqlite3.connect(f"file:{registry}?mode=ro", uri=True) as index:
        indexed = index.execute(
            """
            SELECT canonical_smiles, best_score, status
            FROM candidate_index
            WHERE run_id = ?
            ORDER BY candidate_id
            """,
            (run_id,),
        ).fetchall()
    assert [smiles for smiles, _score, _status in indexed] == [
        smiles for smiles, _reward in EXPECTED_CANDIDATES
    ]
    assert [score for _smiles, score, _status in indexed] == pytest.approx(
        [reward for _smiles, reward in EXPECTED_CANDIDATES]
    )
    assert [status for _smiles, _score, status in indexed] == ["scored"] * 4
