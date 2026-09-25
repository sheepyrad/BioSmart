"""Execute one Run and leave its Run folder, events, and Index."""

from __future__ import annotations

import json
import os
import signal
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from biosmart.scoring import Candidate, FakeScorer, Scorer, ScorerFailed, candidate_smiles
from biosmart.spec import RunSpec
from biosmart.storage import (
    append_event,
    ingest_index,
    init_run_database,
    insert_candidate,
    insert_iteration,
    insert_scoring_round,
    spec_sha256,
    write_json,
)
from biosmart.worker import WorkerScorer


_STOP_REQUESTED = False
_POLICY_CHECKPOINT = Path("checkpoints") / "policy.json"


def stop_requested() -> bool:
    return _STOP_REQUESTED


def _request_stop(_signum: int, _frame: object) -> None:
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


@contextmanager
def _stop_signals() -> Iterator[None]:
    global _STOP_REQUESTED
    _STOP_REQUESTED = False
    previous = signal.signal(signal.SIGTERM, _request_stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _open_scorer(spec: RunSpec, runs_root: Path, *, ordinal: int = 0) -> FakeScorer | WorkerScorer:
    """Local FakeScorer, or a worker when the host was given its tailnet address."""
    address = os.environ.get("BIOSMART_WORKER", "").strip()
    if address:
        return WorkerScorer(
            address,
            spec.seed,
            cache_path=_scorer_cache_path(runs_root),
            ordinal=ordinal,
        )
    return FakeScorer(spec.seed, cache_path=_scorer_cache_path(runs_root), ordinal=ordinal)


def _scorer_cache_path(runs_root: Path) -> Path:
    override = os.environ.get("BIOSMART_SCORER_CACHE")
    if override:
        return Path(override)
    return runs_root / "scorer-cache.sqlite"


def _hold_for_stop(round_no: int) -> bool:
    """Wait at a Scoring round when a test asks, then report whether Stop arrived."""
    raw = os.environ.get("BIOSMART_FAKE_SCORER_BLOCK_ROUND", "").strip()
    if raw:
        blocked = int(raw)
        if blocked < 1:
            raise ValueError("BIOSMART_FAKE_SCORER_BLOCK_ROUND must be >= 1")
        if blocked == round_no:
            while not stop_requested():
                time.sleep(0.05)
    return stop_requested()


def load_spec(spec_path: Path) -> RunSpec:
    if not spec_path.is_file():
        raise FileNotFoundError(f"Run spec not found: {spec_path}")
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    return RunSpec.model_validate(payload)


def execute_run(spec_path: Path, runs_root: Path, registry: Path) -> Path:
    if not isinstance(spec_path, Path):
        raise TypeError("spec_path must be a Path")
    if not isinstance(runs_root, Path):
        raise TypeError("runs_root must be a Path")
    if not isinstance(registry, Path):
        raise TypeError("registry must be a Path")

    spec = load_spec(spec_path)
    runs_root.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    folder = runs_root / run_id
    folder.mkdir()
    (folder / "spec.json").write_bytes(spec_path.read_bytes())
    events_path = folder / "events.jsonl"
    database_path = folder / "run.sqlite"
    init_run_database(database_path)
    _write_manifest(folder, run_id=run_id, status="running", scorer=spec.scorer, seed=spec.seed)

    scorer = _open_scorer(spec, runs_root)
    with _stop_signals():
        try:
            _drive(
                folder,
                spec,
                registry,
                scorer=scorer,
                run_id=run_id,
                events_path=events_path,
                database_path=database_path,
                start_iteration=1,
                ordinal=0,
                announce=True,
            )
        except ScorerFailed:
            raise
        except Exception:
            append_event(events_path, {"type": "run.failed", "run_id": run_id})
            _write_manifest(folder, run_id=run_id, status="failed", scorer=spec.scorer, seed=spec.seed)
            raise
    return folder


def resume_run(folder: Path, runs_root: Path, registry: Path) -> Path:
    """Continue a Paused Run from its policy checkpoint. Asks nothing."""
    if not isinstance(folder, Path):
        raise TypeError("folder must be a Path")
    if not isinstance(runs_root, Path):
        raise TypeError("runs_root must be a Path")
    if not isinstance(registry, Path):
        raise TypeError("registry must be a Path")
    if not folder.is_dir():
        raise FileNotFoundError(f"Run folder not found: {folder}")
    resolved = folder.resolve()
    root = runs_root.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Resume continues a Run inside the Runs root")

    manifest = _read_json_object(folder / "run.json")
    if manifest.get("status") != "paused":
        raise ValueError("Resume continues a Paused Run")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("Paused Run is missing its run id")
    checkpoint = _read_json_object(folder / _POLICY_CHECKPOINT)
    if checkpoint.get("run_id") != run_id or checkpoint.get("seed") != manifest.get("seed"):
        raise ValueError("Policy checkpoint does not match this Run")
    completed = checkpoint.get("completed_iteration")
    scored = checkpoint.get("candidates_scored")
    if not isinstance(completed, int) or not isinstance(scored, int) or completed < 0 or scored < 0:
        raise ValueError("Policy checkpoint is missing its progress")

    spec = load_spec(folder / "spec.json")
    if checkpoint.get("seed") != spec.seed:
        raise ValueError("Policy checkpoint does not match this Run")
    if completed > spec.budget.iterations:
        raise ValueError("Policy checkpoint is past the Budget")
    events_path = folder / "events.jsonl"
    database_path = folder / "run.sqlite"
    _write_manifest(folder, run_id=run_id, status="running", scorer=spec.scorer, seed=spec.seed)
    scorer = _open_scorer(spec, runs_root, ordinal=scored)
    with _stop_signals():
        try:
            _drive(
                folder,
                spec,
                registry,
                scorer=scorer,
                run_id=run_id,
                events_path=events_path,
                database_path=database_path,
                start_iteration=completed + 1,
                ordinal=scored,
                announce=False,
            )
        except ScorerFailed:
            raise
        except Exception:
            append_event(events_path, {"type": "run.failed", "run_id": run_id})
            _write_manifest(folder, run_id=run_id, status="failed", scorer=spec.scorer, seed=spec.seed)
            raise
    return folder


def _drive(
    folder: Path,
    spec: RunSpec,
    registry: Path,
    *,
    scorer: Scorer,
    run_id: str,
    events_path: Path,
    database_path: Path,
    start_iteration: int,
    ordinal: int,
    announce: bool,
) -> None:
    context_hash = scorer.prepare(spec.target, spec.pocket)
    if announce:
        append_event(
            events_path,
            {
                "type": "run.started",
                "run_id": run_id,
                "scorer": spec.scorer,
                "seed": spec.seed,
                "iterations": spec.budget.iterations,
                "candidates_per_iteration": spec.budget.candidates_per_iteration,
            },
        )
    total = spec.budget.iterations * spec.budget.candidates_per_iteration
    smiles = candidate_smiles(spec.seed, total)
    cursor = ordinal
    completed_iteration = start_iteration - 1
    completed_round = start_iteration - 1
    for iteration in range(start_iteration, spec.budget.iterations + 1):
        round_no = iteration
        if _hold_for_stop(round_no):
            _pause(
                folder,
                events_path,
                registry,
                scorer=scorer,
                run_id=run_id,
                spec=spec,
                context_hash=context_hash,
                completed_iteration=completed_iteration,
                completed_round=completed_round,
                candidates_scored=cursor,
            )
            return
        count = spec.budget.candidates_per_iteration
        round_smiles = smiles[cursor : cursor + count]
        candidates = [
            Candidate(
                candidate_id=f"{cursor + offset + 1:06d}",
                iteration=iteration,
                round_no=round_no,
                canonical_smiles=canonical_smiles,
            )
            for offset, canonical_smiles in enumerate(round_smiles)
        ]
        append_event(
            events_path,
            {
                "type": "round.started",
                "run_id": run_id,
                "round_no": round_no,
                "iteration": iteration,
                "scorer": scorer.name,
            },
        )
        started = time.perf_counter()
        try:
            results = scorer.score(round_no, candidates)
        except ScorerFailed as exc:
            elapsed = time.perf_counter() - started
            _record_failed_scoring_round(
                events_path,
                database_path,
                run_id=run_id,
                iteration=iteration,
                round_no=round_no,
                candidates=candidates,
                scorer_name=scorer.name,
                reason=str(exc),
                secs=elapsed,
            )
            _finish_failed(
                folder,
                events_path,
                registry,
                run_id=run_id,
                spec=spec,
                scorer_name=scorer.name,
                scorer_version=scorer.version,
                context_hash=context_hash,
            )
            raise
        elapsed = time.perf_counter() - started
        for result in results:
            append_event(
                events_path,
                {
                    "type": "candidate",
                    "run_id": run_id,
                    "candidate_id": result.candidate_id,
                    "iteration": iteration,
                    "round_no": round_no,
                    "canonical_smiles": result.canonical_smiles,
                    "status": result.status,
                    "reward": result.reward,
                },
            )
            insert_candidate(
                database_path,
                candidate_id=result.candidate_id,
                iteration=iteration,
                round_no=round_no,
                canonical_smiles=result.canonical_smiles,
                status=result.status,
                reward=result.reward,
                failure_reason=result.failure_reason,
                scorer=scorer.name,
            )
        n_ok = sum(result.status == "scored" for result in results)
        n_failed = sum(result.status == "failed" for result in results)
        append_event(
            events_path,
            {
                "type": "round.finished",
                "run_id": run_id,
                "round_no": round_no,
                "iteration": iteration,
                "scorer": scorer.name,
                "n_sent": len(candidates),
                "n_ok": n_ok,
                "n_failed": n_failed,
                "secs": elapsed,
            },
        )
        insert_scoring_round(
            database_path,
            round_no=round_no,
            scorer=scorer.name,
            n_sent=len(candidates),
            n_ok=n_ok,
            n_failed=n_failed,
            secs=elapsed,
        )
        rewards = [result.reward for result in results if result.reward is not None]
        reward_avg = sum(rewards) / len(rewards) if rewards else None
        append_event(
            events_path,
            {
                "type": "iteration",
                "run_id": run_id,
                "iteration": iteration,
                "n_valid": n_ok,
                "reward_avg": reward_avg,
                "secs": elapsed,
            },
        )
        insert_iteration(
            database_path,
            iteration=iteration,
            reward_avg=reward_avg,
            n_valid=n_ok,
            secs=elapsed,
        )
        cursor += count
        completed_iteration = iteration
        completed_round = round_no
        if stop_requested():
            _pause(
                folder,
                events_path,
                registry,
                scorer=scorer,
                run_id=run_id,
                spec=spec,
                context_hash=context_hash,
                completed_iteration=completed_iteration,
                completed_round=completed_round,
                candidates_scored=cursor,
            )
            return
    scorer.flush()
    _write_provenance(
        folder,
        run_id=run_id,
        spec=spec,
        scorer_name=scorer.name,
        scorer_version=scorer.version,
        context_hash=context_hash,
    )
    ingest_index(registry, events_path)
    _write_manifest(folder, run_id=run_id, status="finished", scorer=spec.scorer, seed=spec.seed)
    append_event(events_path, {"type": "run.finished", "run_id": run_id})


def _pause(
    folder: Path,
    events_path: Path,
    registry: Path,
    *,
    scorer: Scorer,
    run_id: str,
    spec: RunSpec,
    context_hash: str,
    completed_iteration: int,
    completed_round: int,
    candidates_scored: int,
) -> None:
    entries = scorer.flush()
    checkpoint_path = folder / _POLICY_CHECKPOINT
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        checkpoint_path,
        {
            "run_id": run_id,
            "seed": spec.seed,
            "scorer": scorer.name,
            "completed_iteration": completed_iteration,
            "completed_round": completed_round,
            "candidates_scored": candidates_scored,
            "scorer_cache_flushed": True,
            "scorer_cache_entries": entries,
        },
    )
    append_event(
        events_path,
        {
            "type": "checkpoint",
            "run_id": run_id,
            "iteration": completed_iteration,
            "round_no": completed_round,
            "checkpoint": _POLICY_CHECKPOINT.as_posix(),
            "scorer_cache_flushed": True,
            "scorer_cache_entries": entries,
        },
    )
    _write_provenance(
        folder,
        run_id=run_id,
        spec=spec,
        scorer_name=scorer.name,
        scorer_version=scorer.version,
        context_hash=context_hash,
    )
    ingest_index(registry, events_path)
    _write_manifest(folder, run_id=run_id, status="paused", scorer=spec.scorer, seed=spec.seed)
    append_event(events_path, {"type": "run.paused", "run_id": run_id})


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"Paused Run is missing {path.name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not an object")
    return payload


def _record_failed_scoring_round(
    events_path: Path,
    database_path: Path,
    *,
    run_id: str,
    iteration: int,
    round_no: int,
    candidates: list[Candidate],
    scorer_name: str,
    reason: str,
    secs: float,
) -> None:
    for candidate in candidates:
        append_event(
            events_path,
            {
                "type": "candidate",
                "run_id": run_id,
                "candidate_id": candidate.candidate_id,
                "iteration": iteration,
                "round_no": round_no,
                "canonical_smiles": candidate.canonical_smiles,
                "status": "failed",
                "reward": None,
                "failure_reason": reason,
            },
        )
        insert_candidate(
            database_path,
            candidate_id=candidate.candidate_id,
            iteration=iteration,
            round_no=round_no,
            canonical_smiles=candidate.canonical_smiles,
            status="failed",
            reward=None,
            failure_reason=reason,
            scorer=scorer_name,
        )
    n_failed = len(candidates)
    append_event(
        events_path,
        {
            "type": "round.finished",
            "run_id": run_id,
            "round_no": round_no,
            "iteration": iteration,
            "scorer": scorer_name,
            "n_sent": n_failed,
            "n_ok": 0,
            "n_failed": n_failed,
            "secs": secs,
        },
    )
    insert_scoring_round(
        database_path,
        round_no=round_no,
        scorer=scorer_name,
        n_sent=n_failed,
        n_ok=0,
        n_failed=n_failed,
        secs=secs,
    )


def _finish_failed(
    folder: Path,
    events_path: Path,
    registry: Path,
    *,
    run_id: str,
    spec: RunSpec,
    scorer_name: str,
    scorer_version: str,
    context_hash: str,
) -> None:
    _write_provenance(
        folder,
        run_id=run_id,
        spec=spec,
        scorer_name=scorer_name,
        scorer_version=scorer_version,
        context_hash=context_hash,
    )
    ingest_index(registry, events_path)
    _write_manifest(folder, run_id=run_id, status="failed", scorer=spec.scorer, seed=spec.seed)
    append_event(events_path, {"type": "run.failed", "run_id": run_id})


def _write_provenance(
    folder: Path,
    *,
    run_id: str,
    spec: RunSpec,
    scorer_name: str,
    scorer_version: str,
    context_hash: str,
) -> None:
    write_json(
        folder / "provenance.json",
        {
            "run_id": run_id,
            "seed": spec.seed,
            "scorer": scorer_name,
            "scorer_version": scorer_version,
            "gpu": None,
            "context_hash": context_hash,
            "target": {"name": spec.target.name},
            "pocket": {"residues": list(spec.pocket.residues)},
            "library": {"id": spec.library.id},
            "spec_sha256": spec_sha256(folder / "spec.json"),
        },
    )


def _write_manifest(folder: Path, *, run_id: str, status: str, scorer: str, seed: int) -> None:
    write_json(
        folder / "run.json",
        {"run_id": run_id, "status": status, "scorer": scorer, "seed": seed},
    )


__all__ = ["execute_run", "load_spec", "resume_run"]
