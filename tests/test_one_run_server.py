"""One Run at a time, streamed to the client.

Drive the runs API with a FakeScorer. Assert the event stream, the Run folder,
and the Index. The server listens on localhost. The test does not read worker
standard streams, log lines, or the React UI.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

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

Event = dict[str, Any]
Predicate = Callable[[list[Event]], bool]


def _spec() -> dict[str, Any]:
    return {
        "scorer": "fake",
        "seed": 7,
        "budget": {"iterations": 2, "candidates_per_iteration": 2},
        "target": {"name": "ns5-fixture"},
        "pocket": {"residues": ["A:42"]},
        "library": {"id": "fixture-library"},
    }


class Server:
    def __init__(self, proc: subprocess.Popen[str], port: int, runs_root: Path, registry: Path) -> None:
        self.proc = proc
        self.port = port
        self.runs_root = runs_root
        self.registry = registry

    @property
    def pid(self) -> int:
        assert self.proc.pid is not None
        return self.proc.pid


class EventStream:
    """Client side of ``GET /api/v1/events``."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.error: str | None = None
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._read, name="biosmart-events", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()

    def snapshot(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def wait_until(self, predicate: Predicate, timeout: float = 20.0) -> list[Event]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.error:
                raise AssertionError(self.error)
            snapshot = self.snapshot()
            if predicate(snapshot):
                return snapshot
            time.sleep(0.05)
        raise AssertionError(f"event stream timed out with {self.snapshot()!r}")


    def _read(self) -> None:
        import http.client

        conn: http.client.HTTPConnection | None = None
        try:
            deadline = time.monotonic() + 10
            while True:
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
                try:
                    conn.request("GET", "/api/v1/events", headers={"Accept": "text/event-stream"})
                    break
                except OSError:
                    conn.close()
                    conn = None
                    if time.monotonic() > deadline or self._stop.is_set():
                        raise
                    time.sleep(0.05)
            assert conn is not None
            response = conn.getresponse()
            if response.status != 200:
                self.error = f"event stream status {response.status}"
                return
            data_lines: list[str] = []
            while not self._stop.is_set():
                raw = response.fp.readline()
                if raw == b"":
                    return
                line = raw.decode().rstrip("\r\n")
                if line == "":
                    if data_lines:
                        payload = json.loads("\n".join(data_lines))
                        if not isinstance(payload, dict):
                            self.error = f"event is not an object: {payload!r}"
                            return
                        with self._lock:
                            self._events.append(payload)
                        data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
        except Exception as exc:
            if not self._stop.is_set():
                self.error = str(exc)
        finally:
            if conn is not None:
                conn.close()


def _request(port: int, method: str, path: str, payload: Mapping[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode()
    req = urlrequest.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    deadline = time.monotonic() + 10
    while True:
        try:
            with urlrequest.urlopen(req, timeout=30) as response:
                raw = response.read()
                parsed = json.loads(raw) if raw else {}
        except urlerror.HTTPError as exc:
            raw = exc.read()
            parsed = json.loads(raw) if raw else {}
            if not isinstance(parsed, dict):
                raise AssertionError(f"expected an object body, got {parsed!r}") from exc
            return exc.code, parsed
        except urlerror.URLError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)
            continue
        if not isinstance(parsed, dict):
            raise AssertionError(f"expected an object body, got {parsed!r}")
        return response.status, parsed


def _descendant_pids(pid: int) -> list[int]:
    children_path = Path(f"/proc/{pid}/task/{pid}/children")
    if not children_path.is_file():
        return []
    descendants: list[int] = []
    for token in children_path.read_text().split():
        child = int(token)
        descendants.append(child)
        descendants.extend(_descendant_pids(child))
    return descendants


def _signal(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except OSError:
        return


def _stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    descendants = _descendant_pids(proc.pid)
    for pid in reversed(descendants):
        _signal(pid, signal.SIGKILL)
    proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return


@contextmanager
def _serve(
    tmp_path: Path,
    *,
    extra_env: Mapping[str, str] | None = None,
    runs_root: Path | None = None,
    registry: Path | None = None,
) -> Iterator[Server]:
    if runs_root is None:
        runs_root = tmp_path / "runs"
        runs_root.mkdir()
    if registry is None:
        registry = tmp_path / "registry.sqlite"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["BIOSMART_RUNS_ROOT"] = str(runs_root)
    env["BIOSMART_REGISTRY"] = str(registry)
    env["CUDA_VISIBLE_DEVICES"] = ""
    env.pop("BIOSMART_SKIP_DOCTOR", None)
    env.pop("BIOSMART_FAKE_SCORER_BLOCK_ROUND", None)
    env.pop("BIOSMART_FAKE_SCORER_RELEASE", None)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(
        [sys.executable, "-m", "biosmart", "serve", "--port", "0"],
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout: list[str] = []
    stderr: list[str] = []

    def _drain(pipe: Any, sink: list[str]) -> None:
        if pipe is None:
            return
        for line in pipe:
            sink.append(line)

    threading.Thread(target=_drain, args=(proc.stdout, stdout), daemon=True).start()
    threading.Thread(target=_drain, args=(proc.stderr, stderr), daemon=True).start()
    port: int | None = None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for line in stdout:
            if line.startswith("http://127.0.0.1:"):
                port = int(line.strip().rsplit(":", 1)[1])
                break
        if port is not None:
            break
        if proc.poll() is not None:
            raise AssertionError(
                f"server exited {proc.returncode} before listening; stderr={''.join(stderr)}"
            )
        time.sleep(0.05)
    if port is None:
        _stop_process(proc)
        raise AssertionError(f"server did not listen; stderr={''.join(stderr)}")
    server = Server(proc, port, runs_root, registry)
    try:
        yield server
    finally:
        _stop_process(proc)


def _events_for(events: list[Event], run_id: str) -> list[Event]:
    return [event for event in events if event.get("run_id") == run_id]


def _read_events(run_folder: Path) -> list[Event]:
    return [
        json.loads(line)
        for line in (run_folder / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]


def _listening(pid: int) -> list[tuple[str, int]]:
    inodes: set[str] = set()
    fd_dir = Path(f"/proc/{pid}/fd")
    if not fd_dir.is_dir():
        return []
    for fd in fd_dir.iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inodes.add(target.removeprefix("socket:[").removesuffix("]"))
    found: list[tuple[str, int]] = []
    found.extend(_listen_table(Path("/proc/net/tcp"), socket.AF_INET, inodes))
    tcp6 = Path("/proc/net/tcp6")
    if tcp6.is_file():
        found.extend(_listen_table(tcp6, socket.AF_INET6, inodes))
    return found


def _listen_table(path: Path, family: socket.AddressFamily, inodes: set[str]) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for line in path.read_text().splitlines()[1:]:
        fields = line.split()
        local, state, inode = fields[1], fields[3], fields[9]
        if state != "0A" or inode not in inodes:
            continue
        ip_hex, port_hex = local.split(":")
        port = int(port_hex, 16)
        raw = bytes.fromhex(ip_hex)
        if family == socket.AF_INET:
            ip = socket.inet_ntop(family, raw[::-1])
        else:
            words = [raw[index : index + 4][::-1] for index in range(0, 16, 4)]
            ip = socket.inet_ntop(family, b"".join(words))
        found.append((ip, port))
    return found


def _assert_index(registry: Path, run_id: str, expected: tuple[tuple[str, float], ...]) -> None:
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
    assert [smiles for smiles, _score, _status in indexed] == [smiles for smiles, _reward in expected]
    assert [score for _smiles, score, _status in indexed] == pytest.approx(
        [reward for _smiles, reward in expected]
    )
    assert [status for _smiles, _score, status in indexed] == ["scored"] * len(expected)


def _assert_finished_folder(run_folder: Path, run_id: str) -> None:
    stored_spec = json.loads((run_folder / "spec.json").read_text())
    assert stored_spec["scorer"] == "fake"
    assert stored_spec["seed"] == 7
    assert stored_spec["budget"] == {"iterations": 2, "candidates_per_iteration": 2}
    events = _read_events(run_folder)
    assert events[0]["type"] == "run.started"
    assert events[0]["run_id"] == run_id
    assert events[-1]["type"] == "run.finished"
    assert [event["canonical_smiles"] for event in events if event["type"] == "candidate"] == [
        smiles for smiles, _reward in EXPECTED_CANDIDATES
    ]
    assert [event["reward"] for event in events if event["type"] == "candidate"] == pytest.approx(
        [reward for _smiles, reward in EXPECTED_CANDIDATES]
    )
    provenance = json.loads((run_folder / "provenance.json").read_text())
    assert provenance["seed"] == 7
    assert provenance["scorer"] == "fake"
    assert provenance["spec_sha256"] == hashlib.sha256((run_folder / "spec.json").read_bytes()).hexdigest()
    manifest = json.loads((run_folder / "run.json").read_text())
    assert manifest["run_id"] == run_id
    assert manifest["status"] == "finished"
    with sqlite3.connect(run_folder / "run.sqlite") as run_db:
        rows = run_db.execute(
            "SELECT canonical_smiles, reward, status FROM candidates ORDER BY id"
        ).fetchall()
    assert [smiles for smiles, _reward, _status in rows] == [smiles for smiles, _reward in EXPECTED_CANDIDATES]


def test_start_is_refused_without_the_doctor(tmp_path: Path) -> None:
    """Production Start does not skip the Doctor."""
    with _serve(tmp_path) as server:
        status, body = _request(server.port, "POST", "/api/v1/runs", _spec())
    assert status == 409
    assert "Doctor" in str(body.get("detail", ""))
    assert [path for path in server.runs_root.iterdir() if path.is_dir()] == []


def test_fakescorer_run_streams_events_and_writes_the_index(tmp_path: Path) -> None:
    with _serve(tmp_path, extra_env={"BIOSMART_SKIP_DOCTOR": "1"}) as server:
        stream = EventStream(server.port)
        try:
            status, created = _request(server.port, "POST", "/api/v1/runs", _spec())
            assert status == 201
            run_id = created["run_id"]
            assert created["status"] == "running"
            streamed = stream.wait_until(
                lambda events: any(
                    event.get("type") == "run.finished" and event.get("run_id") == run_id for event in events
                )
            )
        finally:
            stream.close()

    run_folder = server.runs_root / run_id
    assert run_folder.is_dir()
    file_events = _read_events(run_folder)
    assert _events_for(streamed, run_id) == file_events
    _assert_finished_folder(run_folder, run_id)
    _assert_index(server.registry, run_id, EXPECTED_CANDIDATES)


def test_second_run_waits_until_the_first_finishes(tmp_path: Path) -> None:
    release = tmp_path / "release"
    with _serve(
        tmp_path,
        extra_env={
            "BIOSMART_SKIP_DOCTOR": "1",
            "BIOSMART_FAKE_SCORER_BLOCK_ROUND": "2",
            "BIOSMART_FAKE_SCORER_RELEASE": str(release),
        },
    ) as server:
        stream = EventStream(server.port)
        try:
            _status, first = _request(server.port, "POST", "/api/v1/runs", _spec())
            first_id = first["run_id"]
            stream.wait_until(
                lambda events: any(
                    event.get("type") == "iteration" and event.get("iteration") == 1 and event.get("run_id") == first_id
                    for event in events
                )
            )
            queued_status, queued = _request(server.port, "POST", "/api/v1/runs", _spec())
            assert queued_status == 201
            second_id = queued["run_id"]
            assert queued["status"] == "queued"
            assert _events_for(stream.snapshot(), second_id) == []
            release.write_text("continue\n")
            streamed = stream.wait_until(
                lambda events: any(
                    event.get("type") == "run.finished" and event.get("run_id") == second_id for event in events
                )
            )
        finally:
            stream.close()

    first_events = _events_for(streamed, first_id)
    second_events = _events_for(streamed, second_id)
    assert first_events[-1]["type"] == "run.finished"
    assert second_events[0]["type"] == "run.started"
    assert streamed.index(first_events[-1]) < streamed.index(second_events[0])
    _assert_finished_folder(server.runs_root / first_id, first_id)
    _assert_finished_folder(server.runs_root / second_id, second_id)
    _assert_index(server.registry, first_id, EXPECTED_CANDIDATES)
    _assert_index(server.registry, second_id, EXPECTED_CANDIDATES)


def test_second_run_waits_until_the_first_is_paused_and_cancel_drops_the_queue(
    tmp_path: Path,
) -> None:
    with _serve(
        tmp_path,
        extra_env={"BIOSMART_SKIP_DOCTOR": "1", "BIOSMART_FAKE_SCORER_BLOCK_ROUND": "2"},
    ) as server:
        stream = EventStream(server.port)
        try:
            _status, first = _request(server.port, "POST", "/api/v1/runs", _spec())
            first_id = first["run_id"]
            stream.wait_until(
                lambda events: any(
                    event.get("type") == "iteration" and event.get("iteration") == 1 and event.get("run_id") == first_id
                    for event in events
                )
            )
            _queued_status, second = _request(server.port, "POST", "/api/v1/runs", _spec())
            second_id = second["run_id"]
            assert second["status"] == "queued"
            _third_status, third = _request(server.port, "POST", "/api/v1/runs", _spec())
            third_id = third["run_id"]
            assert third["status"] == "queued"
            cancelled_status, cancelled = _request(server.port, "POST", f"/api/v1/runs/{third_id}/cancel")
            assert cancelled_status == 200
            assert cancelled["status"] == "cancelled"
            read_status, read_back = _request(server.port, "GET", f"/api/v1/runs/{third_id}")
            assert read_status == 200
            assert read_back["status"] == "cancelled"
            stopped_status, stopped = _request(server.port, "POST", f"/api/v1/runs/{first_id}/stop")
            assert stopped_status == 200
            assert stopped["status"] == "paused"
            streamed = stream.wait_until(
                lambda events: any(
                    event.get("type") == "iteration" and event.get("iteration") == 1 and event.get("run_id") == second_id
                    for event in events
                )
            )
            assert _events_for(streamed, third_id) == []
            assert not (server.runs_root / third_id).exists()
        finally:
            stream.close()

    first_events = _events_for(streamed, first_id)
    second_events = _events_for(streamed, second_id)
    assert first_events[-1]["type"] == "run.paused"
    assert second_events[0]["type"] == "run.started"
    assert streamed.index(first_events[-1]) < streamed.index(second_events[0])
    manifest = json.loads((server.runs_root / first_id / "run.json").read_text())
    assert manifest["status"] == "paused"
    assert manifest["run_id"] == first_id
    _assert_index(server.registry, first_id, EXPECTED_CANDIDATES[:2])


def test_resume_continues_a_paused_run(tmp_path: Path) -> None:
    release = tmp_path / "release"
    with _serve(
        tmp_path,
        extra_env={
            "BIOSMART_SKIP_DOCTOR": "1",
            "BIOSMART_FAKE_SCORER_BLOCK_ROUND": "2",
            "BIOSMART_FAKE_SCORER_RELEASE": str(release),
        },
    ) as server:
        stream = EventStream(server.port)
        try:
            _status, created = _request(server.port, "POST", "/api/v1/runs", _spec())
            run_id = created["run_id"]
            stream.wait_until(
                lambda events: any(
                    event.get("type") == "iteration" and event.get("iteration") == 1 and event.get("run_id") == run_id
                    for event in events
                )
            )
            stopped_status, stopped = _request(server.port, "POST", f"/api/v1/runs/{run_id}/stop")
            assert stopped_status == 200
            assert stopped["status"] == "paused"
            release.write_text("continue\n")
            resumed_status, resumed = _request(server.port, "POST", f"/api/v1/runs/{run_id}/resume")
            assert resumed_status == 200
            assert resumed["run_id"] == run_id
            assert resumed["status"] == "running"
            streamed = stream.wait_until(
                lambda events: any(
                    event.get("type") == "run.finished" and event.get("run_id") == run_id for event in events
                )
            )
        finally:
            stream.close()

    run_events = _events_for(streamed, run_id)
    assert [event["type"] for event in run_events if event["type"] == "run.paused"] == ["run.paused"]
    assert run_events[-1]["type"] == "run.finished"
    assert _events_for(streamed, run_id) == _read_events(server.runs_root / run_id)
    _assert_finished_folder(server.runs_root / run_id, run_id)
    _assert_index(server.registry, run_id, EXPECTED_CANDIDATES)


def test_restart_reattaches_to_the_run_in_progress(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    registry = tmp_path / "registry.sqlite"
    runs_root.mkdir()
    extra = {"BIOSMART_SKIP_DOCTOR": "1", "BIOSMART_FAKE_SCORER_BLOCK_ROUND": "2"}
    with _serve(tmp_path, extra_env=extra, runs_root=runs_root, registry=registry) as server:
        stream = EventStream(server.port)
        try:
            _status, created = _request(server.port, "POST", "/api/v1/runs", _spec())
            run_id = created["run_id"]
            stream.wait_until(
                lambda events: any(
                    event.get("type") == "iteration" and event.get("iteration") == 1 and event.get("run_id") == run_id
                    for event in events
                )
            )
        finally:
            stream.close()
        engine_pids = _descendant_pids(server.pid)
        _signal(server.pid, signal.SIGKILL)
        try:
            server.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    assert engine_pids
    try:
        with _serve(tmp_path, extra_env=extra, runs_root=runs_root, registry=registry) as restarted:
            stream = EventStream(restarted.port)
            try:
                replayed = stream.wait_until(
                    lambda events: any(
                        event.get("type") == "iteration"
                        and event.get("iteration") == 1
                        and event.get("run_id") == run_id
                        for event in events
                    )
                )
                assert any(event.get("type") == "run.started" and event.get("run_id") == run_id for event in replayed)
                stopped_status, stopped = _request(restarted.port, "POST", f"/api/v1/runs/{run_id}/stop")
                assert stopped_status == 200
                assert stopped["status"] == "paused"
                stream.wait_until(
                    lambda events: any(
                        event.get("type") == "run.paused" and event.get("run_id") == run_id for event in events
                    )
                )
            finally:
                stream.close()
        manifest = json.loads((runs_root / run_id / "run.json").read_text())
        assert manifest["run_id"] == run_id
        assert manifest["status"] == "paused"
        _assert_index(registry, run_id, EXPECTED_CANDIDATES[:2])
    finally:
        for pid in engine_pids:
            _signal(pid, signal.SIGKILL)


def test_server_listens_on_localhost_only(tmp_path: Path) -> None:
    with _serve(tmp_path, extra_env={"BIOSMART_SKIP_DOCTOR": "1"}) as server:
        listeners = _listening(server.pid)
        assert listeners
        assert {ip for ip, _port in listeners} == {"127.0.0.1"}
        assert server.port in {port for _ip, port in listeners}
        maps = Path(f"/proc/{server.pid}/maps").read_text()
        assert "torch" not in maps
