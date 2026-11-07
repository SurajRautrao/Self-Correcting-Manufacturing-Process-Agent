"""Manufacturing resources and the operation/tool catalogue.

The *catalogue* is the rule-set vocabulary: which operation, tool and feature
types exist, which tool types are compatible with which operation, and which
operations are considered suitable for a feature type. It is versioned data,
not code, so that the assumptions it encodes are visible and reviewable.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from scmpa.schemas.base import SCHEMA_VERSION, Identifier, StrictModel, find_duplicates


class Machine(StrictModel):
    """A machine and the operation types it is declared capable of."""

    machine_id: Identifier
    description: str = ""
    capabilities: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_capabilities(self) -> Machine:
        dups = find_duplicates(self.capabilities)
        if dups:
            raise ValueError(f"machine {self.machine_id!r} lists duplicate capabilities: {dups}")
        return self


class Tool(StrictModel):
    """A tool instance. Only its type is modelled in the MVP (no diameter/length/wear)."""

    tool_id: Identifier
    type: Identifier
    description: str = ""


class Resources(StrictModel):
    """Machines and tools available for one component."""

    machines: list[Machine] = Field(min_length=1)
    tools: list[Tool] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Resources:
        problems = []
        if dups := find_duplicates(m.machine_id for m in self.machines):
            problems.append(f"duplicate machine_id(s): {dups}")
        if dups := find_duplicates(t.tool_id for t in self.tools):
            problems.append(f"duplicate tool_id(s): {dups}")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def machine(self, machine_id: str) -> Machine | None:
        """Look up a machine by ID, or ``None`` if absent."""
        return next((m for m in self.machines if m.machine_id == machine_id), None)

    def tool(self, tool_id: str) -> Tool | None:
        """Look up a tool by ID, or ``None`` if absent."""
        return next((t for t in self.tools if t.tool_id == tool_id), None)


class Catalogue(StrictModel):
    """Versioned vocabulary and compatibility maps used by input checks and the validator."""

    schema_version: str = SCHEMA_VERSION
    catalogue_id: Identifier
    description: str = ""
    operation_types: list[Identifier] = Field(min_length=1)
    tool_types: list[Identifier] = Field(min_length=1)
    #: feature type -> operation types considered suitable to (help) produce it
    feature_types: dict[Identifier, list[Identifier]]
    #: operation type -> tool types allowed for it
    tool_compatibility: dict[Identifier, list[Identifier]]
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _internally_consistent(self) -> Catalogue:
        problems: list[str] = []
        ops, tools = set(self.operation_types), set(self.tool_types)
        if dups := find_duplicates(self.operation_types):
            problems.append(f"duplicate operation_types: {dups}")
        if dups := find_duplicates(self.tool_types):
            problems.append(f"duplicate tool_types: {dups}")
        for feature_type, suitable in self.feature_types.items():
            if not suitable:
                problems.append(f"feature type {feature_type!r} has no suitable operations")
            if unknown := sorted(set(suitable) - ops):
                problems.append(f"feature type {feature_type!r} references unknown operation types {unknown}")
        if missing := sorted(ops - set(self.tool_compatibility)):
            problems.append(f"operation types without a tool_compatibility entry: {missing}")
        for op, allowed in self.tool_compatibility.items():
            if op not in ops:
                problems.append(f"tool_compatibility references unknown operation type {op!r}")
            if not allowed:
                problems.append(f"operation type {op!r} has no compatible tool types")
            if unknown := sorted(set(allowed) - tools):
                problems.append(f"operation type {op!r} references unknown tool types {unknown}")
        if problems:
            raise ValueError("catalogue is inconsistent: " + "; ".join(problems))
        return self
