"""Typed data contracts for components, resources, plans and validation results."""

from scmpa.schemas.base import SCHEMA_VERSION
from scmpa.schemas.component import Component, Feature, PrecedenceConstraint, PrecedenceRef, Provenance
from scmpa.schemas.process_plan import Operation, ProcessPlan
from scmpa.schemas.resources import Catalogue, Machine, Resources, Tool
from scmpa.schemas.validation import Coverage, ValidationResult, Violation

__all__ = [
    "SCHEMA_VERSION",
    "Catalogue",
    "Component",
    "Coverage",
    "Feature",
    "Machine",
    "Operation",
    "PrecedenceConstraint",
    "PrecedenceRef",
    "ProcessPlan",
    "Provenance",
    "Resources",
    "Tool",
    "ValidationResult",
    "Violation",
]
