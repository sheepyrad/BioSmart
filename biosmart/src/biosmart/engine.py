"""Execute one Run and leave its Run folder, events, and Index."""

from __future__ import annotations

import json
import os
import shutil
import signal
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from biosmart.eta import estimate_eta_seconds
from biosmart.flashbind import FlashBindScorer
from biosmart.index import rebuild_index
from biosmart.libraries import default_libraries_root, recorded_library
from biosmart.pose_atoms import PoseAtom, write_pose_pdb
from biosmart.scoring import Candidate, FakeScorer, Scorer, ScorerFailed, candidate_smiles
from biosmart.spec import RunSpec
from biosmart.storage import (
    append_event,
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


def _scorer_cache_path(runs_root: Path) -> Path:
    override = os.environ.get("BIOSMART_SCORER_CACHE")
    if override:
        return Path(override)
    return runs_root / "scorer-cache.sqlite"


def _hold_for_stop(round_no: int) -> bool:
    """Wait at a Scoring round when a test asks, then report whether Stop arrived.

    ``BIOSMART_FAKE_SCORER_RELEASE``, when set, is a file path. Once that file
    exists the hold ends and the Run continues, so a queued Run can start after
    this one finishes.
    """
    raw = os.environ.get("BIOSMART_FAKE_SCORER_BLOCK_ROUND", "").strip()
    if raw:
        blocked = int(raw)
        if blocked < 1:
            raise ValueError("BIOSMART_FAKE_SCORER_BLOCK_ROUND must be >= 1")
        if blocked == round_no:
            release = os.environ.get("BIOSMART_FAKE_SCORER_RELEASE", "").strip()
            while not stop_requested():
                if release and Path(release).is_file():
                    return False
                time.sleep(0.05)
    return stop_requested()


def _allocated_run_id() -> str:
    raw = os.environ.get("BIOSMART_RUN_ID", "").strip()
    if not raw:
        return uuid.uuid4().hex
    if len(raw) != 32 or any(character not in "0123456789abcdef" for character in raw):
        raise ValueError("BIOSMART_RUN_ID must be 32 hex characters")
    return raw


def candidate_route(canonical_smiles: str, library_id: str) -> list[dict[str, str]]:
    """Synthesis route recorded for one Candidate from the Building-block library."""
    if not canonical_smiles or not library_id:
        raise ValueError("A Candidate route needs SMILES and a Building-block library")
    return [
        {
            "action": "Firstblock",
            "block": canonical_smiles,
            "smiles": canonical_smiles,
            "library": library_id,
        }
    ]


def _route_json(canonical_smiles: str, library_id: str) -> str:
    return json.dumps(
        candidate_route(canonical_smiles, library_id),
        separators=(",", ":"),
        allow_nan=False,
    )


_POSE_ID = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._-"


def _store_pose(run_folder: Path, candidate_id: str, pose: tuple[PoseAtom, ...] | None) -> str | None:
    """Write a Scorer's pose inside the Run folder. None when the Scorer returned none."""
    if not pose:
        return None
    if not candidate_id or any(character not in _POSE_ID for character in candidate_id):
        raise ValueError("candidate id cannot name a pose file")
    relative = Path("poses") / f"{candidate_id}.pdb"
    write_pose_pdb(run_folder / relative, pose)
    return relative.as_posix()


def _write_scorer_working_files(
    folder: Path,
    *,
    round_no: int,
    scorer_name: str,
    scorer_version: str,
    context_hash: str,
    candidates: list[dict[str, Any]],
    failure_reason: str | None = None,
) -> None:
    """Keep this Scoring round's Scorer output inside the Run folder."""
    dest = folder / "scorer" / f"round_{round_no}"
    dest.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "round_no": round_no,
        "scorer": scorer_name,
        "scorer_version": scorer_version,
        "context_hash": context_hash,
        "candidates": candidates,
    }
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    write_json(dest / "round.json", payload)


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
    run_id = _allocated_run_id()
    folder = runs_root / run_id
    folder.mkdir()
    write_json(folder / "spec.json", spec.model_dump(mode="json", exclude_none=True))
    events_path = folder / "events.jsonl"
    database_path = folder / "run.sqlite"
    init_run_database(database_path)
    _write_manifest(folder, run_id=run_id, status="running", scorer=spec.scorer, seed=spec.seed)

    _record_used_library(folder, spec, events_path, run_id)
    scorer = _open_scorer(spec, folder=folder, runs_root=runs_root, ordinal=0)
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
        finally:
            _close_scorer(scorer)
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
    if completed > _budget(spec).iterations:
        raise ValueError("Policy checkpoint is past the Budget")
    events_path = folder / "events.jsonl"
    database_path = folder / "run.sqlite"
    _write_manifest(folder, run_id=run_id, status="running", scorer=spec.scorer, seed=spec.seed)
    scorer = _open_scorer(spec, folder=folder, runs_root=runs_root, ordinal=scored)
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
        finally:
            _close_scorer(scorer)
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
    budget = _budget(spec)
    context_hash = scorer.prepare(spec.target, spec.pocket)
    if announce:
        started: dict[str, Any] = {
            "type": "run.started",
            "run_id": run_id,
            "scorer": spec.scorer,
            "seed": spec.seed,
            "iterations": budget.iterations,
            "candidates_per_iteration": budget.candidates_per_iteration,
        }
        if spec.preset is not None:
            started["preset"] = spec.preset
        append_event(events_path, started)
    total = budget.iterations * budget.candidates_per_iteration
    smiles = candidate_smiles(spec.seed, total)
    cursor = ordinal
    completed_iteration = start_iteration - 1
    completed_round = start_iteration - 1
    observed_rounds: list[tuple[int, float]] = []
    for iteration in range(start_iteration, budget.iterations + 1):
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
        count = budget.candidates_per_iteration
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
            _write_scorer_working_files(
                folder,
                round_no=round_no,
                scorer_name=scorer.name,
                scorer_version=scorer.version,
                context_hash=context_hash,
                failure_reason=str(exc),
                candidates=[
                    {
                        "candidate_id": candidate.candidate_id,
                        "canonical_smiles": candidate.canonical_smiles,
                        "status": "failed",
                        "reward": None,
                    }
                    for candidate in candidates
                ],
            )
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
                library_id=spec.library.id,
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
        machine = _scoring_machine(scorer)
        _write_scorer_working_files(
            folder,
            round_no=round_no,
            scorer_name=scorer.name,
            scorer_version=scorer.version,
            context_hash=context_hash,
            candidates=[
                {
                    "candidate_id": result.candidate_id,
                    "canonical_smiles": result.canonical_smiles,
                    "status": result.status,
                    "reward": result.reward,
                }
                for result in results
            ],
        )
        for result in results:
            route = candidate_route(result.canonical_smiles, spec.library.id)
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
                    "route": route,
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
                route_json=_route_json(result.canonical_smiles, spec.library.id),
                raw=result.raw,
                pose_ref=_store_pose(folder, result.candidate_id, result.pose),
            )
        n_ok = sum(result.status == "scored" for result in results)
        n_failed = sum(result.status == "failed" for result in results)
        observed_rounds.append((len(candidates), elapsed))
        eta_seconds = estimate_eta_seconds(
            observed_rounds,
            iterations=budget.iterations,
            candidates_per_iteration=budget.candidates_per_iteration,
            completed_iterations=iteration,
        )
        finished_round: dict[str, Any] = {
            "type": "round.finished",
            "run_id": run_id,
            "round_no": round_no,
            "iteration": iteration,
            "scorer": scorer.name,
            "n_sent": len(candidates),
            "n_ok": n_ok,
            "n_failed": n_failed,
            "secs": elapsed,
            "eta_seconds": eta_seconds,
        }
        if machine is not None:
            finished_round["machine"] = machine
        append_event(events_path, finished_round)
        insert_scoring_round(
            database_path,
            round_no=round_no,
            scorer=scorer.name,
            n_sent=len(candidates),
            n_ok=n_ok,
            n_failed=n_failed,
            secs=elapsed,
            machine=machine,
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
                "eta_seconds": eta_seconds,
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
        extras=_scorer_facts(scorer),
    )
    rebuild_index(registry, folder)
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
        extras=_scorer_facts(scorer),
    )
    rebuild_index(registry, folder)
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
    library_id: str,
) -> None:
    for candidate in candidates:
        route = candidate_route(candidate.canonical_smiles, library_id)
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
                "route": route,
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
            route_json=_route_json(candidate.canonical_smiles, library_id),
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
        extras={"pose_provider": "fabind+"} if spec.scorer == "flashbind" else None,
    )
    rebuild_index(registry, folder)
    _write_manifest(folder, run_id=run_id, status="failed", scorer=spec.scorer, seed=spec.seed)
    append_event(events_path, {"type": "run.failed", "run_id": run_id})


def _record_used_library(folder: Path, spec: RunSpec, events_path: Path, run_id: str) -> None:
    """Copy the library this Run used into the Run folder. An old one reminds."""
    recorded, reminder = recorded_library(spec.library.id, default_libraries_root())
    write_json(folder / "library.json", recorded)
    if reminder:
        append_event(events_path, {"type": "warning", "run_id": run_id, "message": reminder})


def _write_provenance(
    folder: Path,
    *,
    run_id: str,
    spec: RunSpec,
    scorer_name: str,
    scorer_version: str,
    context_hash: str,
    extras: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "seed": spec.seed,
        "scorer": scorer_name,
        "scorer_version": scorer_version,
        "gpu": None,
        "context_hash": context_hash,
        "target": {"name": spec.target.name, "structure": spec.target.structure},
        "pocket": {
            "residues": list(spec.pocket.residues),
            "reference_ligand": spec.pocket.reference_ligand,
        },
        "library": {"id": spec.library.id},
        "spec_sha256": spec_sha256(folder / "spec.json"),
    }
    if extras:
        payload.update(extras)
    write_json(folder / "provenance.json", payload)


def _budget(spec: RunSpec):
    if spec.budget is None:
        raise ValueError("A Run needs a Preset or a Budget")
    return spec.budget


def _scoring_machine(scorer: Scorer) -> str | None:
    """The machine that scored this Scoring round, when a worker did."""
    machine = getattr(scorer, "machine", None)
    if isinstance(machine, str) and machine:
        return machine
    return None


def _scorer_facts(scorer: Scorer) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    gpu = getattr(scorer, "gpu", None)
    if isinstance(gpu, str):
        facts["gpu"] = gpu
    model_loads = getattr(scorer, "model_loads", None)
    prediction_calls = getattr(scorer, "prediction_calls", None)
    interpreter = getattr(scorer, "interpreter", None)
    if scorer.name != "fake":
        if isinstance(model_loads, int):
            facts["model_loads"] = model_loads
        if isinstance(prediction_calls, int):
            facts["prediction_calls"] = prediction_calls
        if isinstance(interpreter, str):
            facts["interpreter"] = interpreter
    pose_provider = _pose_provider_name(scorer)
    if pose_provider:
        facts["pose_provider"] = pose_provider
    return facts


def _pose_provider_name(scorer: Scorer) -> str | None:
    name = getattr(scorer, "pose_provider_name", None)
    return name if isinstance(name, str) and name else None


def _close_scorer(scorer: Scorer) -> None:
    close = getattr(scorer, "close", None)
    if callable(close):
        close()


def _open_scorer(spec: RunSpec, *, folder: Path, runs_root: Path, ordinal: int) -> Scorer:
    """Boltz-2 uses one local worker. FlashBind scores on this host.

    FakeScorer uses the tailnet worker when the host was given its address.
    """
    cache = _scorer_cache_path(runs_root)
    if spec.scorer == "flashbind":
        return FlashBindScorer(cache_path=cache, work_dir=folder)
    if spec.scorer == "boltz2":
        from biosmart.boltz2_client import Boltz2WorkerScorer

        return Boltz2WorkerScorer(
            work_dir=folder / "scorer",
            cache_path=cache,
            msa=_stage_boltz_inputs(folder, spec),
            seed=spec.seed,
        )
    address = os.environ.get("BIOSMART_WORKER", "").strip()
    if address:
        return WorkerScorer(
            address,
            spec.seed,
            cache_path=cache,
            run_folder=folder,
            ordinal=ordinal,
        )
    if spec.scorer == "fake":
        return FakeScorer(spec.seed, cache_path=cache, ordinal=ordinal)
    raise ValueError(f"Unknown Scorer {spec.scorer}")


def _stage_boltz_inputs(folder: Path, spec: RunSpec) -> Path | None:
    """Copy the Target sequence, Pocket, and MSA into the Run folder."""
    target_dir = folder / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    sequence = (spec.target.sequence or "").strip()
    if sequence:
        (target_dir / "sequence.txt").write_text(sequence + "\n", encoding="utf-8")
    write_json(folder / "pocket.json", {"residues": list(spec.pocket.residues)})
    staged = target_dir / "alignment.a3m"
    if staged.is_file():
        return staged
    if not spec.target.msa:
        return None
    source = Path(spec.target.msa)
    if not source.is_file():
        raise FileNotFoundError(f"Target MSA not found: {source}")
    shutil.copyfile(source, staged)
    return staged


def _write_manifest(folder: Path, *, run_id: str, status: str, scorer: str, seed: int) -> None:
    write_json(
        folder / "run.json",
        {"run_id": run_id, "status": status, "scorer": scorer, "seed": seed},
    )


__all__ = ["execute_run", "load_spec", "resume_run"]
