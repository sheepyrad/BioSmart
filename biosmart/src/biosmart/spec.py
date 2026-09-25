"""Run spec owned by the engine."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Budget(BaseModel):
    """How much a Run may spend: Iterations × Candidates per Iteration."""

    model_config = ConfigDict(extra="forbid")

    iterations: int = Field(ge=1)
    candidates_per_iteration: int = Field(ge=1)


class TargetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)


class PocketSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    residues: list[str] = Field(default_factory=list)


class LibrarySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)


class RunSpec(BaseModel):
    """One optimisation job: one Target, one Scorer, one Library, one Budget."""

    model_config = ConfigDict(extra="forbid")

    scorer: Literal["fake"]
    seed: int
    budget: Budget
    target: TargetSpec
    pocket: PocketSpec
    library: LibrarySpec
