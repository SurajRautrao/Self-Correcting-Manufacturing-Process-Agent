"""Component specification: features, resources, precedence assumptions, provenance."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, PositiveFloat, model_validator

from scmpa.schemas.base import SCHEMA_VERSION, Identifier, StrictModel, find_duplicates
from scmpa.schemas.resources import Resources


class Provenance(StrictModel):
    """Where a data record came from. Required so results are never mislabelled."""

    source_type: Literal["real", "derived", "synthetic"]
    source: str = Field(min_length=1, description="Dataset, URL, script or author of the record.")
    license: str | None = None
    notes: str = ""


class Feature(StrictModel):
    """A machining feature of the component. Dimensions are optional and in millimetres."""

    feature_id: Identifier
    type: Identifier
    required: bool = True
    description: str = ""
    diameter_mm: PositiveFloat | None = None
    depth_mm: PositiveFloat | None = None
    width_mm: PositiveFloat | None = None
    length_mm: PositiveFloat | None = None
    #: If set, every listed operation type must be applied to this feature
    #: (e.g. a threaded hole needs drilling *and* tapping). If unset, any one
    #: operation the catalogue lists as suitable for the feature type suffices.
    required_operation_types: list[Identifier] | None = None

    @model_validator(mode="after")
    def _no_duplicate_required_ops(self) -> Feature:
        if self.required_operation_types is not None:
            if not self.required_operation_types:
                raise ValueError(f"feature {self.feature_id!r}: required_operation_types must not be empty if given")
            if dups := find_duplicates(self.required_operation_types):
                raise ValueError(f"feature {self.feature_id!r}: duplicate required_operation_types {dups}")
        return self


class PrecedenceRef(StrictModel):
    """One end of a precedence constraint: a feature, optionally narrowed to one operation type on it."""

    feature_id: Identifier
    operation_type: Identifier | None = None


class PrecedenceConstraint(StrictModel):
    """Component-specific ordering assumption: all work on ``before`` precedes work on ``after``.

    These are declared input assumptions for a particular demo component, not
    universal manufacturing rules. ``rationale`` is mandatory to keep that visible.
    """

    before: PrecedenceRef
    after: PrecedenceRef
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def _not_self_referential(self) -> PrecedenceConstraint:
        if self.before == self.after:
            raise ValueError(f"precedence constraint relates {self.before.feature_id!r} to itself")
        return self


class Component(StrictModel):
    """Structured description of a simplified prismatic component and its resources."""

    schema_version: str = SCHEMA_VERSION
    component_id: Identifier
    description: str = ""
    material: str = Field(min_length=1)
    features: list[Feature] = Field(min_length=1)
    resources: Resources
    precedence_constraints: list[PrecedenceConstraint] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    provenance: Provenance

    @model_validator(mode="after")
    def _references_resolve(self) -> Component:
        problems: list[str] = []
        if dups := find_duplicates(f.feature_id for f in self.features):
            problems.append(f"duplicate feature_id(s): {dups}")
        if not any(f.required for f in self.features):
            problems.append("component has no required features")
        known = {f.feature_id for f in self.features}
        for i, pc in enumerate(self.precedence_constraints):
            for end in ("before", "after"):
                fid = getattr(pc, end).feature_id
                if fid not in known:
                    problems.append(f"precedence_constraints[{i}].{end} references unknown feature {fid!r}")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def feature(self, feature_id: str) -> Feature | None:
        """Look up a feature by ID, or ``None`` if absent."""
        return next((f for f in self.features if f.feature_id == feature_id), None)

    @property
    def required_feature_ids(self) -> list[str]:
        """IDs of features that the plan must cover."""
        return [f.feature_id for f in self.features if f.required]
