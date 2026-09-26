"""Run spec owned by the engine."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.functional_validators import BeforeValidator

SELECTABLE_SCORERS = ("fake", "flashbind")


def _selectable_scorer(value: object) -> object:
    """FABind+ is a Pose provider. UniDock and Vina are not Scorers."""
    if not isinstance(value, str):
        return value
    key = value.strip().lower().replace(" ", "").replace("_", "")
    if key in {"fabind", "fabind+", "fabindplus"}:
        raise ValueError("FABind+ cannot be selected as a Scorer")
    if key in {"unidock", "vina", "autodockvina"}:
        raise ValueError("UniDock and Vina are not Scorers")
    return value


ScorerName = Annotated[Literal["fake", "flashbind"], BeforeValidator(_selectable_scorer)]


class Budget(BaseModel):
    """How much a Run may spend: Iterations × Candidates per Iteration."""

    model_config = ConfigDict(extra="forbid")

    iterations: int = Field(ge=1)
    candidates_per_iteration: int = Field(ge=1)


class TargetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    structure: str | None = None


class PocketSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    residues: list[str] = Field(default_factory=list)
    reference_ligand: str | None = None


class LibrarySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)


class RunSpec(BaseModel):
    """One Run against one Target with one Scorer, one Building-block library, and one Budget."""

    model_config = ConfigDict(extra="forbid")

    scorer: ScorerName
    seed: int
    budget: Budget
    target: TargetSpec
    pocket: PocketSpec
    library: LibrarySpec

    @model_validator(mode="after")
    def _pocket_matches_scorer(self) -> Self:
        if self.scorer != "flashbind":
            return self
        ligand = self.pocket.reference_ligand
        if not isinstance(ligand, str) or not ligand.strip() or self.pocket.residues:
            raise ValueError("The Pocket for FlashBind is a Reference ligand")
        structure = self.target.structure
        if not isinstance(structure, str) or not structure.strip():
            raise ValueError("FlashBind requires a Target structure")
        return self
