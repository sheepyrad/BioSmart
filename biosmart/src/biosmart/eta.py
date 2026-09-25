"""ETA from recorded Scoring-round durations.

No duration is hard-coded. With no recorded rounds the estimate is unknown.
"""

from __future__ import annotations


def estimate_eta_seconds(
    rounds: list[tuple[int, float]],
    *,
    iterations: int,
    candidates_per_iteration: int,
    completed_iterations: int,
) -> float | None:
    """Remaining seconds from observed Scoring-round durations.

    ``rounds`` is ``(n_sent, secs)`` for each recorded Scoring round.
    """
    if iterations < 1 or candidates_per_iteration < 1:
        raise ValueError("Budget must be at least one Iteration and one Candidate")
    if completed_iterations < 0 or completed_iterations > iterations:
        raise ValueError("completed iterations are outside the Budget")
    if not rounds:
        return None
    sent = 0
    elapsed = 0.0
    for n_sent, secs in rounds:
        if n_sent < 1:
            raise ValueError("a Scoring round must send at least one Candidate")
        if secs < 0:
            raise ValueError("Scoring-round duration must be >= 0")
        sent += n_sent
        elapsed += secs
    remaining = (iterations - completed_iterations) * candidates_per_iteration
    return (elapsed / sent) * remaining
