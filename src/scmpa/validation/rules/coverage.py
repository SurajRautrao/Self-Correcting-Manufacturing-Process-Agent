"""R6 — feature coverage, and the coverage computation used in validation results.

Coverage semantics (see docs/constraint_catalogue.md):

* An operation *contributes* to a feature if it targets the feature and its type
  is in the catalogue's suitable list for that feature type. Machine/tool
  problems do not remove a contribution; they are reported by R2–R5.
* A required feature with ``required_operation_types`` is covered when **all**
  of those types are applied to it; otherwise it is covered when **any** one
  suitable operation is applied.
* An operation whose type is unsuitable for a feature it targets is itself an
  R6 violation (e.g. drilling a planar face).
"""

from __future__ import annotations

from scmpa.schemas import Feature, ProcessPlan, Violation
from scmpa.validation.context import ValidationContext

R6 = "R6_FEATURE_COVERAGE"


def applied_operation_types(plan: ProcessPlan, ctx: ValidationContext) -> dict[str, set[str]]:
    """Map feature ID -> suitable operation types the plan applies to it."""
    applied: dict[str, set[str]] = {fid: set() for fid in ctx.features}
    for op in plan.operations:
        for fid in op.target_features:
            feature = ctx.features.get(fid)
            if feature is not None and op.type in ctx.suitable_operation_types(feature):
                applied[fid].add(op.type)
    return applied


def missing_operation_types(feature: Feature, applied: set[str], ctx: ValidationContext) -> tuple[str, list[str]]:
    """Return ``(requirement, missing)`` where requirement is ``"all_of"`` or ``"any_of"``. Empty ``missing`` = covered."""
    if feature.required_operation_types:
        return "all_of", [t for t in feature.required_operation_types if t not in applied]
    suitable = ctx.suitable_operation_types(feature)
    return "any_of", ([] if applied & set(suitable) else suitable)


def uncovered_required_features(plan: ProcessPlan, ctx: ValidationContext) -> list[str]:
    """IDs of required features (component order) not covered by the plan."""
    applied = applied_operation_types(plan, ctx)
    return [
        f.feature_id
        for f in ctx.component.features
        if f.required and missing_operation_types(f, applied[f.feature_id], ctx)[1]
    ]


def check_feature_coverage(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R6: unsuitable operation/feature pairings, and required features not (fully) covered."""
    out: list[Violation] = []

    for op in plan.operations:
        if op.type not in ctx.operation_types:
            continue  # reported by R1
        for fid in op.target_features:
            feature = ctx.features.get(fid)
            if feature is None:
                continue  # reported by R7
            suitable = ctx.suitable_operation_types(feature)
            if op.type not in suitable:
                out.append(
                    Violation(
                        rule_id=R6,
                        severity="hard",
                        operation_id=op.operation_id,
                        feature_id=fid,
                        message=f"Operation type {op.type!r} is not suitable for feature {fid!r} ({feature.type}).",
                        evidence={"operation_type": op.type, "feature_type": feature.type, "suitable_operation_types": suitable},
                        repair_hint=f"Retarget the operation or change its type to one of {suitable}.",
                    )
                )

    applied = applied_operation_types(plan, ctx)
    for feature in ctx.component.features:
        if not feature.required:
            continue
        requirement, missing = missing_operation_types(feature, applied[feature.feature_id], ctx)
        if not missing:
            continue
        options = {t: ctx.resource_options(t) for t in missing}
        producible = [t for t in missing if options[t]]
        repairable = len(producible) == len(missing) if requirement == "all_of" else bool(producible)
        if requirement == "all_of":
            message = f"Required feature {feature.feature_id!r} is missing operation(s) {missing}."
        else:
            message = f"Required feature {feature.feature_id!r} is not addressed by any suitable operation (one of {missing})."
        if repairable:
            examples = "; ".join(
                f"{t} on {options[t][0]['machine_id']} with {options[t][0]['tool_id']}"
                for t in (missing if requirement == "all_of" else producible[:1])
            )
            hint = f"Add operation(s) targeting {feature.feature_id}: {examples}."
        else:
            blocked = [t for t in missing if not options[t]]
            hint = (
                f"No available machine/tool combination can perform {blocked}; "
                "human review needed (add resources or revise the requirement)."
            )
        out.append(
            Violation(
                rule_id=R6,
                severity="hard",
                feature_id=feature.feature_id,
                message=message,
                evidence={
                    "feature_type": feature.type,
                    "requirement": requirement,
                    "missing_operation_types": missing,
                    "applied_operation_types": sorted(applied[feature.feature_id]),
                    "resource_options": options,
                },
                repair_hint=hint,
                repairable=repairable,
            )
        )
    return out
