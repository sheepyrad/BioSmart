"""Execute one Run and leave its Run folder, events, and Index."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from biosmart.scoring import Candidate, FakeScorer, ScorerFailed, candidate_smiles
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

    scorer = FakeScorer(spec.seed)
    try:
        context_hash = scorer.prepare(spec.target, spec.pocket)
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
        cursor = 0
        for iteration in range(1, spec.budget.iterations + 1):
            round_no = iteration
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
    except ScorerFailed:
        raise
    except Exception:
        append_event(events_path, {"type": "run.failed", "run_id": run_id})
        _write_manifest(folder, run_id=run_id, status="failed", scorer=spec.scorer, seed=spec.seed)
        raise
    return folder


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


__all__ = ["execute_run", "load_spec"]
