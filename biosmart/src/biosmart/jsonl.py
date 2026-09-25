"""JSON-lines transport for a persistent Scorer worker.

One request per line on stdin, one response per line on stdout.
The worker process loads models once and stays up until the Run ends.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any, Protocol, TextIO

from biosmart.scoring import ScorerFailed


class WorkerHandler(Protocol):
    def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        """Load models once and return the scoring context."""

    def score(self, request: dict[str, Any]) -> dict[str, Any]:
        """Score one Scoring round."""

    def flush(self, request: dict[str, Any]) -> dict[str, Any]:
        """Flush worker state and report how the models were used."""


def serve(handler: WorkerHandler, protocol: TextIO) -> None:
    """Read requests until stdin closes. Protocol lines go only to ``protocol``."""
    for line in sys_stdin_lines():
        if not line.strip():
            continue
        request = json.loads(line)
        if not isinstance(request, dict):
            _write(protocol, {"id": None, "ok": False, "error": "request is not an object"})
            continue
        request_id = request.get("id")
        try:
            op = request.get("op")
            if op == "prepare":
                payload = handler.prepare(request)
            elif op == "score":
                payload = handler.score(request)
            elif op == "flush":
                payload = handler.flush(request)
            else:
                raise ValueError(f"unknown Scorer worker op: {op}")
            if not isinstance(payload, dict):
                raise TypeError("Scorer worker response must be an object")
            _write(protocol, {"id": request_id, "ok": True, **payload})
        except Exception as exc:
            _write(protocol, {"id": request_id, "ok": False, "error": str(exc)})


def sys_stdin_lines():
    import sys

    return sys.stdin


def _write(protocol: TextIO, payload: dict[str, Any]) -> None:
    protocol.write(json.dumps(payload, allow_nan=False) + "\n")
    protocol.flush()


class JsonlWorker:
    """A long-lived Scorer worker. One process for the Run."""

    def __init__(self, argv: list[str], *, env: dict[str, str], log_path: Path) -> None:
        if not argv:
            raise ValueError("Scorer worker command is empty")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = log_path.open("ab")
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log,
            env=env,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self._next_id = 0
        self.argv = list(argv)

    def running(self) -> bool:
        return self._proc.poll() is None

    def request(self, op: str, **payload: Any) -> dict[str, Any]:
        if op not in {"prepare", "score", "flush"}:
            raise ValueError(f"unknown Scorer worker op: {op}")
        if self._proc.poll() is not None:
            raise ScorerFailed("Scorer worker is not running")
        self._next_id += 1
        message = {"id": self._next_id, "op": op, **payload}
        stdin = self._proc.stdin
        stdout = self._proc.stdout
        if stdin is None or stdout is None:
            raise ScorerFailed("Scorer worker pipes are closed")
        stdin.write(json.dumps(message, allow_nan=False) + "\n")
        stdin.flush()
        line = stdout.readline()
        if not line:
            raise ScorerFailed("Scorer worker closed its protocol stream")
        response = json.loads(line)
        if not isinstance(response, dict) or response.get("ok") is not True:
            error = response.get("error") if isinstance(response, dict) else None
            raise ScorerFailed(str(error or "Scorer worker failed"))
        return response

    def close(self) -> None:
        if self._proc.poll() is None:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            try:
                self._proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(self._proc.pid, signal.SIGTERM)
                try:
                    self._proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(self._proc.pid, signal.SIGKILL)
                    self._proc.wait(timeout=10)
        if not self._log.closed:
            self._log.close()
