"""Worker acceptor.

A worker accepts prepare, score, and flush from a host on its tailnet
address and calls the Scorer seam. Each call is one JSON object per line
on a TCP socket. It serves no UI, runs no policy, and has no queue. It
does not listen on a public LAN address and it asks for no token.

Loopback is the CI stand-in for that tailnet address. A hostname is
allowed when it resolves into loopback, Tailscale IPv4, or Tailscale IPv6.
"""

from __future__ import annotations

import ipaddress
import json
import signal
import socket
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from biosmart.scoring import Candidate, FakeScorer, ScoreResult, ScorerFailed
from biosmart.spec import PocketSpec, TargetSpec

_OPS = frozenset({"prepare", "score", "flush"})
_TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
_TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


def parse_listen(listen: str) -> tuple[str, int]:
    host, port_text = _split_host_port(listen)
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError("listen port must be an integer") from exc
    if port < 0 or port > 65535:
        raise ValueError("listen port must be between 0 and 65535")
    return _bindable_host(host), port


def _split_host_port(listen: str) -> tuple[str, str]:
    if not isinstance(listen, str) or not listen:
        raise ValueError("listen address must be host:port")
    if listen.startswith("["):
        end = listen.find("]")
        if end < 0 or not listen[end:].startswith("]:"):
            raise ValueError("listen address must be host:port")
        host = listen[1:end]
        port_text = listen[end + 2 :]
    else:
        if listen.count(":") != 1:
            raise ValueError("listen address must be host:port")
        host, port_text = listen.rsplit(":", 1)
    if not host or not port_text:
        raise ValueError("listen address must be host:port")
    return host, port_text


def _bindable_host(host: str) -> str:
    literal = _literal_ip(host)
    if literal is not None:
        if not _allowed(literal):
            raise ValueError("worker does not listen on a public LAN address")
        return str(literal)
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("worker does not listen on a public LAN address") from exc
    for info in infos:
        resolved = _literal_ip(str(info[4][0]))
        if resolved is not None and _allowed(resolved):
            return str(resolved)
    raise ValueError("worker does not listen on a public LAN address")


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _allowed(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    if mapped is not None:
        return _allowed(mapped)
    if address.is_loopback:
        return True
    if isinstance(address, ipaddress.IPv4Address) and address in _TAILNET_V4:
        return True
    if isinstance(address, ipaddress.IPv6Address) and address in _TAILNET_V6:
        return True
    return False


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
        self._host = host
        self._port = port
        self.seed = seed
        self.name = "fake"
        self.version = "0"
        self._sock: socket.socket | None = None
        self._reader: Any = None
        self._writer: Any = None
        self._lock = threading.Lock()

    def prepare(self, target: TargetSpec, pocket: PocketSpec) -> str:
        if not isinstance(target, TargetSpec) or not isinstance(pocket, PocketSpec):
            raise TypeError("prepare requires a Target and a Pocket")
        payload = self._call(
            {
                "op": "prepare",
                "seed": self.seed,
                "target": target.model_dump(),
                "pocket": pocket.model_dump(),
            }
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
        payload = self._call(
            {
                "op": "score",
                "round_no": round_no,
                "candidates": [_candidate_payload(candidate) for candidate in candidates],
            }
        )
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise ValueError("worker score did not return results")
        return [_score_result(item) for item in raw_results]

    def flush(self) -> None:
        self._call({"op": "flush"})

    def _call(self, payload: dict[str, Any]) -> dict[str, Any]:
        op = payload.get("op")
        if op not in _OPS:
            raise ValueError("worker accepts only prepare, score, and flush")
        line = json.dumps(payload, allow_nan=False).encode("utf-8") + b"\n"
        with self._lock:
            self._ensure()
            assert self._writer is not None and self._reader is not None
            self._writer.write(line)
            self._writer.flush()
            raw = self._reader.readline()
        if not raw:
            raise ValueError(f"worker is not reachable at {self._host}:{self._port}")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("worker response is not a JSON line") from exc
        if not isinstance(parsed, dict):
            raise ValueError("worker response must be an object")
        if parsed.get("scorer_failed") is True:
            message = parsed.get("error")
            raise ScorerFailed(message if isinstance(message, str) and message else "FakeScorer failed")
        if parsed.get("ok") is False:
            message = parsed.get("error")
            raise ValueError(message if isinstance(message, str) and message else "worker rejected the call")
        return parsed

    def _ensure(self) -> None:
        if self._sock is not None:
            return
        try:
            sock = socket.create_connection((self._host, self._port), timeout=60)
        except OSError as exc:
            raise ValueError(f"worker is not reachable at {self._host}:{self._port}") from exc
        sock.settimeout(60)
        self._sock = sock
        self._reader = sock.makefile("rb")
        self._writer = sock.makefile("wb")


def serve(listen: str, ready_file: Path | None = None) -> None:
    host, port = parse_listen(listen)
    if ready_file is not None and not isinstance(ready_file, Path):
        raise TypeError("ready_file must be a Path")
    acceptor = WorkerAcceptor()
    server = _bind_socket(host, port)
    bound = server.getsockname()
    if ready_file is not None:
        ready_file.parent.mkdir(parents=True, exist_ok=True)
        ready_file.write_text(_format_address(str(bound[0]), int(bound[1])) + "\n", encoding="utf-8")

    stop = threading.Event()

    def _shutdown(_signum: int, _frame: object) -> None:
        stop.set()
        server.close()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    server.settimeout(0.2)
    try:
        while not stop.is_set():
            try:
                connection, _peer = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(
                target=_serve_connection,
                args=(connection, acceptor),
                daemon=True,
            ).start()
    finally:
        server.close()


def _bind_socket(host: str, port: int) -> socket.socket:
    address = ipaddress.ip_address(host)
    family = socket.AF_INET6 if isinstance(address, ipaddress.IPv6Address) else socket.AF_INET
    server = socket.socket(family, socket.SOCK_STREAM)
    if family == socket.AF_INET6:
        server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(16)
    return server


def _format_address(host: str, port: int) -> str:
    if ":" in host:
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def _serve_connection(connection: socket.socket, acceptor: WorkerAcceptor) -> None:
    connection.settimeout(60)
    reader = connection.makefile("rb")
    writer = connection.makefile("wb")
    try:
        for raw in reader:
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                _write_line(writer, {"ok": False, "error": "invalid json"})
                continue
            if not isinstance(payload, dict):
                _write_line(writer, {"ok": False, "error": "payload must be an object"})
                continue
            op = payload.get("op")
            try:
                if op == "prepare":
                    result = acceptor.prepare(payload)
                elif op == "score":
                    result = acceptor.score(payload)
                elif op == "flush":
                    result = acceptor.flush()
                else:
                    _write_line(writer, {"ok": False, "error": "not found"})
                    continue
            except ScorerFailed as exc:
                # The line is the score failure. Re-raising here would close
                # the socket before the host records the Scoring round.
                _write_line(writer, {"ok": False, "scorer_failed": True, "error": str(exc)})
                continue
            except (TypeError, ValueError) as exc:
                _write_line(writer, {"ok": False, "error": str(exc)})
                continue
            _write_line(writer, {"ok": True, **result})
    finally:
        reader.close()
        writer.close()
        connection.close()


def _write_line(writer: Any, payload: dict[str, Any]) -> None:
    writer.write(json.dumps(payload, allow_nan=False).encode("utf-8") + b"\n")
    writer.flush()


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
