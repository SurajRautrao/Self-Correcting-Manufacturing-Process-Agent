"""Milestone 4: benchmark generator, metrics and experiment runner."""

from __future__ import annotations

import json
import shutil

import pytest

from scmpa.evaluation.metrics import aggregate, precedence_accuracy, sequence_similarity, wilson_interval
from scmpa.evaluation.run_experiments import ExperimentConfig, run_experiment
from scmpa.evaluation.synthetic import generate_benchmark
from scmpa.io import EXAMPLE_COMPONENTS_DIR, REFERENCE_PLANS_DIR, REPO_ROOT, load_catalogue, load_component, load_plan, read_json, validate_component
from scmpa.validation import validate_plan

CATALOGUE = load_catalogue()
BENCH = REPO_ROOT / "data" / "synthetic" / "benchmark_v1"


# =========================================================================== synthetic benchmark


def test_generator_is_deterministic(tmp_path) -> None:
    a = generate_benchmark(tmp_path / "a", CATALOGUE, n_components=8, seed=11)
    b = generate_benchmark(tmp_path / "b", CATALOGUE, n_components=8, seed=11)
    assert a == b
    for f in (tmp_path / "a" / "components").iterdir():
        assert f.read_text() == (tmp_path / "b" / "components" / f.name).read_text()


def test_generated_benchmark_invariants(tmp_path) -> None:
    manifest = generate_benchmark(tmp_path, CATALOGUE, n_components=15, seed=5, infeasible_fraction=0.2)
    assert len(manifest["cases"]) == 15
    assert sum(c["expected_outcome"] == "needs_human_review" for c in manifest["cases"]) == 3
    assert set(manifest["split"]["dev"]).isdisjoint(manifest["split"]["test"])
    for c in manifest["cases"]:
        component = validate_component(read_json(tmp_path / "components" / f"{c['component_id']}.json"), CATALOGUE)
        assert component.provenance.source_type == "synthetic"
        assert component.precedence_constraints, "every component declares precedence assumptions"
        ref = tmp_path / "reference_plans" / f"{c['component_id']}_ref.json"
        if c["expected_outcome"] == "feasible":
            assert validate_plan(load_plan(ref), component, CATALOGUE).valid
        else:
            assert not ref.exists() and c["infeasible_reason"]


def test_committed_benchmark_matches_generator(tmp_path) -> None:
    """The checked-in benchmark is exactly what the documented command regenerates."""
    manifest = read_json(BENCH / "manifest.json")
    regenerated = generate_benchmark(tmp_path, CATALOGUE, n_components=manifest["n_components"], seed=manifest["seed"],
                                     infeasible_fraction=manifest["infeasible_fraction"])
    assert regenerated == manifest
    for f in (BENCH / "components").iterdir():
        assert json.loads(f.read_text()) == json.loads((tmp_path / "components" / f.name).read_text())


def test_benchmark_split_has_both_outcomes() -> None:
    manifest = read_json(BENCH / "manifest.json")
    for split in ("dev", "test"):
        outcomes = {c["expected_outcome"] for c in manifest["cases"] if c["split"] == split}
        assert outcomes == {"feasible", "needs_human_review"}


# =========================================================================== metrics


def _bracket():
    return load_component(EXAMPLE_COMPONENTS_DIR / "demo_bracket_001.json", CATALOGUE), load_plan(REFERENCE_PLANS_DIR / "demo_bracket_001_ref.json")


def test_precedence_accuracy_and_similarity_identical() -> None:
    _, ref = _bracket()
    assert precedence_accuracy(ref, ref) == 1.0
    assert sequence_similarity(ref, ref) == 1.0


def test_metrics_on_reordered_plan() -> None:
    _, ref = _bracket()
    swapped = ref.model_copy(update={"operations": [ref.operations[1], ref.operations[0], ref.operations[2]]})
    # reference edges OP1->OP2 and OP1->OP3: one of two now violated
    assert precedence_accuracy(swapped, ref) == 0.5
    # pairs: (F1,F2) discordant, (F1,F3) and (F2,F3) concordant
    assert sequence_similarity(swapped, ref) == pytest.approx(2 / 3)


def test_metrics_ignore_operation_ids() -> None:
    _, ref = _bracket()
    renamed = ref.model_copy(update={
        "operations": [op.model_copy(update={"operation_id": f"X{i}"}) for i, op in enumerate(ref.operations)],
        "precedence": [],
    })
    assert precedence_accuracy(renamed, ref) == 1.0


def test_precedence_accuracy_none_without_reference() -> None:
    _, ref = _bracket()
    assert precedence_accuracy(ref, None) is None
    assert precedence_accuracy(ref, ref.model_copy(update={"precedence": []})) is None


def test_wilson_interval() -> None:
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and 0.25 < hi < 0.35
    lo, hi = wilson_interval(5, 10)
    assert lo < 0.5 < hi
    assert wilson_interval(0, 0) == (None, None)


def _row(**kw):
    base = dict(component_id="c", seed=0, planner_status="ok", initial_valid=False, final_valid=True, final_hard_violations=0,
                final_coverage=1.0, final_precedence_accuracy=None, final_sequence_similarity=None, repairs_used=1,
                final_status="ACCEPTED", expected_outcome="feasible", correct_outcome=True, latency_s=1.0, tokens=None)
    return base | kw


def test_aggregate_rates() -> None:
    rows = [
        _row(component_id="a"),
        _row(component_id="b", final_valid=False, final_hard_violations=2, final_status="NEEDS_HUMAN_REVIEW", correct_outcome=False),
        _row(component_id="c", expected_outcome="needs_human_review", final_valid=False, final_status="NEEDS_HUMAN_REVIEW", correct_outcome=True),
        _row(component_id="d", initial_valid=True, repairs_used=0),
    ]
    s = aggregate(rows)
    assert s["hard_violation_rate"]["k"] == 2 and s["hard_violation_rate"]["n"] == 4
    assert s["repair_success"]["k"] == 1 and s["repair_success"]["n"] == 3
    assert s["repair_success_feasible_only"]["n"] == 2
    assert s["human_review_recall"]["rate"] == 1.0
    assert s["human_review_precision"]["rate"] == 0.5
    assert s["correct_outcome"]["k"] == 3
    assert s["repair_iterations_mean"] == 1.0


# =========================================================================== runner (mock, small)


def test_runner_end_to_end_and_resume(tmp_path) -> None:
    cfg = ExperimentConfig(
        experiment_id="t_runner", split="all", limit=5, seeds=[0, 1], tracks=["generation", "corruption"],
        systems=["B0", "B1", "R"], output_dir=str(tmp_path.relative_to(REPO_ROOT)) if tmp_path.is_relative_to(REPO_ROOT) else str(tmp_path),
    )
    out = run_experiment(cfg, log=lambda m: None)
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
    manifest = read_json(BENCH / "manifest.json")
    selected = sorted(c["component_id"] for c in manifest["cases"])[:5]
    feasible = [c for c in manifest["cases"] if c["component_id"] in selected and c["expected_outcome"] == "feasible"]
    assert len([r for r in rows if r["track"] == "generation"]) == 5 * 2 * 3
    assert len([r for r in rows if r["track"] == "corruption"]) == len(feasible) * 2 * 2  # no B0 in corruption
    # paired design: B0/B1/R share the same initial plan
    by_case = {}
    for r in rows:
        by_case.setdefault((r["track"], r["component_id"], r["seed"]), set()).add(r["initial_hard_violations"])
    assert all(len(v) == 1 for v in by_case.values())
    # corruption: every initial plan is invalid; rule-based repair fixes all
    assert all(r["initial_valid"] is False for r in rows if r["track"] == "corruption")
    assert all(r["final_valid"] for r in rows if r["track"] == "corruption" and r["system"] == "R")
    for name in ("summary.md", "summary.csv", "summary.json", "results.csv", "violations_by_rule.csv", "config.json", "environment.json"):
        assert (out / name).exists(), name

    # resume: identical results without recomputation
    before = (out / "results.jsonl").read_text()
    run_files = sorted(p.stat().st_mtime_ns for p in (out / "runs").iterdir())
    run_experiment(cfg, log=lambda m: None)
    assert (out / "results.jsonl").read_text() == before
    assert sorted(p.stat().st_mtime_ns for p in (out / "runs").iterdir()) == run_files

    # changed config under the same id is refused
    with pytest.raises(ValueError, match="differs"):
        run_experiment(cfg.model_copy(update={"max_repairs": 1}), log=lambda m: None)
    shutil.rmtree(out)


def test_config_requires_llm_repair_for_b2() -> None:
    with pytest.raises(ValueError, match="B2 requires"):
        ExperimentConfig(experiment_id="x", systems=["B0", "B2"])


def test_shipped_configs_are_valid() -> None:
    for path in (REPO_ROOT / "configs" / "experiments").glob("*.json"):
        ExperimentConfig.model_validate(read_json(path))
