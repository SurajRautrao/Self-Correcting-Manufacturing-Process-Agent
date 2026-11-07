"""Bounded generate → validate → repair → revalidate workflow (spec section 6.3).

State machine::

    RECEIVED -> INPUT_VALIDATED -> PLAN_GENERATED -> PLAN_VALIDATED
        -> ACCEPTED
        -> REPAIR_REQUESTED -> PLAN_REPAIRED -> PLAN_VALIDATED -> ...
        -> NEEDS_HUMAN_REVIEW

The loop always terminates: at most ``max_repairs`` repair calls, and it
stops early on a repeated plan, a non-repairable violation, a human-review
request from the repair agent, or unusable planner/repair output. Every plan,
validation result and repair call is recorded in the :class:`RunRecord`.

The *final* plan is the accepted one, or, when the run ends in human review,
the candidate with the fewest hard violations (latest on ties; see
:func:`best_iteration`). A repair that makes a plan worse is therefore never
handed to the reviewer in place of a better earlier candidate.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from scmpa.io import InputValidationError, check_component_against_catalogue
from scmpa.planning.planner import PlanAttempt, Planner, PlanResult
from scmpa.repair.repair_agent import RepairAgent, RepairResult
from scmpa.schemas import SCHEMA_VERSION, Catalogue, Component, ProcessPlan, ValidationResult
from scmpa.schemas.base import StrictModel
from scmpa.validation import RULE_SET_VERSION, ValidationConfig, validate_plan

State = Literal[
    "RECEIVED", "INPUT_VALIDATED", "PLAN_GENERATED", "PLAN_VALIDATED",
    "REPAIR_REQUESTED", "PLAN_REPAIRED", "ACCEPTED", "NEEDS_HUMAN_REVIEW",
]
StopReason = Literal[
    "valid",
    "max_repairs_reached",
    "repeated_plan",
    "non_repairable_violation",
    "repair_agent_requested_review",
    "planner_output_invalid",
    "repair_output_invalid",
]


def default_max_repairs() -> int:
    """``$SCMPA_MAX_REPAIRS`` or the spec default of 3."""
    return int(os.environ.get("SCMPA_MAX_REPAIRS", "3"))


def stable_plan_hash(plan: ProcessPlan) -> str:
    """Hash of the plan's *decision content*: component, operation sequence and precedence.

    Plan ID, explanation, assumptions, uncertainties and operation notes are
    excluded, so a repair that only rewords text counts as a repeated plan.
    """
    content = {
        "component_id": plan.component_id,
        "operations": [op.model_dump(mode="json", exclude={"notes"}) for op in plan.operations],
        "precedence": sorted(plan.precedence),
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:16]


def plan_diff(old: ProcessPlan, new: ProcessPlan) -> dict[str, Any]:
    """Operation-level difference between two plans (for auditing minimal repairs)."""
    old_ops = {o.operation_id: o.model_dump(mode="json", exclude={"notes"}) for o in old.operations}
    new_ops = {o.operation_id: o.model_dump(mode="json", exclude={"notes"}) for o in new.operations}
    modified = {}
    for op_id in sorted(old_ops.keys() & new_ops.keys()):
        fields = {k: [old_ops[op_id][k], new_ops[op_id][k]] for k in old_ops[op_id] if old_ops[op_id][k] != new_ops[op_id][k]}
        if fields:
            modified[op_id] = fields
    return {
        "added": sorted(new_ops.keys() - old_ops.keys()),
        "removed": sorted(old_ops.keys() - new_ops.keys()),
        "modified": modified,
        "sequence_changed": [o for o in old.sequence if o in new_ops] != [o for o in new.sequence if o in old_ops],
        "precedence_added": sorted(map(list, {tuple(e) for e in new.precedence} - {tuple(e) for e in old.precedence})),
        "precedence_removed": sorted(map(list, {tuple(e) for e in old.precedence} - {tuple(e) for e in new.precedence})),
        "unchanged_operations": sorted(o for o in old_ops.keys() & new_ops.keys() if o not in modified),
    }


def best_iteration(iterations: list[Iteration]) -> Iteration | None:
    """The candidate to hand on: fewest hard violations, the latest one on ties (so a valid last plan wins)."""
    if not iterations:
        return None
    return min(reversed(iterations), key=lambda it: len(it.validation.hard_constraint_violations))


class StateTransition(StrictModel):
    state: State
    iteration: int | None = None
    detail: str = ""


class RepairCall(StrictModel):
    """Record of one repair request (excluding the revised plan, stored in the next iteration)."""

    status: Literal["repaired", "needs_human_review", "failed"]
    agent: str
    model: str | None = None
    changes: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    prompt_refs: list[str] = Field(default_factory=list)
    attempts: list[PlanAttempt] = Field(default_factory=list)
    normalization_notes: list[str] = Field(default_factory=list)
    error: str | None = None
    diff: dict[str, Any] | None = None
    latency_s: float


class Iteration(StrictModel):
    """One candidate plan and its validation. Iteration 0 comes from the planner, later ones from repair."""

    index: int
    source: Literal["planner", "repair"]
    plan: ProcessPlan
    plan_hash: str
    validation: ValidationResult
    repair: RepairCall | None = None


class RunRecord(StrictModel):
    """Complete, serialisable account of one workflow run."""

    run_id: str
    component_id: str
    started_at: str
    duration_s: float
    planner: str
    planner_model: str | None = None
    repair_agent: str | None = None
    max_repairs: int
    validation_config: ValidationConfig
    versions: dict[str, Any]
    planner_result: PlanResult
    iterations: list[Iteration] = Field(default_factory=list)
    transitions: list[StateTransition] = Field(default_factory=list)
    final_status: Literal["ACCEPTED", "NEEDS_HUMAN_REVIEW"]
    stop_reason: StopReason
    stop_detail: str = ""
    #: A repair call that ended the run without producing a new plan (human-review request or unusable output).
    terminal_repair: RepairCall | None = None
    #: Index of the iteration whose plan is ``final_plan`` (see :func:`best_iteration`).
    final_iteration: int | None = None
    final_plan: ProcessPlan | None = None
    final_validation: ValidationResult | None = None

    @property
    def repairs_used(self) -> int:
        """Number of repair calls made, including one that ended the run without a plan."""
        return sum(1 for it in self.iterations if it.repair is not None) + (1 if self.terminal_repair else 0)

    @property
    def initially_valid(self) -> bool | None:
        return self.iterations[0].validation.valid if self.iterations else None


def solve(
    component: Component,
    catalogue: Catalogue,
    planner: Planner,
    repair_agent: RepairAgent | None,
    *,
    max_repairs: int | None = None,
    config: ValidationConfig | None = None,
    run_id: str | None = None,
) -> RunRecord:
    """Run the bounded workflow and return the full record.

    ``repair_agent=None`` or ``max_repairs=0`` gives the "LLM + validator"
    baseline (B1): validate once, never repair.
    """
    max_repairs = default_max_repairs() if max_repairs is None else max_repairs
    if max_repairs < 0:
        raise ValueError("max_repairs must be >= 0")
    if repair_agent is None:
        max_repairs = 0
    config = config or ValidationConfig()
    run_id = run_id or uuid.uuid4().hex[:12]
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    t0 = time.perf_counter()

    transitions: list[StateTransition] = [StateTransition(state="RECEIVED")]
    if problems := check_component_against_catalogue(component, catalogue):
        raise InputValidationError(component.component_id, problems)
    transitions.append(StateTransition(state="INPUT_VALIDATED"))

    iterations: list[Iteration] = []
    pending_repair: RepairCall | None = None

    def finish(
        status: Literal["ACCEPTED", "NEEDS_HUMAN_REVIEW"], reason: StopReason, detail: str = "",
        terminal_repair: RepairCall | None = None,
    ) -> RunRecord:
        transitions.append(StateTransition(state=status, iteration=len(iterations) - 1 if iterations else None, detail=detail or reason))
        chosen = best_iteration(iterations)
        return RunRecord(
            run_id=run_id, component_id=component.component_id, started_at=started_at,
            duration_s=round(time.perf_counter() - t0, 3),
            planner=planner.name, planner_model=planner_result.model,
            repair_agent=getattr(repair_agent, "name", None), max_repairs=max_repairs, validation_config=config,
            versions={
                "schema_version": SCHEMA_VERSION, "rule_set_version": RULE_SET_VERSION,
                "catalogue_id": catalogue.catalogue_id, "repair_model": getattr(getattr(repair_agent, "client", None), "model", None),
            },
            planner_result=planner_result.model_copy(update={"plan": None}),
            iterations=iterations, transitions=transitions, final_status=status, stop_reason=reason, stop_detail=detail,
            terminal_repair=terminal_repair,
            final_iteration=chosen.index if chosen else None,
            final_plan=chosen.plan if chosen else None, final_validation=chosen.validation if chosen else None,
        )

    planner_result = planner.generate_plan(component, catalogue)
    if planner_result.status != "ok" or planner_result.plan is None:
        return finish("NEEDS_HUMAN_REVIEW", "planner_output_invalid", planner_result.error or "planner failed")
    transitions.append(StateTransition(state="PLAN_GENERATED", iteration=0))
    plan = planner_result.plan
    seen: dict[str, int] = {}

    for i in range(max_repairs + 1):
        validation = validate_plan(plan, component, catalogue, config)
        h = stable_plan_hash(plan)
        iterations.append(
            Iteration(index=i, source="planner" if i == 0 else "repair", plan=plan, plan_hash=h, validation=validation, repair=pending_repair)
        )
        transitions.append(
            StateTransition(state="PLAN_VALIDATED", iteration=i, detail=f"{len(validation.hard_constraint_violations)} hard violation(s)")
        )
        if validation.valid:
            return finish("ACCEPTED", "valid")
        if h in seen:
            return finish("NEEDS_HUMAN_REVIEW", "repeated_plan", f"iteration {i} repeats iteration {seen[h]}")
        seen[h] = i
        blocked = [v for v in validation.hard_constraint_violations if not v.repairable]
        if blocked:
            return finish(
                "NEEDS_HUMAN_REVIEW", "non_repairable_violation",
                "; ".join(f"{v.rule_id}: {v.repair_hint or v.message}" for v in blocked),
            )
        if i == max_repairs:
            return finish("NEEDS_HUMAN_REVIEW", "max_repairs_reached", f"{max_repairs} repair(s) used")

        transitions.append(StateTransition(state="REPAIR_REQUESTED", iteration=i))
        r0 = time.perf_counter()
        result: RepairResult = repair_agent.repair_plan(  # type: ignore[union-attr]
            component, catalogue, plan, validation, plan_id=f"{component.component_id}_plan_v{i + 1}"
        )
        call = RepairCall(
            status=result.status, agent=result.agent, model=result.model, changes=result.changes,
            missing_information=result.missing_information, prompt_refs=result.prompt_refs, attempts=result.attempts,
            normalization_notes=result.normalization_notes, error=result.error,
            diff=plan_diff(plan, result.plan) if result.plan else None, latency_s=round(time.perf_counter() - r0, 3),
        )
        if result.status == "needs_human_review":
            return finish(
                "NEEDS_HUMAN_REVIEW", "repair_agent_requested_review", "; ".join(result.missing_information), terminal_repair=call
            )
        if result.status == "failed" or result.plan is None:
            return finish("NEEDS_HUMAN_REVIEW", "repair_output_invalid", result.error or "repair failed", terminal_repair=call)
        transitions.append(StateTransition(state="PLAN_REPAIRED", iteration=i + 1, detail=f"{len(result.changes)} change(s)"))
        plan, pending_repair = result.plan, call

    raise AssertionError("unreachable: loop always returns")  # pragma: no cover


def save_run(record: RunRecord, directory: str | Path) -> Path:
    """Write ``<directory>/<component_id>_<run_id>.json`` and return the path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record.component_id}_{record.run_id}.json"
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_run(path: str | Path) -> RunRecord:
    return RunRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))
