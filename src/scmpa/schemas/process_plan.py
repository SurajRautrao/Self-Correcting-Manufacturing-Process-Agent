"""Process plan schema — the structured output of the planner / repair agent.

Design note: this schema enforces *structure* only (fields present, correct
types, unique operation IDs, well-formed precedence pairs). Whether the IDs
refer to real machines/tools/features, whether operation types are in the
catalogue, whether durations are sane and whether the order is consistent are
deliberately left to the deterministic validator (rules R1–R12), so that those
problems are reported as structured, repairable violations rather than as
opaque parse failures.

The order of ``operations`` is the proposed execution sequence.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from scmpa.schemas.base import SCHEMA_VERSION, Identifier, StrictModel, find_duplicates
from scmpa.schemas.component import Provenance

#: A precedence edge ``(predecessor_operation_id, successor_operation_id)``.
PrecedenceEdge = Annotated[list[Identifier], Field(min_length=2, max_length=2)]


class Operation(StrictModel):
    """One planned operation. ``duration_min`` is an estimate in minutes."""

    operation_id: Identifier
    type: Identifier
    target_features: list[Identifier]
    machine_id: Identifier
    tool_id: Identifier
    duration_min: float
    notes: str = ""


class ProcessPlan(StrictModel):
    """A candidate process plan for one component."""

    schema_version: str = SCHEMA_VERSION
    plan_id: Identifier
    component_id: Identifier
    operations: list[Operation]
    precedence: list[PrecedenceEdge] = Field(default_factory=list)
    explanation: str
    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def _unique_operation_ids(self) -> ProcessPlan:
        if dups := find_duplicates(op.operation_id for op in self.operations):
            raise ValueError(f"duplicate operation_id(s): {dups}")
        return self

    @property
    def sequence(self) -> list[str]:
        """Operation IDs in proposed execution order."""
        return [op.operation_id for op in self.operations]
