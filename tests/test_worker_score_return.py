"""Host Run stores one worker Scoring round.

A host Run sends one Scoring round through prepare, score, and flush. The
policy and the Run stay on the host. Scores and Scorer working files land in
the host Run folder, and the round records the worker as the machine that
scored it. The worker then drops its scratch. CI is two local processes.
The test reads the event stream and the host Run folder. It does not read
the worker's standard streams.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BIOSMART_SRC = REPO / "biosmart" / "src"

# Seed 7 walks a fixed catalog from index ``7 % 6 == 1``. One Scoring round
# of two Candidates is that walk. These literals are the walk, not a recomputation.
EXPECTED_CANDIDATES = (
    ("CCN", -0.70),
    ("CC(=O)O", -0.71),
)


def test_host_run_stores_the_worker_scoring_round(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry = tmp_path / "registry.sqlite"
    scratch = tmp_path / "worker-scratch"
    runs_root.mkdir()
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "scorer": "fake",
                "seed": 7,
                "budget": {"iterations": 1, "candidates_per_iteration": 2},
                "target": {"name": "ns5-fixture"},
                "pocket": {"residues": ["A:42"]},
                "library": {"id": "fixture-library"},
            }
        ),
        encoding="utf-8",
    )

    ready = tmp_path / "worker-ready"
    worker_env = _base_env()
    worker_env["BIOSMART_WORKER_SCRATCH"] = str(scratch)
    worker_env.pop("BIOSMART_RUNS_ROOT", None)
    worker_env.pop("BIOSMART_REGISTRY", None)
    worker_env.pop("BIOSMART_TOKEN", None)
    worker_env.pop("BIOSMART_FAKE_SCORER_FAIL", None)
    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "biosmart",
            "worker",
            "--listen",
            "127.0.0.1:0",
            "--ready-file",
            str(ready),
        ],
        cwd=REPO,
        env=worker_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        address = _wait_ready(ready, worker)
        host, port_text = address.rsplit(":", 1)
        port = int(port_text)
        assert host == "127.0.0.1"
        listeners = _listen_endpoints(worker.pid)
        assert listeners == {("127.0.0.1", port)}
        assert all(bound_host != "0.0.0.0" for bound_host, _bound_port in listeners)

        host_env = _base_env()
        host_env["BIOSMART_RUNS_ROOT"] = str(runs_root)
        host_env["BIOSMART_REGISTRY"] = str(registry)
        host_env["BIOSMART_WORKER"] = address
        # A local FakeScorer on the host would fail. The Scoring round has to
        # come back from the worker.
        host_env["BIOSMART_FAKE_SCORER_FAIL"] = "1"
        host_env.pop("BIOSMART_TOKEN", None)
        host_env.pop("BIOSMART_WORKER_SCRATCH", None)

        completed = subprocess.run(
            [sys.executable, "-m", "biosmart", "run", str(spec_path)],
            cwd=REPO,
            env=host_env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert worker.poll() is None
        deadline = time.monotonic() + 5
        while scratch.exists() and time.monotonic() < deadline:
            time.sleep(0.05)

        run_folders = [path for path in runs_root.iterdir() if path.is_dir()]
        assert len(run_folders) == 1
        run_folder = run_folders[0]
        assert scratch not in run_folder.parents
        assert not scratch.exists()
        assert not (scratch / "scorer" / "round_1").exists()
        assert not (scratch / "checkpoints" / "policy.json").exists()
        assert not (scratch / "events.jsonl").exists()
        assert not (scratch / "run.sqlite").exists()

        events = [
            json.loads(line)
            for line in (run_folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert events[0]["type"] == "run.started"
        assert events[-1]["type"] == "run.finished"
        assert all(event["type"] != "run.failed" for event in events)
        assert [event["round_no"] for event in events if event["type"] == "round.started"] == [1]
        finished = [event for event in events if event["type"] == "round.finished"]
        assert len(finished) == 1
        assert finished[0]["round_no"] == 1
        assert finished[0]["n_sent"] == 2
        assert finished[0]["n_ok"] == 2
        assert finished[0]["scorer"] == "fake"
        assert finished[0]["machine"] == address
        iterations = [event for event in events if event["type"] == "iteration"]
        assert [event["iteration"] for event in iterations] == [1]
        candidates = [event for event in events if event["type"] == "candidate"]
        assert [event["canonical_smiles"] for event in candidates] == [
            smiles for smiles, _reward in EXPECTED_CANDIDATES
        ]
        assert [event["reward"] for event in candidates] == pytest.approx(
            [reward for _smiles, reward in EXPECTED_CANDIDATES]
        )
        assert [event["status"] for event in candidates] == ["scored", "scored"]

        working = json.loads(
            (run_folder / "scorer" / "round_1" / "round.json").read_text(encoding="utf-8")
        )
        assert working["round_no"] == 1
        assert working["scorer"] == "fake"
        assert working["scorer_version"] == "0"
        assert working["context_hash"] == "fake:0:ns5-fixture:A:42"
        assert working["machine"] == address
        assert [row["canonical_smiles"] for row in working["candidates"]] == [
            smiles for smiles, _reward in EXPECTED_CANDIDATES
        ]
        assert [row["reward"] for row in working["candidates"]] == pytest.approx(
            [reward for _smiles, reward in EXPECTED_CANDIDATES]
        )
        assert [row["status"] for row in working["candidates"]] == ["scored", "scored"]

        with sqlite3.connect(run_folder / "run.sqlite") as run_db:
            scores = run_db.execute(
                """
                SELECT candidates.canonical_smiles, scores.reward, scores.scorer
                FROM scores
                JOIN candidates ON candidates.id = scores.candidate_id
                ORDER BY candidates.id
                """
            ).fetchall()
            rounds = run_db.execute(
                "SELECT round_no, scorer, n_sent, n_ok, machine FROM scoring_rounds"
            ).fetchall()
            iteration_rows = run_db.execute(
                "SELECT iteration, n_valid FROM iterations"
            ).fetchall()
        assert [smiles for smiles, _reward, _scorer in scores] == [
            smiles for smiles, _reward in EXPECTED_CANDIDATES
        ]
        assert [reward for _smiles, reward, _scorer in scores] == pytest.approx(
            [reward for _smiles, reward in EXPECTED_CANDIDATES]
        )
        assert [scorer for _smiles, _reward, scorer in scores] == ["fake", "fake"]
        assert rounds == [(1, "fake", 2, 2, address)]
        assert iteration_rows == [(1, 2)]
        assert (run_folder / "spec.json").is_file()
        assert (run_folder / "run.json").is_file()
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["BIOSMART_SKIP_DOCTOR"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = ""
    env.pop("BIOSMART_TOKEN", None)
    env.pop("BIOSMART_FAKE_SCORER_FAIL", None)
    env.pop("BIOSMART_WORKER", None)
    env.pop("BIOSMART_WORKER_SCRATCH", None)
    return env


def _wait_ready(path: Path, proc: subprocess.Popen[bytes], timeout: float = 10) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"worker exited {proc.returncode}")
        if path.is_file():
            address = path.read_text(encoding="utf-8").strip()
            if address:
                return address
        time.sleep(0.05)
    raise AssertionError("worker did not publish its tailnet address")


def _listen_endpoints(pid: int) -> set[tuple[str, int]]:
    inodes = _socket_inodes(pid)
    found: set[tuple[str, int]] = set()
    tcp = Path(f"/proc/{pid}/net/tcp")
    if not tcp.is_file():
        tcp = Path("/proc/net/tcp")
    for line in tcp.read_text(encoding="utf-8").splitlines()[1:]:
        fields = line.split()
        if len(fields) < 10 or fields[3] != "0A" or fields[9] not in inodes:
            continue
        ip_hex, port_hex = fields[1].split(":")
        octets = bytes.fromhex(ip_hex)
        host = ".".join(str(octet) for octet in octets[::-1])
        found.add((host, int(port_hex, 16)))
    return found


def _socket_inodes(pid: int) -> set[str]:
    inodes: set[str] = set()
    fd_dir = Path(f"/proc/{pid}/fd")
    for fd in fd_dir.iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inodes.add(target.removeprefix("socket:[").removesuffix("]"))
    return inodes
