"""Precedence rules: R8 (edge validity, acyclicity) and R9 (sequence respects order).

The sequence is the order of ``plan.operations``. R9 checks it against two
sources of ordering: the plan's own declared precedence edges, and the
component's ``precedence_constraints`` (declared, component-specific
assumptions — never a built-in universal rule).
"""

from __future__ import annotations

from scmpa.graph import find_cycle
from scmpa.schemas import Operation, PrecedenceRef, ProcessPlan, Violation
from scmpa.validation.context import ValidationContext

R8 = "R8_PRECEDENCE_VALIDITY"
R9 = "R9_PRECEDENCE_ORDER"


def check_precedence_validity(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R8: precedence edges reference existing operations and form an acyclic graph.

    Only one cycle is reported per validation; after repair, revalidation
    reports the next one if any remain.
    """
    out: list[Violation] = []
    known = set(plan.sequence)
    graph: dict[str, list[str]] = {}
    for i, (a, b) in enumerate(plan.precedence):
        unknown = [x for x in (a, b) if x not in known]
        if unknown:
            out.append(
                Violation(
                    rule_id=R8,
                    severity="hard",
                    operation_id=unknown[0],
                    message=f"Precedence edge {i} [{a!r}, {b!r}] references unknown operation(s) {unknown}.",
                    evidence={"edge_index": i, "edge": [a, b], "unknown_operations": unknown},
                    repair_hint="Remove the edge or reference operations that exist in the plan.",
                )
            )
            continue
        graph.setdefault(a, []).append(b)
    if cycle := find_cycle(graph):
        out.append(
            Violation(
                rule_id=R8,
                severity="hard",
                operation_id=cycle[0],
                message=f"Precedence edges contain a cycle: {' -> '.join(cycle)}.",
                evidence={"cycle": cycle},
                repair_hint="Remove or reverse at least one edge in the cycle so that a valid order exists.",
            )
        )
    return out


def _matches(op: Operation, ref: PrecedenceRef) -> bool:
    return ref.feature_id in op.target_features and (ref.operation_type is None or op.type == ref.operation_type)


def _describe(ref: PrecedenceRef) -> str:
    return f"{ref.operation_type} on {ref.feature_id}" if ref.operation_type else f"all work on {ref.feature_id}"


def check_precedence_order(plan: ProcessPlan, ctx: ValidationContext) -> list[Violation]:
    """R9: the operation sequence respects plan precedence edges and component precedence constraints."""
    out: list[Violation] = []
    pos = {op_id: i for i, op_id in enumerate(plan.sequence)}

    for i, (a, b) in enumerate(plan.precedence):
        if a not in pos or b not in pos or a == b:
            continue  # reported by R8
        if pos[a] > pos[b]:
            out.append(
                Violation(
                    rule_id=R9,
                    severity="hard",
                    operation_id=b,
                    message=f"Declared precedence {a} -> {b} is violated: {b} is sequenced before {a}.",
                    evidence={"source": "plan_precedence", "edge_index": i, "edge": [a, b], "positions": {a: pos[a], b: pos[b]}},
                    repair_hint=f"Move {a} before {b} in the operation sequence, or remove the edge if it is not required.",
                )
            )

    for ci, pc in enumerate(ctx.component.precedence_constraints):
        before_ops = [op for op in plan.operations if _matches(op, pc.before)]
        after_ops = [op for op in plan.operations if _matches(op, pc.after)]
        for x in before_ops:
            for y in after_ops:
                if x.operation_id == y.operation_id:
                    message = (
                        f"Operation {x.operation_id} performs both sides of a component precedence constraint "
                        f"({_describe(pc.before)} must precede {_describe(pc.after)})."
                    )
                    hint = f"Split {x.operation_id} so that {_describe(pc.before)} is done in an earlier operation."
                elif pos[x.operation_id] > pos[y.operation_id]:
                    message = (
                        f"Component constraint violated: {_describe(pc.before)} must precede {_describe(pc.after)}, "
                        f"but {y.operation_id} is sequenced before {x.operation_id}."
                    )
                    hint = f"Move {x.operation_id} before {y.operation_id}."
                else:
                    continue
                out.append(
                    Violation(
                        rule_id=R9,
                        severity="hard",
                        operation_id=y.operation_id,
                        feature_id=pc.after.feature_id,
                        message=message,
                        evidence={
                            "source": "component_precedence_constraint",
                            "constraint_index": ci,
                            "before": pc.before.model_dump(),
                            "after": pc.after.model_dump(),
                            "rationale": pc.rationale,
                            "before_operation": x.operation_id,
                            "after_operation": y.operation_id,
                            "positions": {x.operation_id: pos[x.operation_id], y.operation_id: pos[y.operation_id]},
                        },
                        repair_hint=hint,
                    )
                )
    return out
