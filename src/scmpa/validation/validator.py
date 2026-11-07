"""Deterministic plan validator. No LLM, no network, no randomness."""

from __future__ import annotations

from collections.abc import Sequence

from scmpa.schemas import Catalogue, Component, Coverage, ProcessPlan, ValidationResult, Violation
from scmpa.validation.context import ValidationConfig, ValidationContext
from scmpa.validation.rules import ALL_RULES, RULE_SET_VERSION, Rule
from scmpa.validation.rules.coverage import uncovered_required_features


def validate_plan(
    plan: ProcessPlan,
    component: Component,
    catalogue: Catalogue,
    config: ValidationConfig | None = None,
    rules: Sequence[Rule] = ALL_RULES,
) -> ValidationResult:
    """Check ``plan`` against every rule and return a structured result.

    The plan is valid iff no rule reports a ``hard`` violation. Warnings never
    affect validity. Violations are reported in rule order, then plan order.
    """
    ctx = ValidationContext(component, catalogue, config)
    findings: list[Violation] = []
    for rule in rules:
        findings.extend(rule.check(plan, ctx))
    hard = [v for v in findings if v.severity == "hard"]
    warnings = [v for v in findings if v.severity == "warning"]

    required = component.required_feature_ids
    missing = uncovered_required_features(plan, ctx)
    coverage = Coverage(
        required_features=len(required),
        covered_features=len(required) - len(missing),
        missing_features=missing,
    )
    return ValidationResult(
        valid=not hard,
        hard_constraint_violations=hard,
        warnings=warnings,
        coverage=coverage,
        catalogue_id=catalogue.catalogue_id,
        rule_set_version=RULE_SET_VERSION,
    )
