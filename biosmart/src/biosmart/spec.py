"""Run spec owned by the engine."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.functional_validators import BeforeValidator

from biosmart.presets import PRESET_BUDGETS, PresetName

SELECTABLE_SCORERS = ("fake", "flashbind", "boltz2")

_RESIDUE = re.compile(r"^[A-Za-z0-9]+:[0-9]+$")


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


ScorerName = Annotated[Literal["fake", "flashbind", "boltz2"], BeforeValidator(_selectable_scorer)]


class Budget(BaseModel):
    """How much a Run may spend: Iterations × Candidates per Iteration."""

    model_config = ConfigDict(extra="forbid")

    iterations: int = Field(ge=1)
    candidates_per_iteration: int = Field(ge=1)


class TargetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    structure: str | None = None
    sequence: str | None = None
    msa: str | None = None


class PocketSpec(BaseModel):
    """Boltz-2 takes selected residues. FlashBind takes a Reference ligand."""

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
    budget: Budget | None = None
    preset: PresetName | None = None
    target: TargetSpec
    pocket: PocketSpec
    library: LibrarySpec

    @model_validator(mode="after")
    def resolve_preset_and_pocket(self) -> Self:
        if self.preset is not None:
            iterations, candidates = PRESET_BUDGETS[self.preset]
            preset_budget = Budget(iterations=iterations, candidates_per_iteration=candidates)
            if self.budget is not None and self.budget != preset_budget:
                raise ValueError(
                    f"Preset {self.preset} is {iterations}×{candidates} "
                    "and does not match the Budget"
                )
            self.budget = preset_budget
        if self.budget is None:
            raise ValueError("A Run needs a Preset or a Budget")
        if self.scorer == "boltz2":
            sequence = (self.target.sequence or "").strip()
            if not sequence:
                raise ValueError("Boltz-2 Target needs a sequence")
            self.target.sequence = sequence
            if not self.pocket.residues:
                raise ValueError("Boltz-2 Pocket is selected residues")
            invalid = [residue for residue in self.pocket.residues if _RESIDUE.fullmatch(residue) is None]
            if invalid:
                raise ValueError(
                    "Boltz-2 Pocket residues must be CHAIN:NUMBER, got " + ", ".join(invalid)
                )
        return self

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
