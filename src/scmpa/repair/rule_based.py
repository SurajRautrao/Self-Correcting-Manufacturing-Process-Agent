"""Deterministic, evidence-driven repair agent (no LLM).

It applies one targeted fix per reported hard violation, using the
validator's evidence. It exists so the repair loop can be tested and
demonstrated offline, and as a non-AI reference point in experiments. It is
*not* evidence that an AI can repair plans.

Fixes per rule:

========  ==============================================================
R1        change the operation type to a producible suitable type for its target(s)
R2, R3    assign the first available capable machine
R4, R5    assign the first available compatible tool
R3, R5    no capable resource exists but the op is not needed for coverage: remove it
R6        drop an unsuitable target; add an operation for each missing type
R7        drop the unknown target
R8        drop edges to unknown operations; drop the closing edge of a cycle
R9        reorder (stable topological sort over plan edges + component constraints)
R10       (if hard) drop the duplicate operation
R11       replace the duration with a placeholder estimate
R12       fix component_id / explanation; drop operations without targets
========  ==============================================================

Operations left without targets are removed together with their edges.
If any hard violation is marked ``repairable=False``, no repair is attempted.
"""

from __future__ import annotations

from typing import Any

from scmpa.graph import stable_topological_order
from scmpa.planning.mock import DEFAULT_DURATION_MIN, PLACEHOLDER_DURATION_MIN
from scmpa.repair.repair_agent import RepairResult
from scmpa.schemas import Catalogue, Component, Operation, PrecedenceRef, ProcessPlan, ValidationResult
from scmpa.validation.context import ValidationContext


def operation_matches(op: Operation, ref: PrecedenceRef) -> bool:
    return ref.feature_id in op.target_features and (ref.operation_type is None or op.type == ref.operation_type)


def reorder_to_satisfy_precedence(plan: ProcessPlan, component: Component) -> tuple[ProcessPlan, bool]:
    """Stable reorder of ``plan.operations`` honouring plan edges and component constraints.

    If plan edges conflict (cycle), only component constraints are honoured and
    plan edges violated by the result are dropped. Returns ``(plan, changed)``.
    """
    ops = plan.operations
    index = {op.operation_id: i for i, op in enumerate(ops)}
    constraint_edges = [
        (index[x.operation_id], index[y.operation_id])
        for pc in component.precedence_constraints
        for x in ops if operation_matches(x, pc.before)
        for y in ops if operation_matches(y, pc.after) and x.operation_id != y.operation_id
    ]
    plan_edges = [(index[a], index[b]) for a, b in plan.precedence if a in index and b in index and a != b]
    order = stable_topological_order(len(ops), constraint_edges + plan_edges)
    precedence = plan.precedence
    if order is None:
        order = stable_topological_order(len(ops), constraint_edges)
        if order is None:  # component constraints are validated acyclic at input time
            return plan, False
        pos = {i: k for k, i in enumerate(order)}
        precedence = [e for e in plan.precedence if not (e[0] in index and e[1] in index and pos[index[e[0]]] > pos[index[e[1]]])]
    new_ops = [ops[i] for i in order]
    changed = new_ops != list(ops) or precedence != plan.precedence
    return plan.model_copy(update={"operations": new_ops, "precedence": precedence}), changed


class RuleBasedRepairAgent:
    """Deterministic repair from validator evidence. See module docstring for the fix table."""

    name = "rule_based"

    def repair_plan(
        self, component: Component, catalogue: Catalogue, plan: ProcessPlan, validation: ValidationResult, *, plan_id: str
    ) -> RepairResult:
        hard = validation.hard_constraint_violations
        blocked = [v for v in hard if not v.repairable]
        if blocked:
            return RepairResult(
                status="needs_human_review", agent=self.name,
                missing_information=[f"{v.rule_id}: {v.repair_hint or v.message}" for v in blocked],
            )

        ctx = ValidationContext(component, catalogue)
        data = plan.model_dump(mode="json")
        ops: list[dict[str, Any]] = data["operations"]
        changes: list[str] = []
        removed: set[str] = set()

        def find(op_id: str | None) -> dict[str, Any] | None:
            return next((o for o in ops if o["operation_id"] == op_id and op_id not in removed), None)

        def assign_resources(op: dict[str, Any]) -> None:
            machine = ctx.machines.get(op["machine_id"])
            if machine is None or op["type"] not in machine.capabilities:
                if capable := ctx.capable_machines(op["type"]):
                    changes.append(f"{op['operation_id']}: machine {op['machine_id']} -> {capable[0]}")
                    op["machine_id"] = capable[0]
            tool = ctx.tools.get(op["tool_id"])
            if tool is None or tool.type not in catalogue.tool_compatibility.get(op["type"], []):
                if compatible := ctx.compatible_tools(op["type"]):
                    changes.append(f"{op['operation_id']}: tool {op['tool_id']} -> {compatible[0]}")
                    op["tool_id"] = compatible[0]

        def drop_target(op: dict[str, Any], fid: str) -> None:
            if fid in op["target_features"]:
                op["target_features"] = [f for f in op["target_features"] if f != fid]
                changes.append(f"{op['operation_id']}: removed target {fid}")

        def next_op_id() -> str:
            nums = [int(o["operation_id"][2:]) for o in ops if o["operation_id"][:2] == "OP" and o["operation_id"][2:].isdigit()]
            return f"OP{max(nums, default=0) + 1}"

        for v in hard:
            op = find(v.operation_id)
            rid = v.rule_id.split("_")[0]
            if rid == "R1" and op:
                # Prefer a type the target feature still needs, then one not yet applied to it.
                needed, unused, other = [], [], []
                for fid in op["target_features"]:
                    if (f := ctx.features.get(fid)) is None:
                        continue
                    applied = {
                        o["type"] for o in ops
                        if o is not op and o["operation_id"] not in removed and fid in o["target_features"]
                    }
                    for t in ctx.suitable_operation_types(f):
                        if not ctx.resource_options(t):
                            continue
                        if t in (f.required_operation_types or []) and t not in applied:
                            needed.append(t)
                        elif t not in applied:
                            unused.append(t)
                        else:
                            other.append(t)
                suitable = needed + unused + other
                if suitable:
                    changes.append(f"{op['operation_id']}: type {op['type']} -> {suitable[0]}")
                    op["type"] = suitable[0]
                    assign_resources(op)
            elif rid in ("R3", "R5") and op and v.evidence.get("operation_removable"):
                removed.add(op["operation_id"])
                changes.append(f"removed {op['operation_id']} ({op['type']}): no capable resource and not needed for coverage")
            elif rid in ("R2", "R3", "R4", "R5") and op:
                assign_resources(op)
            elif rid == "R6" and op and v.feature_id:
                drop_target(op, v.feature_id)
            elif rid == "R6" and v.feature_id:
                feature = ctx.features[v.feature_id]
                suitable = ctx.suitable_operation_types(feature)
                # Recompute from the current state: an earlier fix (e.g. R1) may already cover it.
                applied = {
                    o["type"] for o in ops
                    if o["operation_id"] not in removed and feature.feature_id in o["target_features"] and o["type"] in suitable
                }
                if feature.required_operation_types:
                    missing = [t for t in feature.required_operation_types if t not in applied]
                elif applied:
                    missing = []
                else:
                    producible = [t for t in suitable if ctx.resource_options(t)]
                    main = [t for t in producible if t != "spot_drilling"]
                    missing = (main or producible)[:1]
                for op_type in missing:
                    option = ctx.resource_options(op_type)[0]
                    new = {
                        "operation_id": next_op_id(), "type": op_type, "target_features": [feature.feature_id],
                        "machine_id": option["machine_id"], "tool_id": option["tool_id"],
                        "duration_min": PLACEHOLDER_DURATION_MIN.get(op_type, DEFAULT_DURATION_MIN), "notes": "",
                    }
                    ops.append(new)
                    changes.append(f"added {new['operation_id']}: {op_type} on {feature.feature_id} ({new['machine_id']}/{new['tool_id']})")
            elif rid == "R7" and op and v.feature_id:
                drop_target(op, v.feature_id)
            elif rid == "R8":
                if "cycle" in v.evidence:
                    a, b = v.evidence["cycle"][-2], v.evidence["cycle"][-1]
                    if [a, b] in data["precedence"]:
                        data["precedence"].remove([a, b])
                        changes.append(f"removed precedence edge {a} -> {b} to break cycle")
                elif "edge" in v.evidence and v.evidence["edge"] in data["precedence"]:
                    data["precedence"].remove(v.evidence["edge"])
                    changes.append(f"removed precedence edge {v.evidence['edge']} (unknown operation)")
            elif rid == "R10" and op:
                removed.add(op["operation_id"])
                changes.append(f"removed duplicate operation {op['operation_id']}")
            elif rid == "R11" and op:
                new_d = PLACEHOLDER_DURATION_MIN.get(op["type"], DEFAULT_DURATION_MIN)
                changes.append(f"{op['operation_id']}: duration {op['duration_min']} -> {new_d} (placeholder)")
                op["duration_min"] = new_d
            elif rid == "R12":
                if "expected_component_id" in v.evidence:
                    data["component_id"] = v.evidence["expected_component_id"]
                    changes.append(f"component_id -> {data['component_id']}")
                elif v.evidence.get("field") == "explanation":
                    data["explanation"] = "Plan revised by the rule-based repair agent."
                    changes.append("filled empty explanation")
            # R9 is handled by the reorder below.

        for op in ops:
            if not op["target_features"] and op["operation_id"] not in removed:
                removed.add(op["operation_id"])
                changes.append(f"removed {op['operation_id']} (no remaining targets)")
        data["operations"] = [o for o in ops if o["operation_id"] not in removed]
        data["precedence"] = [e for e in data["precedence"] if not (set(e) & removed)]
        data["plan_id"] = plan_id

        repaired, reordered = reorder_to_satisfy_precedence(ProcessPlan.model_validate(data), component)
        if reordered:
            changes.append("reordered operations to satisfy precedence")
        if not changes:
            return RepairResult(
                status="needs_human_review", agent=self.name,
                missing_information=["rule-based agent has no fix for: " + ", ".join(sorted({v.rule_id for v in hard}))],
            )
        return RepairResult(status="repaired", plan=repaired, changes=changes, agent=self.name)
