"""Sanity rules: R10 (duplicates), R11 (durations), R12 (completeness)."""

from __future__ import annotations

import math

from scmpa.schemas import ProcessPlan, Violation
from scmpa.validation.context import ValidationContext

R10 = "R10_DUPLICATE_OPERATION"
R11 = "R11_DURATION"
R12 = "R12_COMPLETENESS"


def check_duplicates(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R10: flag the same operation type applied more than once to the same feature.

    Different operation types on one feature (e.g. drilling then tapping) are
    not duplicates. Severity and exempt types come from the config.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for op in plan.operations:
        for fid in op.target_features:
            groups.setdefault((op.type, fid), []).append(op.operation_id)
    out = []
    allowed = set(ctx.config.allowed_duplicate_operation_types)
    for (op_type, fid), op_ids in groups.items():
        if len(op_ids) < 2 or op_type in allowed:
            continue
        out.append(
            Violation(
                rule_id=R10,
                severity=ctx.config.duplicate_severity,
                operation_id=op_ids[1],
                feature_id=fid,
                message=f"Feature {fid!r} receives {op_type!r} {len(op_ids)} times ({op_ids}).",
                evidence={"operation_type": op_type, "operation_ids": op_ids},
                repair_hint=f"Remove the redundant operation(s), keeping {op_ids[0]}, unless repeated passes are intended.",
            )
        )
    return out


def check_durations(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R11: durations are finite and positive (hard) and within the configured demo bound."""
    out = []
    upper = ctx.config.max_duration_min
    for op in plan.operations:
        d = op.duration_min
        if not math.isfinite(d) or d <= 0:
            out.append(
                Violation(
                    rule_id=R11,
                    severity="hard",
                    operation_id=op.operation_id,
                    message=f"Duration {d} min is not a positive finite number.",
                    evidence={"duration_min": d if math.isfinite(d) else str(d)},
                    repair_hint="Provide a positive duration estimate in minutes.",
                )
            )
        elif d > upper:
            out.append(
                Violation(
                    rule_id=R11,
                    severity=ctx.config.duration_bound_severity,
                    operation_id=op.operation_id,
                    message=f"Duration {d} min exceeds the demo bound of {upper} min.",
                    evidence={"duration_min": d, "max_duration_min": upper},
                    repair_hint="Check the estimate; split the operation or correct the duration.",
                )
            )
    return out


def check_completeness(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R12: plan-level content is present and refers to this component.

    Missing *fields* are already rejected by the plan schema; this rule checks
    that required content is non-empty and consistent.
    """
    out = []

    def add(message: str, evidence: dict, hint: str, operation_id: str | None = None) -> None:
        out.append(
            Violation(rule_id=R12, severity="hard", operation_id=operation_id, message=message, evidence=evidence, repair_hint=hint)
        )

    if plan.component_id != ctx.component.component_id:
        add(
            f"Plan is for component {plan.component_id!r}, not {ctx.component.component_id!r}.",
            {"plan_component_id": plan.component_id, "expected_component_id": ctx.component.component_id},
            "Set component_id to the component being planned.",
        )
    if not plan.operations:
        add("Plan contains no operations.", {}, "Add operations covering every required feature.")
    for op in plan.operations:
        if not op.target_features:
            add(
                f"Operation {op.operation_id} has no target features.",
                {"field": "target_features"},
                "List the feature(s) this operation produces.",
                op.operation_id,
            )
    if not plan.explanation.strip():
        add("Plan explanation is empty.", {"field": "explanation"}, "Provide a short explanation of the sequence.")
    return out
