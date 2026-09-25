"""Worker acceptor.

A worker accepts prepare, score, and flush from a host on its tailnet
address and calls the Scorer seam. It serves no UI, runs no policy, and
has no queue. Loopback is the CI stand-in for that tailnet address. It
does not listen on a public LAN address and it asks for no token.
"""

from __future__ import annotations

import ipaddress
import json
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from biosmart.scoring import Candidate, FakeScorer, ScoreResult, ScorerFailed
from biosmart.spec import PocketSpec, TargetSpec

_SCORER_PATHS = frozenset({"/prepare", "/score", "/flush"})
_TAILNET = ipaddress.ip_network("100.64.0.0/10")


def parse_listen(listen: str) -> tuple[str, int]:
    if not isinstance(listen, str) or listen.count(":") != 1:
        raise ValueError("listen address must be host:port")
    host, port_text = listen.split(":", 1)
    if not host or not port_text:
        raise ValueError("listen address must be host:port")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError("listen port must be an integer") from exc
    if port < 0 or port > 65535:
        raise ValueError("listen port must be between 0 and 65535")
    _require_tailnet_host(host)
    return host, port


def _require_tailnet_host(host: str) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("worker does not listen on a public LAN address") from exc
    if address.is_loopback:
        return
    if isinstance(address, ipaddress.IPv4Address) and address in _TAILNET:
        return
    raise ValueError("worker does not listen on a public LAN address")


class WorkerAcceptor:
    """prepare, score, and flush for one host, via the Scorer seam."""

    def __init__(self) -> None:
        self._scorer: FakeScorer | None = None
        self._lock = threading.Lock()

    def prepare(self, payload: dict[str, Any]) -> dict[str, Any]:
        seed = payload.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        try:
            target = TargetSpec.model_validate(payload["target"])
            pocket = PocketSpec.model_validate(payload["pocket"])
        except (KeyError, ValidationError) as exc:
            raise ValueError("prepare requires a Target and a Pocket") from exc
        with self._lock:
            scorer = FakeScorer(seed)
            context_hash = scorer.prepare(target, pocket)
            self._scorer = scorer
        return {"context_hash": context_hash, "scorer": scorer.name, "version": scorer.version}

    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        round_no = payload.get("round_no")
        raw_candidates = payload.get("candidates")
        if isinstance(round_no, bool) or not isinstance(round_no, int):
            raise ValueError("round_no must be an integer")
        if not isinstance(raw_candidates, list):
            raise ValueError("candidates must be a list")
        candidates = [_candidate(item) for item in raw_candidates]
        with self._lock:
            scorer = self._scorer
            if scorer is None:
                raise ValueError("prepare before score")
            results = scorer.score(round_no, candidates)
        return {"results": [_score_payload(result) for result in results]}

    def flush(self) -> dict[str, Any]:
        with self._lock:
            scorer = self._scorer
            if scorer is None:
                raise ValueError("prepare before flush")
            scorer.flush()
        return {}


class WorkerScorer:
    """Host-side Scorer. Calls prepare, score, and flush on a worker. No token."""

    def __init__(self, address: str, seed: int) -> None:
        if not isinstance(address, str) or not address.strip():
            raise ValueError("worker address is required")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        host, port = parse_listen(address.strip())
        self.address = f"{host}:{port}"
        self.seed = seed
        self.name = "fake"
        self.version = "0"

    def prepare(self, target: TargetSpec, pocket: PocketSpec) -> str:
        if not isinstance(target, TargetSpec) or not isinstance(pocket, PocketSpec):
            raise TypeError("prepare requires a Target and a Pocket")
        payload = self._post(
            "/prepare",
            {"seed": self.seed, "target": target.model_dump(), "pocket": pocket.model_dump()},
        )
        context_hash = payload.get("context_hash")
        scorer_name = payload.get("scorer")
        version = payload.get("version")
        if not isinstance(context_hash, str) or not context_hash:
            raise ValueError("worker prepare did not return a scoring context")
        if not isinstance(scorer_name, str) or not isinstance(version, str):
            raise ValueError("worker prepare did not return the Scorer")
        self.name = scorer_name
        self.version = version
        return context_hash

    def score(self, round_no: int, candidates: list[Candidate]) -> list[ScoreResult]:
        if isinstance(round_no, bool) or not isinstance(round_no, int):
            raise ValueError("round_no must be an integer")
        if not isinstance(candidates, list):
            raise TypeError("candidates must be a list")
        payload = self._post(
            "/score",
            {
                "round_no": round_no,
                "candidates": [_candidate_payload(candidate) for candidate in candidates],
            },
        )
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise ValueError("worker score did not return results")
        return [_score_result(item) for item in raw_results]

    def flush(self) -> None:
        self._post("/flush", {})

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if path not in _SCORER_PATHS:
            raise ValueError("worker accepts only prepare, score, and flush")
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        request = Request(
            url=f"http://{self.address}{path}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code >= 500:
                raise ScorerFailed(detail or "worker failed") from exc
            raise ValueError(detail or f"worker rejected {path}") from exc
        except URLError as exc:
            raise ValueError(f"worker is not reachable at {self.address}") from exc
        parsed = json.loads(raw) if raw else {}
        if not isinstance(parsed, dict):
            raise ValueError("worker response must be an object")
        return parsed


def serve(listen: str, ready_file: Path | None = None) -> None:
    host, port = parse_listen(listen)
    if ready_file is not None and not isinstance(ready_file, Path):
        raise TypeError("ready_file must be a Path")
    acceptor = WorkerAcceptor()
    server = ThreadingHTTPServer((host, port), _handler(acceptor))
    bound_host, bound_port = server.server_address[:2]
    if ready_file is not None:
        ready_file.parent.mkdir(parents=True, exist_ok=True)
        ready_file.write_text(f"{bound_host}:{bound_port}\n", encoding="utf-8")

    def _shutdown(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()


def _handler(acceptor: WorkerAcceptor) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in _SCORER_PATHS:
                self._send(404, {"error": "not found"})
                return
            payload = self._read_json()
            if payload is None:
                return
            try:
                if self.path == "/prepare":
                    result = acceptor.prepare(payload)
                elif self.path == "/score":
                    result = acceptor.score(payload)
                else:
                    result = acceptor.flush()
            except ScorerFailed as exc:
                self._send(500, {"error": str(exc)})
                return
            except (TypeError, ValueError) as exc:
                self._send(400, {"error": str(exc)})
                return
            self._send(200, result)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> dict[str, Any] | None:
            length_text = self.headers.get("Content-Length", "0")
            try:
                length = int(length_text)
            except ValueError:
                self._send(400, {"error": "invalid content length"})
                return None
            if length < 0:
                self._send(400, {"error": "invalid content length"})
                return None
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid json"})
                return None
            if not isinstance(payload, dict):
                self._send(400, {"error": "payload must be an object"})
                return None
            return payload

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _candidate(item: Any) -> Candidate:
    if not isinstance(item, dict):
        raise ValueError("candidate must be an object")
    try:
        iteration = item["iteration"]
        round_no = item["round_no"]
        candidate_id = item["candidate_id"]
        canonical_smiles = item["canonical_smiles"]
    except KeyError as exc:
        raise ValueError("candidate is missing a field") from exc
    if isinstance(iteration, bool) or not isinstance(iteration, int):
        raise ValueError("iteration must be an integer")
    if isinstance(round_no, bool) or not isinstance(round_no, int):
        raise ValueError("round_no must be an integer")
    if not isinstance(candidate_id, str) or not isinstance(canonical_smiles, str):
        raise ValueError("candidate fields must be strings")
    return Candidate(
        candidate_id=candidate_id,
        iteration=iteration,
        round_no=round_no,
        canonical_smiles=canonical_smiles,
    )


def _candidate_payload(candidate: Candidate) -> dict[str, Any]:
    if not isinstance(candidate, Candidate):
        raise TypeError("candidate must be a Candidate")
    return {
        "candidate_id": candidate.candidate_id,
        "iteration": candidate.iteration,
        "round_no": candidate.round_no,
        "canonical_smiles": candidate.canonical_smiles,
    }


def _score_payload(result: ScoreResult) -> dict[str, Any]:
    return {
        "candidate_id": result.candidate_id,
        "canonical_smiles": result.canonical_smiles,
        "status": result.status,
        "reward": result.reward,
        "failure_reason": result.failure_reason,
    }


def _score_result(item: Any) -> ScoreResult:
    if not isinstance(item, dict):
        raise ValueError("score result must be an object")
    try:
        reward = item["reward"]
        return ScoreResult(
            candidate_id=str(item["candidate_id"]),
            canonical_smiles=str(item["canonical_smiles"]),
            status=str(item["status"]),
            reward=None if reward is None else float(reward),
            failure_reason=None if item.get("failure_reason") is None else str(item["failure_reason"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("worker score result is invalid") from exc
