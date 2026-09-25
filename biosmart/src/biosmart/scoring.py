"""Scorer interface and the CPU FakeScorer.

FakeScorer stands in for Boltz-2 and FlashBind. It never loads a model and
never touches a GPU. Candidates are drawn from a fixed catalog starting at
``seed % len(CATALOG)``. The k-th Candidate in the Run scores
``-((seed * 10 + k) % 100) / 100``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from biosmart.spec import PocketSpec, TargetSpec

CATALOG: tuple[str, ...] = ("CCO", "CCN", "CC(=O)O", "c1ccccc1", "CCC", "CO")


def sample_smiles(seed: int, count: int) -> list[str]:
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


class Scorer(Protocol):
    name: str
    version: str

    def prepare(self, target: TargetSpec, pocket: PocketSpec) -> str:
        """Load nothing for FakeScorer. Return the scoring-context hash."""

    def score(self, round_no: int, candidates: list[Candidate]) -> list[ScoreResult]:
        """Score one Scoring round. Results stay in candidate order."""

    def flush(self) -> None:
        """Flush any Scorer cache. FakeScorer keeps none."""


class FakeScorer:
    name = "fake"
    version = "0"

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._ordinal = 0

    def prepare(self, target: TargetSpec, pocket: PocketSpec) -> str:
        if not target.name:
            raise ValueError("Target name is required")
        residues = ",".join(pocket.residues)
        return f"fake:{self.version}:{target.name}:{residues}"

    def score(self, round_no: int, candidates: list[Candidate]) -> list[ScoreResult]:
        if round_no < 1:
            raise ValueError("round_no must be >= 1")
        results: list[ScoreResult] = []
        for candidate in candidates:
            reward = fake_reward(self.seed, self._ordinal)
            self._ordinal += 1
            results.append(
                ScoreResult(
                    candidate_id=candidate.candidate_id,
                    canonical_smiles=candidate.canonical_smiles,
                    status="scored",
                    reward=reward,
                )
            )
        return results

    def flush(self) -> None:
        return None
