"""Seeded fault injection: corrupt a valid plan in a known way with a known expected rule.

Used by the mock planner, repair-loop tests and (later) the synthetic
benchmark. Each fault returns a new plan (the input is not modified) and a
:class:`FaultRecord` stating which rule should detect it.
"""

from __future__ import annotations

import random

from scmpa.schemas import Catalogue, Component, ProcessPlan
from scmpa.schemas.base import StrictModel
from scmpa.validation.context import ValidationContext

UNKNOWN_MACHINE_ID = "M_UNKNOWN"
UNKNOWN_TOOL_ID = "T_UNKNOWN"
UNKNOWN_FEATURE_ID = "F_UNKNOWN"
UNKNOWN_OPERATION_TYPE = "laser_cutting"


class FaultRecord(StrictModel):
    kind: str
    operation_id: str | None = None
    #: Every operation the fault involves (both endpoints for edge faults).
    operations: list[str] = []
    expected_rule: str
    detail: str


class FaultNotApplicable(ValueError):
    """The requested fault cannot be injected into this plan/component."""


def _pick(rng: random.Random, items: list, kind: str):
    if not items:
        raise FaultNotApplicable(f"fault {kind!r} is not applicable to this plan")
    return rng.choice(sorted(items, key=str))


def inject_fault(
    plan: ProcessPlan,
    component: Component,
    catalogue: Catalogue,
    kind: str,
    rng: random.Random,
    *,
    exclude_operations: frozenset[str] | set[str] = frozenset(),
) -> tuple[ProcessPlan, FaultRecord]:
    """Return a corrupted copy of ``plan`` and a record of what was done.

    Operations in ``exclude_operations`` are never touched, so several faults
    can be injected into distinct operations without overwriting each other.
    """
    if kind not in FAULT_KINDS:
        raise ValueError(f"unknown fault kind {kind!r}; known: {sorted(FAULT_KINDS)}")
    data = plan.model_dump(mode="json")
    ops = data["operations"]
    by_id = {o["operation_id"]: o for o in ops if o["operation_id"] not in exclude_operations}
    ctx = ValidationContext(component, catalogue)

    if kind == "unknown_operation_type":
        op = by_id[_pick(rng, list(by_id), kind)]
        op["type"] = UNKNOWN_OPERATION_TYPE
        rec = FaultRecord(kind=kind, operation_id=op["operation_id"], expected_rule="R1_OPERATION_TYPE", detail=f"type -> {UNKNOWN_OPERATION_TYPE}")

    elif kind == "unknown_machine":
        op = by_id[_pick(rng, list(by_id), kind)]
        op["machine_id"] = UNKNOWN_MACHINE_ID
        rec = FaultRecord(kind=kind, operation_id=op["operation_id"], expected_rule="R2_MACHINE_EXISTS", detail=f"machine -> {UNKNOWN_MACHINE_ID}")

    elif kind == "incapable_machine":
        pairs = [
            (o["operation_id"], m) for o in by_id.values() for m in ctx.machines
            if o["type"] in ctx.operation_types and o["type"] not in ctx.machines[m].capabilities
        ]
        op_id, machine = _pick(rng, pairs, kind)
        by_id[op_id]["machine_id"] = machine
        rec = FaultRecord(kind=kind, operation_id=op_id, expected_rule="R3_MACHINE_CAPABILITY", detail=f"machine -> {machine}")

    elif kind == "unknown_tool":
        op = by_id[_pick(rng, list(by_id), kind)]
        op["tool_id"] = UNKNOWN_TOOL_ID
        rec = FaultRecord(kind=kind, operation_id=op["operation_id"], expected_rule="R4_TOOL_EXISTS", detail=f"tool -> {UNKNOWN_TOOL_ID}")

    elif kind == "incompatible_tool":
        pairs = [
            (o["operation_id"], t) for o in by_id.values() for t, tool in ctx.tools.items()
            if o["type"] in ctx.operation_types and tool.type not in catalogue.tool_compatibility[o["type"]]
        ]
        op_id, tool_id = _pick(rng, pairs, kind)
        by_id[op_id]["tool_id"] = tool_id
        rec = FaultRecord(kind=kind, operation_id=op_id, expected_rule="R5_TOOL_COMPATIBILITY", detail=f"tool -> {tool_id}")

    elif kind == "missing_operation":
        required = set(component.required_feature_ids)
        candidates = [o["operation_id"] for o in by_id.values() if required & set(o["target_features"])]
        op_id = _pick(rng, candidates, kind)
        data["operations"] = [o for o in ops if o["operation_id"] != op_id]
        data["precedence"] = [e for e in data["precedence"] if op_id not in e]
        rec = FaultRecord(kind=kind, operation_id=op_id, expected_rule="R6_FEATURE_COVERAGE", detail=f"removed {op_id}")

    elif kind == "unknown_feature":
        op = by_id[_pick(rng, list(by_id), kind)]
        op["target_features"] = op["target_features"] + [UNKNOWN_FEATURE_ID]
        rec = FaultRecord(kind=kind, operation_id=op["operation_id"], expected_rule="R7_FEATURE_REFERENCE", detail=f"added target {UNKNOWN_FEATURE_ID}")

    elif kind == "precedence_cycle":
        a, b = _pick(rng, [tuple(e) for e in data["precedence"] if not set(e) & exclude_operations], kind)
        data["precedence"].append([b, a])
        rec = FaultRecord(kind=kind, operation_id=b, expected_rule="R8_PRECEDENCE_VALIDITY", detail=f"added reverse edge {b}->{a}", operations=[a, b])

    elif kind == "swap_precedence":
        a, b = _pick(rng, [tuple(e) for e in data["precedence"] if not set(e) & exclude_operations], kind)
        ia = next(i for i, o in enumerate(ops) if o["operation_id"] == a)
        ib = next(i for i, o in enumerate(ops) if o["operation_id"] == b)
        ops[ia], ops[ib] = ops[ib], ops[ia]
        rec = FaultRecord(kind=kind, operation_id=b, expected_rule="R9_PRECEDENCE_ORDER", detail=f"swapped {a} and {b} in sequence", operations=[a, b])

    elif kind == "invalid_duration":
        op = by_id[_pick(rng, list(by_id), kind)]
        op["duration_min"] = -1.0
        rec = FaultRecord(kind=kind, operation_id=op["operation_id"], expected_rule="R11_DURATION", detail="duration -> -1.0")

    else:  # pragma: no cover - guarded above
        raise AssertionError(kind)

    if not rec.operations and rec.operation_id:
        rec = rec.model_copy(update={"operations": [rec.operation_id]})
    return ProcessPlan.model_validate(data), rec


#: Fault kind -> rule expected to detect it.
FAULT_KINDS: dict[str, str] = {
    "unknown_operation_type": "R1_OPERATION_TYPE",
    "unknown_machine": "R2_MACHINE_EXISTS",
    "incapable_machine": "R3_MACHINE_CAPABILITY",
    "unknown_tool": "R4_TOOL_EXISTS",
    "incompatible_tool": "R5_TOOL_COMPATIBILITY",
    "missing_operation": "R6_FEATURE_COVERAGE",
    "unknown_feature": "R7_FEATURE_REFERENCE",
    "precedence_cycle": "R8_PRECEDENCE_VALIDITY",
    "swap_precedence": "R9_PRECEDENCE_ORDER",
    "invalid_duration": "R11_DURATION",
}
