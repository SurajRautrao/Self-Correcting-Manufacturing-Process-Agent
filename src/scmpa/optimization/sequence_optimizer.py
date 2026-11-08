"""Deterministic sequence optimizer (Milestone 6, hypothesis H3).

Optimization is not repair. This module only accepts plans the validator
already accepts. It searches for a better *feasible* plan under an explicit
objective, then runs the independent validator again on the result.

Problem (solved exactly with OR-Tools CP-SAT)
---------------------------------------------
* **Tasks:** the plan's operations. Their types, targets and durations are fixed.
* **Decisions:** the operation order and, if ``reassign_resources`` is set, which
  eligible (machine, tool) pair performs each operation. Eligible means the
  machine declares the operation type (R3) and the tool type is compatible (R5).
* **Hard constraints:** every ordering R9 demands, i.e. the plan's precedence edges
  plus the component's ``precedence_constraints`` (:func:`required_order_pairs`).
* **Objective:** ``machine_change_weight × machine changes + tool_change_weight × tool changes``,
  counted between consecutive operations. A machine change stands in for a
  transfer and re-fixturing, and a tool change for a tool swap. The default
  weights 10 : 1 say a machine change costs about ten tool changes. That is a
  demo assumption, which is why ``evaluation.optimize_results`` reports a
  sensitivity check over other weights.
* **Tie-break (secondary):** among equally good plans, the one closest to the input,
  measured as total position displacement plus the number of reassigned operations.
  The optimizer prefers small, explainable changes.

Total duration is the sum of fixed per-operation estimates, so reordering cannot
change it. No time saving is claimed. Setups, travel and tool-change times are
not modelled beyond these change counts.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import Field, NonNegativeInt, PositiveFloat

from scmpa.schemas import Catalogue, Component, ProcessPlan, ValidationResult
from scmpa.schemas.base import StrictModel
from scmpa.validation import ValidationConfig, validate_plan
from scmpa.validation.context import ValidationContext
from scmpa.validation.rules.precedence import required_order_pairs
from scmpa.workflow.orchestration import plan_diff

OptimizationStatus = Literal["optimized", "unchanged", "rejected_input", "solver_failed", "rejected_output"]


class OptimizationConfig(StrictModel):
    """Objective weights and solver settings. Integer weights keep the CP-SAT objective exact."""

    machine_change_weight: NonNegativeInt = 10
    tool_change_weight: NonNegativeInt = 1
    #: Also choose among eligible (machine, tool) pairs, not just the order.
    reassign_resources: bool = True
    #: CP-SAT *deterministic* time budget per solve phase (not wall clock), so results do not depend
    #: on machine speed or load. Hitting it is reported in ``solver_status`` / ``tie_break_status``.
    deterministic_time_limit: PositiveFloat = 5.0
    #: Smaller budget for phase 2, which only chooses among plans of equal cost.
    tie_break_time_limit: PositiveFloat = 0.5
    #: One worker and a fixed seed make the search reproducible for a given OR-Tools version.
    num_workers: int = Field(default=1, ge=1)
    random_seed: int = 0


class SequenceCost(StrictModel):
    machine_changes: int
    tool_changes: int
    cost: int


class OptimizationResult(StrictModel):
    """Outcome of one optimization. ``plan`` is the input plan unless ``status == "optimized"``."""

    status: OptimizationStatus
    detail: str = ""
    #: Phase 1 (minimum change cost). ``OPTIMAL`` means no lower-cost feasible plan exists.
    solver_status: str | None = None
    #: Phase 2 (closest plan at that cost). ``FEASIBLE`` means the tie-break is not proven minimal.
    tie_break_status: str | None = None
    config: OptimizationConfig
    plan: ProcessPlan
    before: SequenceCost | None = None
    after: SequenceCost | None = None
    changes: list[str] = Field(default_factory=list)
    diff: dict[str, Any] | None = None
    validation: ValidationResult | None = None
    latency_s: float = 0.0


def sequence_cost(plan: ProcessPlan, config: OptimizationConfig | None = None) -> SequenceCost:
    """Machine and tool changes between consecutive operations, and the weighted cost."""
    config = config or OptimizationConfig()
    ops = plan.operations
    mc = sum(1 for a, b in zip(ops, ops[1:]) if a.machine_id != b.machine_id)
    tc = sum(1 for a, b in zip(ops, ops[1:]) if a.tool_id != b.tool_id)
    return SequenceCost(machine_changes=mc, tool_changes=tc, cost=config.machine_change_weight * mc + config.tool_change_weight * tc)


def min_cover_size(option_sets: list[set[str]]) -> int:
    """Smallest number of values such that every set contains at least one (exact; the sets here are tiny)."""
    from itertools import combinations

    values = sorted(set().union(*option_sets)) if option_sets else []
    for size in range(1, len(values) + 1):
        if any(all(s & set(c) for s in option_sets) for c in combinations(values, size)):
            return size
    return 0


def optimize_sequence(
    plan: ProcessPlan,
    component: Component,
    catalogue: Catalogue,
    config: OptimizationConfig | None = None,
    validation_config: ValidationConfig | None = None,
) -> OptimizationResult:
    """Return a lower-cost valid plan, or the input plan with the reason it was kept."""
    from ortools.sat.python import cp_model  # optional dependency: pip install -e ".[opt]"

    config = config or OptimizationConfig()
    t0 = time.perf_counter()

    def done(status: OptimizationStatus, detail: str = "", **kw: Any) -> OptimizationResult:
        return OptimizationResult(status=status, detail=detail, config=config, latency_s=round(time.perf_counter() - t0, 3), **kw)

    initial = validate_plan(plan, component, catalogue, validation_config)
    if not initial.valid:
        return done("rejected_input", "only valid plans are optimized; repair restores feasibility first", plan=plan, validation=initial)

    before = sequence_cost(plan, config)
    ops = plan.operations
    n = len(ops)
    ctx = ValidationContext(component, catalogue, validation_config)
    idx = {op.operation_id: i for i, op in enumerate(ops)}
    pairs = required_order_pairs(plan, ctx)

    # Eligible (machine, tool) pairs per operation; the current pair is always first.
    options: list[list[tuple[str, str]]] = []
    for op in ops:
        current = (op.machine_id, op.tool_id)
        others = [(o["machine_id"], o["tool_id"]) for o in ctx.resource_options(op.type)] if config.reassign_resources else []
        options.append([current] + [o for o in others if o != current])

    m = cp_model.CpModel()
    choose = [[m.NewBoolVar(f"a{i}_{k}") for k in range(len(options[i]))] for i in range(n)]
    for i in range(n):
        m.AddExactlyOne(choose[i])
    machines = sorted({mt[0] for opts in options for mt in opts})
    tools = sorted({mt[1] for opts in options for mt in opts})
    # Sequence as a Hamiltonian circuit through a depot node n; pos[i] is the 0-based position.
    pos = [m.NewIntVar(0, n - 1, f"pos{i}") for i in range(n)]
    arcs, arc = [], {}
    for i in range(n + 1):
        for j in range(n + 1):
            if i != j:
                lit = m.NewBoolVar(f"x{i}_{j}")
                arcs.append((i, j, lit))
                arc[i, j] = lit
    m.AddCircuit(arcs)
    for j in range(n):
        m.Add(pos[j] == 0).OnlyEnforceIf(arc[n, j])
        for i in range(n):
            if i != j:
                m.Add(pos[j] == pos[i] + 1).OnlyEnforceIf(arc[i, j])
    # Sorted: ``pairs`` is a set, whose order depends on Python's per-process hash seed. Constraint order
    # changes which of several equally good solutions CP-SAT returns, so unsorted it is not reproducible.
    for a, b in sorted(pairs):
        m.Add(pos[idx[a]] < pos[idx[b]])

    # Integer code of each op's chosen machine and tool, linked to the choice literals.
    def code_var(i: int, which: int, values: list[str], name: str) -> Any:
        var = m.NewIntVar(0, len(values) - 1, f"{name}{i}")
        m.Add(var == sum(values.index(mt[which]) * choose[i][k] for k, mt in enumerate(options[i])))
        return var

    mcode = [code_var(i, 0, machines, "mc") for i in range(n)]
    tcode = [code_var(i, 1, tools, "tc") for i in range(n)]
    machine_options = [{mt[0] for mt in opts} for opts in options]
    tool_options = [{mt[1] for mt in opts} for opts in options]

    def change(i: int, j: int, code: list[Any], opts: list[set[str]], name: str) -> Any:
        """Bool forced to 1 if arc i->j is used and the two ops differ in machine or tool."""
        ch = m.NewBoolVar(f"ch{name}{i}_{j}")
        if not opts[i] & opts[j]:
            m.Add(ch >= arc[i, j])  # they can never share it
            return ch
        same = m.NewBoolVar(f"same{name}{i}_{j}")
        m.Add(code[i] == code[j]).OnlyEnforceIf(same)
        m.Add(ch >= arc[i, j] - same)
        return ch

    machine_changes, tool_changes = [], []
    for i in range(n):
        for j in range(n):
            if i != j:
                machine_changes.append(change(i, j, mcode, machine_options, "m"))
                tool_changes.append(change(i, j, tcode, tool_options, "t"))
    primary = config.machine_change_weight * sum(machine_changes) + config.tool_change_weight * sum(tool_changes)
    # Redundant but valid lower bounds: a sequence uses at least as many machines (tools) as the smallest
    # set covering every operation's options, and each one in use costs a segment. They remove no
    # solution; they let CP-SAT prove optimality quickly instead of exploring a flat objective.
    m.Add(sum(machine_changes) >= min_cover_size(machine_options) - 1)
    m.Add(sum(tool_changes) >= min_cover_size(tool_options) - 1)

    displacement = []
    for i in range(n):
        d = m.NewIntVar(0, n, f"d{i}")
        m.AddAbsEquality(d, pos[i] - i)
        displacement.append(d)
    reassigned = sum(1 - choose[i][0] for i in range(n))
    secondary = sum(displacement) + reassigned

    # Lexicographic in two solves: (1) minimum change cost, (2) at that cost, the plan closest to the input.
    # One weighted objective would make the solver prove the tie-break optimal too, which is much slower.
    def solve(objective: Any, limit: float) -> tuple[Any, int]:
        solver = cp_model.CpSolver()
        solver.parameters.max_deterministic_time = limit
        solver.parameters.num_workers = config.num_workers
        solver.parameters.random_seed = config.random_seed
        m.Minimize(objective)
        return solver, solver.Solve(m)

    # Hint the input plan (feasible by construction: it is valid and keeps its own resources).
    for i in range(n):
        m.AddHint(pos[i], i)
        m.AddHint(choose[i][0], 1)
    solver, status = solve(primary, config.deterministic_time_limit)
    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return done("solver_failed", f"CP-SAT returned {status_name}", solver_status=status_name, plan=plan, before=before, validation=initial)
    best = round(solver.ObjectiveValue())
    m.ClearHints()
    for i in range(n):
        m.AddHint(pos[i], solver.Value(pos[i]))
        for k, v in enumerate(choose[i]):
            m.AddHint(v, solver.Value(v))
    m.Add(primary <= best)
    solver2, status2 = solve(secondary, config.tie_break_time_limit)
    tie_break_status = solver2.StatusName(status2)
    if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solver = solver2  # otherwise keep the phase-1 solution, which has the same cost

    order = sorted(range(n), key=lambda i: solver.Value(pos[i]))
    new_ops, changes = [], []
    for i in order:
        k = next(k for k, v in enumerate(choose[i]) if solver.Value(v))
        machine, tool = options[i][k]
        if (machine, tool) != (ops[i].machine_id, ops[i].tool_id):
            changes.append(f"{ops[i].operation_id}: {ops[i].machine_id}/{ops[i].tool_id} -> {machine}/{tool}")
        new_ops.append(ops[i].model_copy(update={"machine_id": machine, "tool_id": tool}))
    if [o.operation_id for o in new_ops] != plan.sequence:
        changes.insert(0, "sequence: " + " ".join(o.operation_id for o in new_ops))
    candidate = plan.model_copy(update={
        "plan_id": f"{plan.plan_id}_opt",
        "operations": new_ops,
        "assumptions": [*plan.assumptions, (
            f"Sequence optimized by the SCMPA CP-SAT optimizer: minimise {config.machine_change_weight} x machine changes "
            f"+ {config.tool_change_weight} x tool changes, subject to the declared precedence and eligible resources."
        )],
    })
    after = sequence_cost(candidate, config)
    if after.cost >= before.cost:
        return done("unchanged", "the input plan is already optimal for this objective", solver_status=status_name, tie_break_status=tie_break_status,
                    plan=plan, before=before, after=before, validation=initial)

    validation = validate_plan(candidate, component, catalogue, validation_config)
    if not validation.valid:  # defensive: the model encodes R3/R5/R9, so this should not happen
        return done("rejected_output", "optimized plan failed revalidation; input plan kept", solver_status=status_name, tie_break_status=tie_break_status,
                    plan=plan, before=before, validation=validation)
    return done("optimized", solver_status=status_name, tie_break_status=tie_break_status, plan=candidate, before=before, after=after, changes=changes,
                diff=plan_diff(plan, candidate), validation=validation)
