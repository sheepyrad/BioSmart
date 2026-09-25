"""Worker acceptor seam.

A host calls prepare, score, and flush on a worker. The worker's listen
address stands in for the tailnet interface. FakeScorer scores the Scoring
round. The test reads the event stream, the Run folder, and the Index. It
does not read the worker's standard streams.
"""

from __future__ import annotations

import ipaddress
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BIOSMART_SRC = REPO / "biosmart" / "src"

# Seed 7 walks a fixed catalog from index ``7 % 6 == 1``. The first Scoring
# round has two Candidates. These literals are that walk, not a recomputation.
EXPECTED_CANDIDATES = (
    ("CCN", -0.70),
    ("CC(=O)O", -0.71),
)
# The same walk through a 2×2 Budget. Resume must continue at ordinal 2.
CONTINUED_CANDIDATES = (
    ("CCN", -0.70),
    ("CC(=O)O", -0.71),
    ("c1ccccc1", -0.72),
    ("CCC", -0.73),
)
_CONTEXT_HASH = "fake:0:ns5-fixture:A:42"


def test_worker_prepare_score_and_flush_record_the_scoring_round(tmp_path: Path) -> None:
    env = _base_env()
    refused_ready = tmp_path / "refused-ready"
    refused = subprocess.run(
        [
            sys.executable,
            "-m",
            "biosmart",
            "worker",
            "--listen",
            "0.0.0.0:18080",
            "--ready-file",
            str(refused_ready),
        ],
        cwd=REPO,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    assert refused.returncode != 0
    assert not refused_ready.exists()

    runs_root = tmp_path / "runs"
    registry = tmp_path / "registry.sqlite"
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
        )
    )

    ready = tmp_path / "worker-ready"
    worker_env = env.copy()
    worker_env.pop("BIOSMART_FAKE_SCORER_FAIL", None)
    worker_env.pop("BIOSMART_TOKEN", None)
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

        for op in ("ui", "policy", "queue"):
            reply = _exchange(address, {"op": op})
            assert reply.get("ok") is not True
            assert "results" not in reply

        host_env = env.copy()
        host_env["BIOSMART_RUNS_ROOT"] = str(runs_root)
        host_env["BIOSMART_REGISTRY"] = str(registry)
        host_env["BIOSMART_WORKER"] = address
        # A local FakeScorer on the host would fail. Scores have to come from the worker.
        host_env["BIOSMART_FAKE_SCORER_FAIL"] = "1"
        host_env.pop("BIOSMART_TOKEN", None)

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

        run_folders = [path for path in runs_root.iterdir() if path.is_dir()]
        assert len(run_folders) == 1
        run_folder = run_folders[0]

        stored_spec = json.loads((run_folder / "spec.json").read_text())
        assert stored_spec["scorer"] == "fake"
        assert stored_spec["seed"] == 7
        assert stored_spec["budget"] == {"iterations": 1, "candidates_per_iteration": 2}

        events = [
            json.loads(line)
            for line in (run_folder / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert events[0]["type"] == "run.started"
        assert events[-1]["type"] == "run.finished"
        assert all(event["type"] != "run.failed" for event in events)
        run_id = events[0]["run_id"]

        assert [event["round_no"] for event in events if event["type"] == "round.started"] == [1]
        finished = [event for event in events if event["type"] == "round.finished"]
        assert len(finished) == 1
        assert finished[0]["round_no"] == 1
        assert finished[0]["n_sent"] == 2
        assert finished[0]["n_ok"] == 2
        assert finished[0]["scorer"] == "fake"

        candidates = [event for event in events if event["type"] == "candidate"]
        assert [event["canonical_smiles"] for event in candidates] == [
            smiles for smiles, _reward in EXPECTED_CANDIDATES
        ]
        assert [event["reward"] for event in candidates] == pytest.approx(
            [reward for _smiles, reward in EXPECTED_CANDIDATES]
        )
        assert [event["status"] for event in candidates] == ["scored", "scored"]
        assert [event["iteration"] for event in candidates] == [1, 1]

        iterations = [event for event in events if event["type"] == "iteration"]
        assert [event["iteration"] for event in iterations] == [1]

        provenance = json.loads((run_folder / "provenance.json").read_text())
        assert provenance["seed"] == 7
        assert provenance["scorer"] == "fake"
        assert provenance["scorer_version"] == "0"
        assert provenance["gpu"] is None
        assert provenance["context_hash"] == "fake:0:ns5-fixture:A:42"
        assert provenance["target"]["name"] == "ns5-fixture"
        assert provenance["pocket"]["residues"] == ["A:42"]

        manifest = json.loads((run_folder / "run.json").read_text())
        assert manifest["run_id"] == run_id
        assert manifest["status"] == "finished"
        assert manifest["scorer"] == "fake"

        with sqlite3.connect(run_folder / "run.sqlite") as run_db:
            rows = run_db.execute(
                "SELECT canonical_smiles, reward, status FROM candidates ORDER BY id"
            ).fetchall()
            rounds = run_db.execute(
                "SELECT round_no, scorer, n_sent, n_ok FROM scoring_rounds ORDER BY round_no"
            ).fetchall()
        assert [smiles for smiles, _reward, _status in rows] == [
            smiles for smiles, _reward in EXPECTED_CANDIDATES
        ]
        assert [reward for _smiles, reward, _status in rows] == pytest.approx(
            [reward for _smiles, reward in EXPECTED_CANDIDATES]
        )
        assert [status for _smiles, _reward, status in rows] == ["scored", "scored"]
        assert rounds == [(1, "fake", 2, 2)]

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
            tables = {
                name
                for (name,) in index.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        assert "run_queue" not in tables
        assert [smiles for smiles, _score, _status in indexed] == [
            smiles for smiles, _reward in EXPECTED_CANDIDATES
        ]
        assert [score for _smiles, score, _status in indexed] == pytest.approx(
            [reward for _smiles, reward in EXPECTED_CANDIDATES]
        )
        assert [status for _smiles, _score, status in indexed] == ["scored", "scored"]
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["CUDA_VISIBLE_DEVICES"] = ""
    env.pop("BIOSMART_TOKEN", None)
    env.pop("BIOSMART_FAKE_SCORER_FAIL", None)
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


def test_worker_allows_a_hostname_that_resolves_to_loopback(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "biosmart",
            "worker",
            "--listen",
            "localhost:0",
            "--ready-file",
            str(ready),
        ],
        cwd=REPO,
        env=_base_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        address = _wait_ready(ready, worker)
        host, _port = _split_address(address)
        assert ipaddress.ip_address(host).is_loopback
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)


def test_failed_score_records_the_scoring_round_provenance_and_index(tmp_path: Path) -> None:
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
    ready = tmp_path / "worker-ready"
    worker_env = _base_env()
    worker_env["BIOSMART_FAKE_SCORER_FAIL"] = "1"
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
        host_env = _base_env()
        host_env["BIOSMART_RUNS_ROOT"] = str(runs_root)
        host_env["BIOSMART_REGISTRY"] = str(registry)
        host_env["BIOSMART_WORKER"] = address
        host_env.pop("BIOSMART_FAKE_SCORER_FAIL", None)
        completed = subprocess.run(
            [sys.executable, "-m", "biosmart", "run", str(spec_path)],
            cwd=REPO,
            env=host_env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode != 0

        run_folders = [path for path in runs_root.iterdir() if path.is_dir()]
        assert len(run_folders) == 1
        run_folder = run_folders[0]
        assert run_folder.is_dir()
        assert (run_folder / "provenance.json").is_file()

        events = [
            json.loads(line)
            for line in (run_folder / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert events[0]["type"] == "run.started"
        assert events[-1]["type"] == "run.failed"
        assert all(event["type"] != "run.finished" for event in events)
        run_id = events[0]["run_id"]

        finished = [event for event in events if event["type"] == "round.finished"]
        assert len(finished) == 1
        assert finished[0]["round_no"] == 1
        assert finished[0]["n_sent"] == 1
        assert finished[0]["n_ok"] == 0
        assert finished[0]["n_failed"] == 1

        failed = [event for event in events if event["type"] == "candidate"]
        assert [event["canonical_smiles"] for event in failed] == ["CCN"]
        assert [event["status"] for event in failed] == ["failed"]

        provenance = json.loads((run_folder / "provenance.json").read_text())
        assert provenance["seed"] == 7
        assert provenance["scorer"] == "fake"
        assert provenance["gpu"] is None
        assert provenance["context_hash"] == "fake:0:ns5-fixture:A:42"
        assert provenance["target"]["name"] == "ns5-fixture"
        assert provenance["pocket"]["residues"] == ["A:42"]

        with sqlite3.connect(run_folder / "run.sqlite") as run_db:
            rounds = run_db.execute(
                "SELECT round_no, n_sent, n_ok, n_failed FROM scoring_rounds"
            ).fetchall()
        assert rounds == [(1, 1, 0, 1)]

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
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)


def test_worker_pause_records_the_cache_and_resume_continues(tmp_path: Path) -> None:
    """Pause records the flush count in the host cache. Resume continues the ordinal."""
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
    ready = tmp_path / "worker-ready"
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
        env=_base_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        address = _wait_ready(ready, worker)
        host_env = _base_env()
        host_env["BIOSMART_RUNS_ROOT"] = str(runs_root)
        host_env["BIOSMART_REGISTRY"] = str(registry)
        host_env["BIOSMART_WORKER"] = address
        host_env["BIOSMART_FAKE_SCORER_FAIL"] = "1"
        host_env["BIOSMART_FAKE_SCORER_BLOCK_ROUND"] = "2"
        proc = subprocess.Popen(
            [sys.executable, "-m", "biosmart", "run", str(spec_path)],
            cwd=REPO,
            env=host_env,
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
        assert worker.poll() is None

        events = _read_events(run_folder)
        assert events[0]["type"] == "run.started"
        assert [event["type"] for event in events[-2:]] == ["checkpoint", "run.paused"]
        run_id = events[0]["run_id"]
        checkpoint_event = events[-2]
        assert isinstance(checkpoint_event["scorer_cache_entries"], int)
        assert checkpoint_event["scorer_cache_entries"] == 2
        assert checkpoint_event["scorer_cache_flushed"] is True

        checkpoint = json.loads((run_folder / "checkpoints" / "policy.json").read_text())
        assert checkpoint["candidates_scored"] == 2
        assert isinstance(checkpoint["scorer_cache_entries"], int)
        assert checkpoint["scorer_cache_entries"] == 2
        _assert_cache(runs_root / "scorer-cache.sqlite", EXPECTED_CANDIDATES)

        resume_env = _base_env()
        resume_env["BIOSMART_RUNS_ROOT"] = str(runs_root)
        resume_env["BIOSMART_REGISTRY"] = str(registry)
        resume_env["BIOSMART_WORKER"] = address
        resume_env["BIOSMART_FAKE_SCORER_FAIL"] = "1"
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

        events = _read_events(run_folder)
        assert events[0]["run_id"] == run_id
        assert events[-1]["type"] == "run.finished"
        candidates = [event for event in events if event["type"] == "candidate"]
        assert [event["canonical_smiles"] for event in candidates] == [
            smiles for smiles, _reward in CONTINUED_CANDIDATES
        ]
        assert [event["reward"] for event in candidates] == pytest.approx(
            [reward for _smiles, reward in CONTINUED_CANDIDATES]
        )
        assert [event["iteration"] for event in candidates] == [1, 1, 2, 2]
        _assert_cache(runs_root / "scorer-cache.sqlite", CONTINUED_CANDIDATES)
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)


def _read_events(run_folder: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (run_folder / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]


def _wait_until_iteration_held(proc: subprocess.Popen[str], runs_root: Path, iteration: int) -> Path:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr is not None else ""
            raise AssertionError(f"Run exited {proc.returncode} before Stop; stderr={stderr}")
        folders = [path for path in runs_root.iterdir() if path.is_dir()]
        if len(folders) == 1:
            events_path = folders[0] / "events.jsonl"
            if events_path.is_file():
                held = any(
                    event.get("type") == "iteration" and event.get("iteration") == iteration
                    for event in _read_events(folders[0])
                )
                if held:
                    return folders[0]
        time.sleep(0.05)
    raise AssertionError("Run did not reach the held Iteration")


def _assert_cache(path: Path, expected: tuple[tuple[str, float], ...]) -> None:
    with sqlite3.connect(path) as database:
        rows = database.execute(
            """
            SELECT canonical_smiles, reward
            FROM scorer_cache
            WHERE scorer = 'fake'
              AND scorer_version = '0'
              AND context_hash = ?
            """,
            (_CONTEXT_HASH,),
        ).fetchall()
    assert len(rows) == len(expected)
    by_smiles = {smiles: reward for smiles, reward in rows}
    assert set(by_smiles) == {smiles for smiles, _reward in expected}
    for smiles, reward in expected:
        assert by_smiles[smiles] == pytest.approx(reward)


def _exchange(address: str, payload: dict[str, object]) -> dict[str, object]:
    host, port = _split_address(address)
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        sock.shutdown(socket.SHUT_WR)
        buffer = b""
        while b"\n" not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
    line = buffer.splitlines()[0]
    assert b"<html" not in line.lower()
    assert b"<!doctype" not in line.lower()
    parsed = json.loads(line)
    assert isinstance(parsed, dict)
    return parsed


def _split_address(address: str) -> tuple[str, int]:
    if address.startswith("["):
        host, port_text = address[1:].split("]:", 1)
        return host, int(port_text)
    host, port_text = address.rsplit(":", 1)
    return host, int(port_text)
