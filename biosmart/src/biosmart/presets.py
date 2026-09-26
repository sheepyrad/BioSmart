"""Named Budgets. Quick, Standard, and Thorough."""

from __future__ import annotations

from typing import Literal

PresetName = Literal["quick", "standard", "thorough"]

# Iterations × Candidates per Iteration. Time estimates are not stored here.
PRESET_BUDGETS: dict[PresetName, tuple[int, int]] = {
    "quick": (100, 16),
    "standard": (1000, 32),
    "thorough": (2000, 64),
}


def preset_budget(name: PresetName) -> tuple[int, int]:
    try:
        iterations, candidates = PRESET_BUDGETS[name]
    except KeyError as exc:
        known = ", ".join(PRESET_BUDGETS)
        raise ValueError(f"Unknown Preset {name!r}. Known Presets: {known}") from exc
    return iterations, candidates
