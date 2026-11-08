"""Milestone 6: the CP-SAT sequence optimizer (H3).

Optimality is checked against an independent brute force: every precedence-feasible
order, each with the best (machine, tool) assignment found by dynamic programming.
"""

from __future__ import annotations

import itertools
import random

import pytest

pytest.importorskip("ortools", reason="ortools not installed (pip install -e .[opt])")

from scmpa.io import EXAMPLE_COMPONENTS_DIR, REFERENCE_PLANS_DIR, REPO_ROOT, load_catalogue, load_component, load_plan
from scmpa.optimization import OptimizationConfig, optimize_sequence, sequence_cost
from scmpa.optimization.sequence_optimizer import min_cover_size
from scmpa.validation import validate_plan
from scmpa.validation.context import ValidationContext
from scmpa.validation.rules.precedence import required_order_pairs

CATALOGUE = load_catalogue()
BENCH = REPO_ROOT / "data" / "synthetic" / "benchmark_v1"


def example(cid: str):
    return load_component(EXAMPLE_COMPONENTS_DIR / f"{cid}.json", CATALOGUE), load_plan(REFERENCE_PLANS_DIR / f"{cid}_ref.json")


def synthetic(cid: str):
    return load_component(BENCH / "components" / f"{cid}.json", CATALOGUE), load_plan(BENCH / "reference_plans" / f"{cid}_ref.json")


def brute_force_cost(plan, component, cfg: OptimizationConfig) -> int:
    ctx = ValidationContext(component, CATALOGUE)
    ops = plan.operations
    pairs = required_order_pairs(plan, ctx)
    opts = [
        list(dict.fromkeys([(o.machine_id, o.tool_id)] + ([(r["machine_id"], r["tool_id"]) for r in ctx.resource_options(o.type)] if cfg.reassign_resources else [])))
        for o in ops
    ]
    best = None
    for perm in itertools.permutations(range(len(ops))):
        where = {ops[i].operation_id: p for p, i in enumerate(perm)}
        if any(where[a] >= where[b] for a, b in pairs):
            continue
        # DP over the order: cost[k] = best cost ending with option k of the current op.
        cost = {k: 0 for k in range(len(opts[perm[0]]))}
        for prev, cur in zip(perm, perm[1:]):
            cost = {
                k: min(c + cfg.machine_change_weight * (opts[prev][j][0] != mt[0]) + cfg.tool_change_weight * (opts[prev][j][1] != mt[1])
                       for j, c in cost.items())
                for k, mt in enumerate(opts[cur])
            }
        total = min(cost.values())
        best = total if best is None else min(best, total)
    return best


CASES = [("example", c) for c in ("demo_bracket_001", "demo_plate_002", "demo_block_003")] + [
    ("synthetic", c) for c in ("syn_003", "syn_005", "syn_006", "syn_007", "syn_009", "syn_016")
]


def load_case(kind: str, cid: str):
    return example(cid) if kind == "example" else synthetic(cid)


@pytest.mark.parametrize("reassign", [False, True])
@pytest.mark.parametrize("kind,cid", CASES)
def test_optimum_matches_brute_force(kind: str, cid: str, reassign: bool) -> None:
    component, plan = load_case(kind, cid)
    if len(plan.operations) > 8:
        pytest.skip("too many operations for brute force")
    cfg = OptimizationConfig(reassign_resources=reassign)
    result = optimize_sequence(plan, component, CATALOGUE, cfg)
    assert result.status in ("optimized", "unchanged") and result.solver_status == "OPTIMAL"
    assert result.after.cost == brute_force_cost(plan, component, cfg)
    assert result.after.cost <= result.before.cost


@pytest.mark.parametrize("kind,cid", CASES)
def test_optimized_plan_is_valid_and_only_reorders_or_reassigns(kind: str, cid: str) -> None:
    component, plan = load_case(kind, cid)
    result = optimize_sequence(plan, component, CATALOGUE)
    assert validate_plan(result.plan, component, CATALOGUE).valid
    before = {o.operation_id: o for o in plan.operations}
    for op in result.plan.operations:
        old = before[op.operation_id]
        assert (op.type, op.target_features, op.duration_min) == (old.type, old.target_features, old.duration_min)
    assert sorted(result.plan.sequence) == sorted(plan.sequence)
    assert result.plan.precedence == plan.precedence
    assert sum(o.duration_min for o in result.plan.operations) == sum(o.duration_min for o in plan.operations)


def test_sequence_only_mode_keeps_resources() -> None:
    component, plan = synthetic("syn_002")
    result = optimize_sequence(plan, component, CATALOGUE, OptimizationConfig(reassign_resources=False))
    assert result.status == "optimized"
    assert {(o.operation_id, o.machine_id, o.tool_id) for o in result.plan.operations} == {
        (o.operation_id, o.machine_id, o.tool_id) for o in plan.operations
    }


def test_reassignment_can_beat_reordering() -> None:
    component, plan = synthetic("syn_006")
    order_only = optimize_sequence(plan, component, CATALOGUE, OptimizationConfig(reassign_resources=False))
    reassign = optimize_sequence(plan, component, CATALOGUE, OptimizationConfig(reassign_resources=True))
    assert reassign.after.cost < order_only.after.cost
    assert any("->" in c and "/" in c for c in reassign.changes)


def test_invalid_input_is_refused_not_repaired() -> None:
    component, plan = example("demo_bracket_001")
    broken = plan.model_copy(update={"operations": [plan.operations[0].model_copy(update={"tool_id": "T3"}), *plan.operations[1:]]})
    result = optimize_sequence(broken, component, CATALOGUE)
    assert result.status == "rejected_input" and result.plan == broken and not result.validation.valid


def test_already_optimal_plan_is_returned_unchanged() -> None:
    component, plan = example("demo_bracket_001")  # one machine; F1 first; OP2/OP3 use different tools anyway
    result = optimize_sequence(plan, component, CATALOGUE)
    assert result.status == "unchanged" and result.plan == plan and result.diff is None


def test_weights_change_the_objective() -> None:
    component, plan = synthetic("syn_002")
    tools_only = optimize_sequence(plan, component, CATALOGUE, OptimizationConfig(machine_change_weight=0, tool_change_weight=1))
    machines_only = optimize_sequence(plan, component, CATALOGUE, OptimizationConfig(machine_change_weight=1, tool_change_weight=0))
    assert tools_only.after.tool_changes <= machines_only.after.tool_changes
    assert machines_only.after.machine_changes <= tools_only.after.machine_changes


def test_result_is_deterministic() -> None:
    component, plan = synthetic("syn_010")
    a = optimize_sequence(plan, component, CATALOGUE)
    b = optimize_sequence(plan, component, CATALOGUE)
    assert a.plan == b.plan and a.after == b.after


def test_sequence_cost_counts_consecutive_changes() -> None:
    component, plan = example("demo_plate_002")
    c = sequence_cost(plan, OptimizationConfig(machine_change_weight=10, tool_change_weight=1))
    ops = plan.operations
    assert c.machine_changes == sum(a.machine_id != b.machine_id for a, b in zip(ops, ops[1:]))
    assert c.cost == 10 * c.machine_changes + c.tool_changes


def test_min_cover_size() -> None:
    assert min_cover_size([{"M1"}, {"M1", "M2"}, {"M2", "M3"}]) == 2
    assert min_cover_size([{"A", "B"}, {"B"}, {"B", "C"}]) == 1
    assert min_cover_size([]) == 0


@pytest.mark.parametrize("cid", ["syn_001", "syn_002", "syn_007", "syn_010", "syn_013"])
def test_required_order_pairs_agree_with_r9(cid: str) -> None:
    """Property: a random order has no R9 violation iff it respects every required pair."""
    component, plan = synthetic(cid)
    ctx = ValidationContext(component, CATALOGUE)
    pairs = required_order_pairs(plan, ctx)
    rng = random.Random(cid)
    for _ in range(200):
        ops = plan.operations[:]
        rng.shuffle(ops)
        shuffled = plan.model_copy(update={"operations": ops})
        where = {o.operation_id: i for i, o in enumerate(ops)}
        respects = all(where[a] < where[b] for a, b in pairs)
        r9 = [v for v in validate_plan(shuffled, component, CATALOGUE).hard_constraint_violations if v.rule_id == "R9_PRECEDENCE_ORDER"]
        assert respects == (not r9)


def test_optimize_results_on_mock_experiment(tmp_path, monkeypatch) -> None:
    """End to end on a tiny mock experiment: every optimized plan stays valid, nothing gets worse."""
    import json

    import scmpa.evaluation.optimize_results as opt_eval

    monkeypatch.setattr(opt_eval, "SENSITIVITY_WEIGHTS", [(1, 1)])  # keep the test fast; the CLI runs all settings

    from scmpa.evaluation.optimize_results import run as optimize_experiment
    from scmpa.evaluation.run_experiments import ExperimentConfig, run_experiment

    out_dir = str(tmp_path.relative_to(REPO_ROOT)) if tmp_path.is_relative_to(REPO_ROOT) else str(tmp_path)
    cfg = ExperimentConfig(experiment_id="t_opt", split="test", limit=2, seeds=[0], tracks=["generation", "corruption"],
                           systems=["B0", "B1", "R"], planner={"provider": "mock", "faults": ["incompatible_tool"]}, output_dir=out_dir)
    exp = run_experiment(cfg, log=lambda m: None)
    report = optimize_experiment(exp, log=lambda m: None)
    rows = [json.loads(line) for line in (exp / "optimization.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows and all(r["valid_after"] for r in rows)
    assert all(r["after_cost"] <= r["before_cost"] for r in rows)
    assert {r["system"] for r in rows} >= {"R+opt", "REF+opt"}
    assert "Weight sensitivity" in report.read_text(encoding="utf-8")
