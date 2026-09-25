"""JSON-lines FakeScorer worker for the protocol test. Not used by a Run."""

from __future__ import annotations

import sys
from typing import Any

from biosmart.jsonl import serve
from biosmart.scoring import Candidate, FakeScorer
from biosmart.spec import PocketSpec, TargetSpec


class _Handler:
    def __init__(self) -> None:
        self._scorer = FakeScorer(seed=0)
        self.prepares = 0

    def prepare(self, request: dict[str, Any]) -> dict[str, Any]:
        self.prepares += 1
        target = TargetSpec.model_validate(request["target"])
        pocket = PocketSpec.model_validate(request["pocket"])
        digest = self._scorer.prepare(target, pocket)
        return {"context_hash": digest, "prepares": self.prepares}

    def score(self, request: dict[str, Any]) -> dict[str, Any]:
        candidates = [
            Candidate(
                candidate_id=str(item["candidate_id"]),
                iteration=int(item["iteration"]),
                round_no=int(item["round_no"]),
                canonical_smiles=str(item["canonical_smiles"]),
            )
            for item in request["candidates"]
        ]
        results = self._scorer.score(int(request["round_no"]), candidates)
        return {
            "results": [
                {
                    "candidate_id": result.candidate_id,
                    "canonical_smiles": result.canonical_smiles,
                    "status": result.status,
                    "reward": result.reward,
                    "failure_reason": result.failure_reason,
                }
                for result in results
            ],
            "prepares": self.prepares,
        }

    def flush(self, request: dict[str, Any]) -> dict[str, Any]:
        del request
        return {"written": self._scorer.flush(), "prepares": self.prepares}


def main() -> None:
    protocol = sys.stdout
    sys.stdout = sys.stderr
    serve(_Handler(), protocol)


if __name__ == "__main__":
    main()
