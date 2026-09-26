"""Scorer interface and the CPU FakeScorer.

FakeScorer stands in for Boltz-2 and FlashBind. It never loads a model and
never touches a GPU. Candidates are drawn from a fixed catalog starting at
``seed % len(CATALOG)``. The k-th Candidate in the Run scores
``-((seed * 10 + k) % 100) / 100``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from biosmart.pose_atoms import PoseAtom, pose_from_payload
from biosmart.spec import PocketSpec, TargetSpec
from biosmart.storage import flush_scorer_cache

CATALOG: tuple[str, ...] = ("CCO", "CCN", "CC(=O)O", "c1ccccc1", "CCC", "CO")


def candidate_smiles(seed: int, count: int) -> list[str]:
    if count < 1:
        raise ValueError("count must be at least 1")
    start = seed % len(CATALOG)
    return [CATALOG[(start + ordinal) % len(CATALOG)] for ordinal in range(count)]


def fake_reward(seed: int, ordinal: int) -> float:
    if ordinal < 0:
        raise ValueError("ordinal must be >= 0")
    return -((seed * 10 + ordinal) % 100) / 100


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    iteration: int
    round_no: int
    canonical_smiles: str


@dataclass(frozen=True)
class ScoreResult:
    candidate_id: str
    canonical_smiles: str
    status: str
    reward: float | None
    failure_reason: str | None = None
    raw: dict[str, object] | None = None
    pose: tuple[PoseAtom, ...] | None = None


class Scorer(Protocol):
    name: str
    version: str

    def prepare(self, target: TargetSpec, pocket: PocketSpec) -> str:
        """Load nothing for FakeScorer. Return the scoring-context hash."""

    def score(self, round_no: int, candidates: list[Candidate]) -> list[ScoreResult]:
        """Score one Scoring round. Results stay in candidate order."""

    def flush(self) -> int:
        """Flush the Scorer cache. Returns how many entries were written."""


class ScorerFailed(Exception):
    """The Scorer could not score this Scoring round."""


class FakeScorer:
    name = "fake"
    version = "0"

    def __init__(self, seed: int, *, cache_path: Path | None = None, ordinal: int = 0) -> None:
        if ordinal < 0:
            raise ValueError("ordinal must be >= 0")
        self.seed = seed
        self._cache_path = cache_path
        self._ordinal = ordinal
        self._context_hash: str | None = None
        self._pending: list[tuple[str, float]] = []

    def prepare(self, target: TargetSpec, pocket: PocketSpec) -> str:
        if not target.name:
            raise ValueError("Target name is required")
        residues = ",".join(pocket.residues)
        self._context_hash = f"fake:{self.version}:{target.name}:{residues}"
        return self._context_hash

    def score(self, round_no: int, candidates: list[Candidate]) -> list[ScoreResult]:
        if round_no < 1:
            raise ValueError("round_no must be >= 1")
        if os.environ.get("BIOSMART_FAKE_SCORER_FAIL") == "1":
            raise ScorerFailed("FakeScorer failed")
        poses = _fake_poses()
        results: list[ScoreResult] = []
        for candidate in candidates:
            reward = fake_reward(self.seed, self._ordinal)
            self._ordinal += 1
            self._pending.append((candidate.canonical_smiles, reward))
            results.append(
                ScoreResult(
                    candidate_id=candidate.candidate_id,
                    canonical_smiles=candidate.canonical_smiles,
                    status="scored",
                    reward=reward,
                    pose=poses.get(candidate.candidate_id),
                )
            )
        return results

    def staged_entries(self) -> list[tuple[str, float]]:
        """Cache rows waiting for flush. The list is a copy."""
        return list(self._pending)

    def flush(self) -> int:
        if self._cache_path is None or self._context_hash is None:
            written = len(self._pending)
            self._pending.clear()
            return written
        written = flush_scorer_cache(
            self._cache_path,
            scorer=self.name,
            scorer_version=self.version,
            context_hash=self._context_hash,
            entries=self._pending,
        )
        self._pending.clear()
        return written


def _fake_poses() -> dict[str, tuple[PoseAtom, ...]]:
    """Poses FakeScorer was given. Unset means this Scorer returned none."""
    raw_path = os.environ.get("BIOSMART_FAKE_SCORER_POSE", "").strip()
    if not raw_path:
        return {}
    path = Path(raw_path)
    if not path.is_file():
        raise ScorerFailed("FakeScorer pose file is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScorerFailed("FakeScorer pose file is invalid") from exc
    if not isinstance(payload, dict):
        raise ScorerFailed("FakeScorer pose file is invalid")
    poses: dict[str, tuple[PoseAtom, ...]] = {}
    for candidate_id, atoms in payload.items():
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ScorerFailed("FakeScorer pose file is invalid")
        try:
            parsed = pose_from_payload(atoms)
        except ValueError as exc:
            raise ScorerFailed("FakeScorer pose file is invalid") from exc
        if not parsed:
            raise ScorerFailed("FakeScorer pose file is invalid")
        poses[candidate_id] = parsed
    return poses
