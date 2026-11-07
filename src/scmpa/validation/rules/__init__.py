"""Registry of MVP validator rules R1–R12 (order = evaluation and report order)."""

from scmpa.validation.rules.base import Rule
from scmpa.validation.rules.coverage import R6, check_feature_coverage
from scmpa.validation.rules.precedence import R8, R9, check_precedence_order, check_precedence_validity
from scmpa.validation.rules.references import (
    R1,
    R2,
    R3,
    R4,
    R5,
    R7,
    check_feature_references,
    check_machine_capability,
    check_machine_exists,
    check_operation_type,
    check_tool_compatibility,
    check_tool_exists,
)
from scmpa.validation.rules.sanity import R10, R11, R12, check_completeness, check_duplicates, check_durations

#: Bump when rule semantics change, so recorded results stay interpretable.
#: 1.1: R3/R5 violations on operations not needed for coverage are repairable (by removal).
#: 1.2: preparatory operations (catalogue ``preparatory_operation_types``, e.g. spot drilling) never
#:      cover a feature on their own (R6), so a spot-drill-only hole is a coverage violation.
#:      R3/R5 removability compares each feature's missing types, so a still-required step is never "removable".
RULE_SET_VERSION = "1.2"

ALL_RULES: tuple[Rule, ...] = (
    Rule(R1, "Valid operation type", "Every operation type belongs to the operation catalogue.", check_operation_type),
    Rule(R2, "Valid machine", "Every operation references an available machine.", check_machine_exists),
    Rule(R3, "Machine capability", "The machine declares the operation type as a capability.", check_machine_capability),
    Rule(R4, "Tool exists", "Every operation references an available tool.", check_tool_exists),
    Rule(R5, "Tool compatibility", "Tool type is compatible with the operation type per the catalogue map.", check_tool_compatibility),
    Rule(R6, "Feature coverage", "Operations suit their features; every required feature is covered.", check_feature_coverage),
    Rule(R7, "Valid feature references", "Each operation target is a feature of the component.", check_feature_references),
    Rule(R8, "Precedence validity", "Precedence edges reference existing operations and are acyclic.", check_precedence_validity),
    Rule(R9, "Precedence order", "The sequence respects plan edges and component precedence constraints.", check_precedence_order),
    Rule(R10, "Duplicate handling", "The same operation type is not repeated on a feature unless allowed.", check_duplicates),
    Rule(R11, "Duration sanity", "Durations are positive, finite and within demo bounds.", check_durations),
    Rule(R12, "Completeness", "Plan content is non-empty and refers to this component.", check_completeness),
)

RULES_BY_ID = {r.rule_id: r for r in ALL_RULES}

__all__ = ["ALL_RULES", "RULES_BY_ID", "RULE_SET_VERSION", "Rule"] + [
    "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12",
]
