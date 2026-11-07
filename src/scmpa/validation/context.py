"""Validation configuration and the read-only context passed to every rule."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, PositiveFloat

from scmpa.schemas import Catalogue, Component, Feature, Machine, Tool
from scmpa.schemas.base import StrictModel

Severity = Literal["hard", "warning"]


class ValidationConfig(StrictModel):
    """Tunable parts of the rule set. Defaults are documented in docs/constraint_catalogue.md."""

    #: R10: severity of a repeated (operation type, feature) pair.
    duplicate_severity: Severity = "warning"
    #: R10: operation types that may legitimately repeat on one feature (e.g. roughing + finishing passes).
    allowed_duplicate_operation_types: list[str] = Field(default_factory=list)
    #: R11: upper demo bound for a single operation's estimated duration, in minutes.
    max_duration_min: PositiveFloat = 240.0
    #: R11: severity when a duration exceeds ``max_duration_min``. Non-positive or
    #: non-finite durations are always hard violations.
    duration_bound_severity: Severity = "warning"


class ValidationContext:
    """Component, catalogue and config, plus precomputed lookups. Rules must treat it as read-only."""

    def __init__(self, component: Component, catalogue: Catalogue, config: ValidationConfig | None = None) -> None:
        self.component = component
        self.catalogue = catalogue
        self.config = config or ValidationConfig()
        self.machines: dict[str, Machine] = {m.machine_id: m for m in component.resources.machines}
        self.tools: dict[str, Tool] = {t.tool_id: t for t in component.resources.tools}
        self.features: dict[str, Feature] = {f.feature_id: f for f in component.features}
        self.operation_types: set[str] = set(catalogue.operation_types)

    def suitable_operation_types(self, feature: Feature) -> list[str]:
        """Operation types the catalogue considers suitable for this feature's type."""
        return list(self.catalogue.feature_types.get(feature.type, []))

    def capable_machines(self, operation_type: str) -> list[str]:
        """IDs of available machines declaring ``operation_type`` as a capability."""
        return [m.machine_id for m in self.component.resources.machines if operation_type in m.capabilities]

    def compatible_tools(self, operation_type: str) -> list[str]:
        """IDs of available tools whose type is compatible with ``operation_type``."""
        allowed = set(self.catalogue.tool_compatibility.get(operation_type, []))
        return [t.tool_id for t in self.component.resources.tools if t.type in allowed]

    def resource_options(self, operation_type: str) -> list[dict[str, str]]:
        """All (machine, tool) pairs from the available resources that can perform ``operation_type``."""
        return [
            {"machine_id": m, "tool_id": t}
            for m in self.capable_machines(operation_type)
            for t in self.compatible_tools(operation_type)
        ]
