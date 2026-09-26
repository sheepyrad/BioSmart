"""Localhost runs API.

One Run executes at a time. Further Runs wait in the Registry until the running
Run finishes or is Paused. Events are the engine's JSONL stream. The listener
is 127.0.0.1 only.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError

from biosmart.index import (
    IndexNotFound,
    IndexQueryError,
    RunFolderError,
    import_run_folder,
    page_candidates,
    search_candidates,
)
from biosmart.spec import RunSpec
from biosmart.storage import connect
from biosmart.transfer import ExportError, export_top, import_run_archive, write_run_archive

LOCALHOST = "127.0.0.1"
_RUN_ID = "0123456789abcdef"


class DoctorRefused(Exception):
    """Production Start asked the Doctor and was refused."""


class RunNotFound(Exception):
    """No Run with this id is in the Registry."""


class RunConflict(Exception):
    """The Run is not in the state this command requires."""


def doctor_refuses_start() -> str | None:
    """Return a refusal message, or None when Start may proceed.

    Production Start does not set ``BIOSMART_SKIP_DOCTOR``. A FakeScorer seam
    test may set that variable to skip the Doctor. Otherwise Start asks the
    Doctor, and a missing or negative report refuses the Run.
    """
    if os.environ.get("BIOSMART_SKIP_DOCTOR") == "1":
        return None
    try:
        import biosmart.doctor as doctor
    except ImportError:
        return "Doctor refuses Start"
    allows_start = getattr(doctor, "allows_start", None)
    if not callable(allows_start) or not allows_start():
        return "Doctor refuses Start"
    return None


def _valid_run_id(run_id: str) -> bool:
    return len(run_id) == 32 and all(character in _RUN_ID for character in run_id)


def _pid_alive(pid: int) -> bool:
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        text = stat_path.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        state = text.rsplit(")", 1)[1].split()[0]
    except (IndexError, ValueError):
        return False
    return state not in {"Z", "X"}


def _cmdline_matches(pid: int, run_id: str) -> bool:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    text = raw.replace(b"\x00", b" ").decode(errors="replace")
    return "biosmart" in text and run_id in text


class Supervisor:
    """In-process FIFO for Runs. The executing engine survives a server restart."""

    def __init__(self, runs_root: Path, registry: Path) -> None:
        self.runs_root = runs_root
        self.registry = registry
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    def init_registry(self) -> None:
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    spec_json TEXT,
                    folder TEXT,
                    engine_pid INTEGER,
                    enqueued_at TEXT NOT NULL,
                    queue_at TEXT NOT NULL,
                    resume INTEGER NOT NULL
                )
                """
            )

    async def start(self) -> None:
        self.init_registry()
        async with self._lock:
            running = self._running()
            if running is not None:
                pid = running["engine_pid"]
                run_id = str(running["run_id"])
                if isinstance(pid, int) and _pid_alive(pid) and _cmdline_matches(pid, run_id):
                    self._watch(run_id, pid)
                else:
                    self._sync_from_folder(run_id)
            await self._pump()

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

    async def enqueue(self, payload: Mapping[str, Any]) -> tuple[str, str]:
        refusal = doctor_refuses_start()
        if refusal:
            raise DoctorRefused(refusal)
        spec = RunSpec.model_validate(payload)
        run_id = uuid.uuid4().hex
        stamp = _stamp()
        folder = str(self.runs_root / run_id)
        async with self._lock:
            self._execute(
                """
                INSERT INTO runs (
                    run_id, status, spec_json, folder, engine_pid,
                    enqueued_at, queue_at, resume
                ) VALUES (?, 'queued', ?, ?, NULL, ?, ?, 0)
                """,
                (run_id, json.dumps(spec.model_dump()), folder, stamp, stamp),
            )
            await self._pump()
            status = str(self._require(run_id)["status"])
        return run_id, status

    def read(self, run_id: str) -> dict[str, Any]:
        row = self._get(run_id)
        if row is None:
            raise RunNotFound(run_id)
        return {"run_id": run_id, "status": row["status"]}

    async def cancel(self, run_id: str) -> dict[str, Any]:
        async with self._lock:
            row = self._require(run_id)
            if row["status"] != "queued":
                raise RunConflict("Cancel drops a queued Run")
            self._set_status(run_id, "cancelled")
        return {"run_id": run_id, "status": "cancelled"}

    async def stop(self, run_id: str) -> dict[str, Any]:
        async with self._lock:
            row = self._require(run_id)
            if row["status"] != "running" or not isinstance(row["engine_pid"], int):
                raise RunConflict("Stop pauses the running Run")
            pid = int(row["engine_pid"])
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 30
        while _pid_alive(pid) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if _pid_alive(pid):
            raise RunConflict("Stop did not pause the Run")
        async with self._lock:
            current = self._require(run_id)
            if current["engine_pid"] == pid and current["status"] == "running":
                self._sync_from_folder(run_id)
                await self._pump()
            status = str(self._require(run_id)["status"])
        if status != "paused":
            raise RunConflict("Stop did not pause the Run")
        return {"run_id": run_id, "status": status}

    async def note_imported(self, run_id: str, folder: Path, status: str) -> None:
        if status not in {"paused", "finished", "failed"}:
            raise RunConflict("Import rebuilds a finished, failed, or Paused Run")
        async with self._lock:
            row = self._get(run_id)
            if row is not None and row["status"] == "running":
                raise RunConflict("Import does not replace a running Run")
            stamp = _stamp()
            if row is None:
                self._execute(
                    """
                    INSERT INTO runs (
                        run_id, status, spec_json, folder, engine_pid,
                        enqueued_at, queue_at, resume
                    ) VALUES (?, ?, NULL, ?, NULL, ?, ?, 0)
                    """,
                    (run_id, status, str(folder), stamp, stamp),
                )
            else:
                self._execute(
                    """
                    UPDATE runs
                    SET status = ?, folder = ?, engine_pid = NULL
                    WHERE run_id = ?
                    """,
                    (status, str(folder), run_id),
                )

    async def resume(self, run_id: str) -> dict[str, Any]:
        async with self._lock:
            row = self._require(run_id)
            if row["status"] != "paused":
                raise RunConflict("Resume continues a Paused Run")
            self._execute(
                "UPDATE runs SET status = 'queued', resume = 1, queue_at = ? WHERE run_id = ?",
                (_stamp(), run_id),
            )
            await self._pump()
            status = str(self._require(run_id)["status"])
        return {"run_id": run_id, "status": status}

    def event_sources(self) -> list[tuple[str, Path]]:
        with self._db() as connection:
            rows = connection.execute("SELECT run_id FROM runs ORDER BY enqueued_at").fetchall()
        sources: list[tuple[str, Path]] = []
        for row in rows:
            run_id = row["run_id"]
            if not isinstance(run_id, str):
                continue
            sources.append((run_id, self.runs_root / run_id / "events.jsonl"))
        return sources

    async def _pump(self) -> None:
        if self._running() is not None:
            return
        queued = self._next_queued()
        if queued is None:
            return
        await self._spawn(queued)

    async def _spawn(self, row: Mapping[str, Any]) -> None:
        run_id = str(row["run_id"])
        folder = self.runs_root / run_id
        env = os.environ.copy()
        env["BIOSMART_RUNS_ROOT"] = str(self.runs_root)
        env["BIOSMART_REGISTRY"] = str(self.registry)
        env.pop("BIOSMART_RUN_ID", None)
        if int(row["resume"]) == 1:
            argv = [sys.executable, "-m", "biosmart", "run", "--resume", str(folder)]
        else:
            spec_text = row["spec_json"]
            if not isinstance(spec_text, str) or not spec_text:
                raise RunConflict("Queued Run is missing its spec")
            spec_path = self._spec_path(run_id)
            spec_path.parent.mkdir(parents=True, exist_ok=True)
            spec_path.write_text(spec_text, encoding="utf-8")
            env["BIOSMART_RUN_ID"] = run_id
            argv = [sys.executable, "-m", "biosmart", "run", str(spec_path)]
        process = await asyncio.create_subprocess_exec(
            *argv,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        pid = process.pid
        if pid is None:
            raise RunConflict("The Run did not start")
        self._execute(
            """
            UPDATE runs
            SET status = 'running', engine_pid = ?, folder = ?, resume = 0
            WHERE run_id = ?
            """,
            (pid, str(folder), run_id),
        )
        self._watch(run_id, pid)

    def _watch(self, run_id: str, pid: int) -> None:
        task = asyncio.create_task(self._until_exit(run_id, pid))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _until_exit(self, run_id: str, pid: int) -> None:
        while _pid_alive(pid):
            await asyncio.sleep(0.05)
        async with self._lock:
            row = self._get(run_id)
            if row is None or row["engine_pid"] != pid or row["status"] != "running":
                return
            self._sync_from_folder(run_id)
            await self._pump()

    def _sync_from_folder(self, run_id: str) -> None:
        manifest_path = self.runs_root / run_id / "run.json"
        status = "failed"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest = None
            if isinstance(manifest, dict):
                recorded = manifest.get("status")
                if recorded in {"paused", "finished", "failed"}:
                    status = str(recorded)
        self._set_status(run_id, status)

    def _spec_path(self, run_id: str) -> Path:
        return self.registry.parent / "run-specs" / f"{run_id}.json"

    def _running(self) -> Mapping[str, Any] | None:
        return self._one("SELECT * FROM runs WHERE status = 'running' ORDER BY enqueued_at LIMIT 1")

    def _next_queued(self) -> Mapping[str, Any] | None:
        return self._one("SELECT * FROM runs WHERE status = 'queued' ORDER BY queue_at LIMIT 1")

    def _require(self, run_id: str) -> Mapping[str, Any]:
        row = self._get(run_id)
        if row is None:
            raise RunNotFound(run_id)
        return row

    def _get(self, run_id: str) -> Mapping[str, Any] | None:
        return self._one("SELECT * FROM runs WHERE run_id = ?", (run_id,))

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> Mapping[str, Any] | None:
        with self._db() as connection:
            row = connection.execute(sql, params).fetchone()
        if row is None:
            return None
        return dict(row)

    def _set_status(self, run_id: str, status: str) -> None:
        self._execute(
            "UPDATE runs SET status = ?, engine_pid = NULL WHERE run_id = ?",
            (status, run_id),
        )

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._db() as connection:
            connection.execute(sql, params)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        connection = connect(self.registry)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


def _stamp() -> str:
    return str(time.time_ns())


def _new_events(path: Path, offset: int) -> tuple[int, list[str]]:
    try:
        data = path.read_bytes()
    except OSError:
        return offset, []
    if offset > len(data):
        offset = 0
    fresh = data[offset:]
    newline = fresh.rfind(b"\n")
    if newline < 0:
        return offset, []
    complete = fresh[: newline + 1]
    lines = [
        line.decode()
        for line in complete.splitlines()
        if line.strip()
    ]
    return offset + len(complete), lines


def create_app() -> FastAPI:
    runs_root_env = os.environ.get("BIOSMART_RUNS_ROOT")
    if not runs_root_env:
        raise RuntimeError("BIOSMART_RUNS_ROOT is required")
    runs_root = Path(runs_root_env)
    registry_env = os.environ.get("BIOSMART_REGISTRY")
    registry = Path(registry_env) if registry_env else runs_root / "registry.sqlite"
    supervisor = Supervisor(runs_root, registry)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await supervisor.start()
        try:
            yield
        finally:
            await supervisor.shutdown()

    app = FastAPI(lifespan=lifespan)
    app.state.supervisor = supervisor

    @app.post("/api/v1/runs", status_code=201)
    async def start_run(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="Run spec must be JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="Run spec must be an object")
        try:
            run_id, status = await supervisor.enqueue(payload)
        except DoctorRefused as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse({"run_id": run_id, "status": status}, status_code=201)

    @app.get("/api/v1/runs/{run_id}")
    async def read_run(run_id: str) -> dict[str, Any]:
        if not _valid_run_id(run_id):
            raise HTTPException(status_code=404, detail="Run not found")
        try:
            return supervisor.read(run_id)
        except RunNotFound as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    @app.post("/api/v1/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> dict[str, Any]:
        return await _command(supervisor.cancel, run_id)

    @app.post("/api/v1/runs/{run_id}/stop")
    async def stop_run(run_id: str) -> dict[str, Any]:
        return await _command(supervisor.stop, run_id)

    @app.post("/api/v1/runs/{run_id}/resume")
    async def resume_run(run_id: str) -> dict[str, Any]:
        return await _command(supervisor.resume, run_id)

    @app.get("/api/v1/runs/{run_id}/candidates")
    async def list_candidates(
        run_id: str,
        limit: int = 50,
        cursor: str | None = None,
        sort: str = "candidate_id",
        status_filter: str | None = Query(default=None, alias="filter"),
        min_score: float | None = None,
        max_score: float | None = None,
        min_mw: float | None = None,
        max_mw: float | None = None,
        min_logp: float | None = None,
        max_logp: float | None = None,
    ) -> dict[str, Any]:
        if not _valid_run_id(run_id):
            raise HTTPException(status_code=404, detail="Run not found")
        try:
            return page_candidates(
                supervisor.registry,
                run_id,
                limit=limit,
                cursor=cursor,
                sort=sort,
                status=status_filter,
                min_score=min_score,
                max_score=max_score,
                min_mw=min_mw,
                max_mw=max_mw,
                min_logp=min_logp,
                max_logp=max_logp,
            )
        except IndexNotFound as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc
        except IndexQueryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/runs/{run_id}/export")
    async def export_run(
        run_id: str,
        export_format: str = Query(alias="format"),
        top: int = Query(),
    ) -> Response:
        folder = _require_run_folder(supervisor, run_id)
        try:
            body, media_type, filename = export_top(folder, export_format=export_format, top=top)
        except ExportError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RunFolderError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(
            content=body,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/v1/runs/{run_id}/archive")
    async def archive_run(run_id: str, request: Request) -> dict[str, Any]:
        folder = _require_run_folder(supervisor, run_id)
        payload = await _json_object(request, "Archive must be JSON")
        destination = payload.get("destination")
        if destination is None:
            archive_path = supervisor.runs_root / "archives" / f"{run_id}.tar.zst"
        elif isinstance(destination, str) and destination:
            archive_path = Path(destination)
        else:
            raise HTTPException(status_code=422, detail="destination must be a path")
        try:
            written = write_run_archive(folder, archive_path)
        except RunFolderError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"run_id": run_id, "archive": str(written)}

    @app.post("/api/v1/runs/import")
    async def import_run(request: Request) -> dict[str, Any]:
        payload = await _json_object(request, "Import must be JSON")
        folder = payload.get("folder")
        archive = payload.get("archive")
        has_folder = isinstance(folder, str) and bool(folder)
        has_archive = isinstance(archive, str) and bool(archive)
        if has_folder == has_archive:
            raise HTTPException(status_code=422, detail="Import takes a Run folder or an archive")
        try:
            if has_archive:
                imported = import_run_archive(
                    supervisor.runs_root,
                    supervisor.registry,
                    Path(str(archive)),
                )
            else:
                imported = import_run_folder(
                    supervisor.runs_root,
                    supervisor.registry,
                    Path(str(folder)),
                )
            await supervisor.note_imported(
                str(imported["run_id"]),
                Path(str(imported["folder"])),
                str(imported["status"]),
            )
        except RunFolderError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RunConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "run_id": imported["run_id"],
            "status": imported["status"],
            "candidates": imported["candidates"],
        }

    @app.get("/api/v1/search")
    async def search(
        smarts: str | None = None,
        similar_to: str | None = None,
        threshold: float | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        try:
            return search_candidates(
                supervisor.registry,
                smarts=smarts,
                similar_to=similar_to,
                threshold=threshold,
                limit=limit,
                cursor=cursor,
            )
        except IndexQueryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/events")
    async def events(request: Request) -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            offsets: dict[str, int] = {}
            while not await request.is_disconnected():
                for run_id, path in supervisor.event_sources():
                    offset, lines = _new_events(path, offsets.get(run_id, 0))
                    offsets[run_id] = offset
                    for line in lines:
                        yield f"data: {line}\n\n"
                await asyncio.sleep(0.05)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _require_run_folder(supervisor: Supervisor, run_id: str) -> Path:
    if not _valid_run_id(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    folder = (supervisor.runs_root / run_id).resolve()
    root = supervisor.runs_root.resolve()
    if folder != root and root not in folder.parents:
        raise HTTPException(status_code=404, detail="Run not found")
    if not (folder / "run.json").is_file() or not (folder / "run.sqlite").is_file():
        raise HTTPException(status_code=404, detail="Run not found")
    return folder


async def _json_object(request: Request, invalid: str) -> dict[str, Any]:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=invalid) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail=invalid)
    return payload


async def _command(
    action: Callable[[str], Awaitable[dict[str, Any]]],
    run_id: str,
) -> dict[str, Any]:
    if not _valid_run_id(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        result = await action(run_id)
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Run command failed")
    return result


class _LocalhostServer:
    """Uvicorn server that publishes the bound localhost address after listen."""

    def __init__(self, port: int) -> None:
        import uvicorn

        config = uvicorn.Config(
            create_app(),
            host=LOCALHOST,
            port=port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)

    def run(self) -> None:
        server = self._server
        startup = server.startup

        async def startup_and_publish(sockets: list[Any] | None = None) -> None:
            await startup(sockets=sockets)
            for listener in server.servers:
                for sock in listener.sockets or []:
                    host, bound_port = sock.getsockname()[:2]
                    print(f"http://{host}:{bound_port}", flush=True)

        server.startup = startup_and_publish  # type: ignore[method-assign]
        server.run()


def serve(port: int) -> None:
    if not isinstance(port, int) or isinstance(port, bool) or port < 0 or port > 65535:
        raise ValueError("port must be between 0 and 65535")
    if not os.environ.get("BIOSMART_RUNS_ROOT"):
        raise ValueError("BIOSMART_RUNS_ROOT is required")
    _LocalhostServer(port).run()


__all__ = ["LOCALHOST", "create_app", "doctor_refuses_start", "serve"]
