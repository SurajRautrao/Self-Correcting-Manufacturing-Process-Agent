"""Validation result schema — the machine-readable output of the validator."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from scmpa.schemas.base import SCHEMA_VERSION, Identifier, StrictModel


class Violation(StrictModel):
    """A single rule finding with the evidence needed to repair it."""

    rule_id: str = Field(min_length=1)
    severity: Literal["hard", "warning"]
    message: str = Field(min_length=1)
    operation_id: Identifier | None = None
    feature_id: Identifier | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    repair_hint: str = ""
    #: False when no change using the available resources can fix this
    #: violation (e.g. no machine can perform a required operation). The
    #: repair loop uses this to route the case to human review.
    repairable: bool = True


class Coverage(StrictModel):
    """How many required features the plan addresses."""

    required_features: int = Field(ge=0)
    covered_features: int = Field(ge=0)
    missing_features: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Coverage:
        if self.covered_features > self.required_features:
            raise ValueError("covered_features cannot exceed required_features")
        if self.required_features - self.covered_features != len(self.missing_features):
            raise ValueError("missing_features must list exactly the uncovered required features")
        return self


class ValidationResult(StrictModel):
    """Outcome of validating one plan against one component and catalogue."""

    schema_version: str = SCHEMA_VERSION
    valid: bool
    hard_constraint_violations: list[Violation] = Field(default_factory=list)
    warnings: list[Violation] = Field(default_factory=list)
    coverage: Coverage
    catalogue_id: Identifier | None = None
    rule_set_version: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ValidationResult:
        if self.valid and self.hard_constraint_violations:
            raise ValueError("a result with hard violations cannot be valid")
        if not self.valid and not self.hard_constraint_violations:
            raise ValueError("an invalid result must list at least one hard violation")
        if any(v.severity != "hard" for v in self.hard_constraint_violations):
            raise ValueError("hard_constraint_violations may only contain severity='hard'")
        if any(v.severity != "warning" for v in self.warnings):
            raise ValueError("warnings may only contain severity='warning'")
        return self
