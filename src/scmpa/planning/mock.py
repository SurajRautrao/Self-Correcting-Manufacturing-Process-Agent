"""Deterministic rule-based planner for tests, offline demos and controlled experiments.

It is *not* an AI planner and is not meant to be clever: it builds the
obvious plan from the component data (first available machine/tool per
needed operation, ordered by the component's precedence constraints), and can
optionally inject known faults so the repair loop and evaluation have
ground-truth corrupted inputs.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from scmpa.graph import stable_topological_order
from scmpa.planning.faults import inject_fault
from scmpa.planning.planner import PlanResult, default_plan_id
from scmpa.schemas import Catalogue, Component, Operation, ProcessPlan
from scmpa.validation.context import ValidationContext

#: Illustrative placeholder durations (minutes) per operation type. Not cutting-data based.
PLACEHOLDER_DURATION_MIN: dict[str, float] = {
    "face_milling": 4.0,
    "contour_milling": 5.0,
    "pocket_milling": 6.0,
    "slot_milling": 4.0,
    "spot_drilling": 0.5,
    "drilling": 2.0,
    "reaming": 1.5,
    "tapping": 1.5,
    "chamfering": 1.5,
}
DEFAULT_DURATION_MIN = 3.0


def build_baseline_plan(component: Component, catalogue: Catalogue, plan_id: str) -> ProcessPlan:
    """Construct the straightforward plan implied by the component data."""
    ctx = ValidationContext(component, catalogue)
    drafts: list[dict] = []
    uncertainties: list[str] = []

    for feature in component.features:
        suitable = ctx.suitable_operation_types(feature)
        if feature.required_operation_types:
            needed = list(feature.required_operation_types)
        else:
            producible = [t for t in suitable if ctx.resource_options(t)]
            # spot drilling alone does not make a hole; prefer the main operation if possible
            main = [t for t in producible if t != "spot_drilling"]
            needed = (main or producible or suitable)[:1]
        for op_type in needed:
            options = ctx.resource_options(op_type)
            if not options:
                if feature.required:
                    uncertainties.append(
                        f"No available machine/tool can perform {op_type!r} for required feature {feature.feature_id}."
                    )
                continue
            drafts.append(
                {
                    "type": op_type,
                    "target_features": [feature.feature_id],
                    "machine_id": options[0]["machine_id"],
                    "tool_id": options[0]["tool_id"],
                    "duration_min": PLACEHOLDER_DURATION_MIN.get(op_type, DEFAULT_DURATION_MIN),
                }
            )

    def matches(d: dict, ref) -> bool:
        return ref.feature_id in d["target_features"] and (ref.operation_type is None or d["type"] == ref.operation_type)

    edges: list[tuple[int, int]] = []
    for pc in component.precedence_constraints:
        for i, a in enumerate(drafts):
            for j, b in enumerate(drafts):
                if i != j and matches(a, pc.before) and matches(b, pc.after) and (i, j) not in edges:
                    edges.append((i, j))

    order = stable_topological_order(len(drafts), edges)
    if order is None:  # cannot happen for validated components (acyclic constraints)
        raise ValueError("precedence constraints are cyclic")
    new_id = {old: f"OP{k + 1}" for k, old in enumerate(order)}
    operations = [Operation(operation_id=new_id[i], **drafts[i]) for i in order]
    precedence = sorted(([new_id[a], new_id[b]] for a, b in edges), key=lambda e: (int(e[0][2:]), int(e[1][2:])))

    return ProcessPlan(
        plan_id=plan_id,
        component_id=component.component_id,
        operations=operations,
        precedence=precedence,
        explanation=(
            "Mock plan: one operation per needed operation type using the first available capable machine and "
            "compatible tool, ordered to satisfy the component's declared precedence constraints."
        ),
        assumptions=["Durations are illustrative placeholders, not calculated from cutting data."],
        uncertainties=uncertainties,
    )


class MockPlanner:
    """Deterministic planner. ``faults`` lists fault kinds (see :mod:`scmpa.planning.faults`) to inject."""

    name = "mock"

    def __init__(self, faults: Sequence[str] = (), seed: int = 0) -> None:
        self.faults = list(faults)
        self.seed = seed

    def generate_plan(self, component: Component, catalogue: Catalogue, *, plan_id: str | None = None) -> PlanResult:
        plan = build_baseline_plan(component, catalogue, plan_id or default_plan_id(component))
        rng = random.Random(self.seed)
        records = []
        touched: set[str] = set()
        for kind in self.faults:
            plan, record = inject_fault(plan, component, catalogue, kind, rng, exclude_operations=touched)
            records.append(record.model_dump())
            # Faults on precedence edges involve both endpoints; protect all ops a fault touched.
            touched.update(record.operations)
        return PlanResult(status="ok", plan=plan, planner=self.name, model=None, injected_faults=records)
