"""Reproducible experiment runner: B0 / B1 / B2 (and rule-based reference R) on a fixed benchmark.

    python -m scmpa.evaluation.run_experiments --config configs/experiments/pilot_mock.json

Design
------
* **Paired comparison.** Per (component, seed) the planner is called **once**.
  All systems start from that same initial plan and differ only in what happens
  next, so differences between systems are not planner noise.
* **Systems.** B0: initial plan, not checked. B1: validated, never repaired
  (``max_repairs=0``). B2: LLM repair loop. R: deterministic rule-based repair,
  a non-AI reference; never report it as an AI result.
* **Tracks.** ``generation``: initial plans from the configured planner.
  ``corruption``: initial plans are reference plans with seeded injected faults,
  which measures repair independently of planner quality (feasible components only).
* **Resumable.** Every planner result and run record is cached as JSON under
  ``<output_dir>/<experiment_id>/``. Re-running skips finished cases.
* **Re-scoring.** ``initial_plans_from`` replays the initial plans of an earlier
  experiment instead of calling the planner, so a rule-set or loop change can be
  measured on exactly the same plans (a paired comparison across experiments).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import random
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

import scmpa
from scmpa.io import DEFAULT_CATALOGUE_PATH, REPO_ROOT, load_catalogue, load_plan, read_json, validate_component
from scmpa.planning import FAULT_KINDS, FaultNotApplicable, PlanResult, inject_fault, make_planner
from scmpa.repair import make_repair_agent
from scmpa.schemas import Catalogue, Component, ProcessPlan
from scmpa.schemas.base import StrictModel
from scmpa.validation import RULE_SET_VERSION
from scmpa.evaluation.metrics import (
    coverage_ratio,
    precedence_accuracy,
    sequence_similarity,
    violations_by_rule,
)
from scmpa.workflow import RunRecord, load_run, save_run, solve

System = Literal["B0", "B1", "B2", "R"]
Track = Literal["generation", "corruption"]

#: Faults used in the corruption track by default (R8 cycle and R1 included; all have expected rules).
DEFAULT_CORRUPTION_FAULTS = sorted(FAULT_KINDS)


class ExperimentConfig(StrictModel):
    """Frozen description of one experiment. Saved next to its results."""

    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    description: str = ""
    benchmark_dir: str = "data/synthetic/benchmark_v1"
    split: Literal["dev", "test", "all"] = "test"
    limit: int | None = None
    seeds: list[int] = Field(default_factory=lambda: [0], min_length=1)
    tracks: list[Track] = Field(default_factory=lambda: ["generation"], min_length=1)
    systems: list[System] = Field(default_factory=lambda: ["B0", "B1", "R"], min_length=1)
    #: ``{"provider": "mock" | "ollama", ...options passed to make_planner}``
    planner: dict[str, Any] = Field(default_factory=lambda: {"provider": "mock"})
    #: Repair agent for B2: ``{"provider": "ollama", ...OllamaConfig options}``. Required if B2 is run.
    llm_repair: dict[str, Any] | None = None
    max_repairs: int = Field(default=3, ge=0)
    corruption_faults: list[str] = Field(default_factory=lambda: list(DEFAULT_CORRUPTION_FAULTS))
    faults_per_case: int = Field(default=2, ge=1)
    output_dir: str = "reports/experiments"
    #: Experiment ID (under ``output_dir``) whose cached initial plans are replayed instead of
    #: calling the planner. A missing plan there is an error, never a silent new planner call.
    initial_plans_from: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.\-]+$")

    @model_validator(mode="after")
    def _consistent(self) -> ExperimentConfig:
        if "B2" in self.systems and not self.llm_repair:
            raise ValueError("system B2 requires an 'llm_repair' configuration")
        if unknown := sorted(set(self.corruption_faults) - set(FAULT_KINDS)):
            raise ValueError(f"unknown corruption faults: {unknown}")
        if self.initial_plans_from == self.experiment_id:
            raise ValueError("initial_plans_from must name a different experiment")
        return self


#: Config fields that must match for replayed initial plans to mean the same thing.
REPLAY_FIELDS = ("benchmark_dir", "planner", "corruption_faults", "faults_per_case")


def check_replay_source(cfg: ExperimentConfig) -> Path:
    """Return the source ``plans/`` folder, after checking it was produced under a compatible config."""
    src = (REPO_ROOT / cfg.output_dir / cfg.initial_plans_from).resolve()  # type: ignore[operator]
    if not (src / "config.json").exists():
        raise ValueError(f"initial_plans_from: no experiment at {src}")
    source = ExperimentConfig.model_validate_json((src / "config.json").read_text(encoding="utf-8"))
    if diffs := [f for f in REPLAY_FIELDS if getattr(source, f) != getattr(cfg, f)]:
        raise ValueError(f"initial_plans_from={cfg.initial_plans_from!r} used a different {diffs}; its plans are not comparable")
    if missing := sorted(set(cfg.seeds) - set(source.seeds)):
        raise ValueError(f"initial_plans_from={cfg.initial_plans_from!r} has no plans for seeds {missing}")
    return src / "plans"


class FixedPlanner:
    """Replays a stored planner result so every system starts from the same plan."""

    def __init__(self, result: PlanResult) -> None:
        self.result = result
        self.name = result.planner

    def generate_plan(self, component: Component, catalogue: Catalogue, *, plan_id: str | None = None) -> PlanResult:
        return self.result


# --------------------------------------------------------------------------- benchmark loading


def load_benchmark(cfg: ExperimentConfig, catalogue: Catalogue) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return the manifest and the selected cases, each with ``component`` and ``reference`` loaded."""
    bench = (REPO_ROOT / cfg.benchmark_dir).resolve()
    manifest = read_json(bench / "manifest.json")
    selected = [c for c in manifest["cases"] if cfg.split == "all" or c["split"] == cfg.split]
    selected.sort(key=lambda c: c["component_id"])
    if cfg.limit is not None:
        selected = selected[: cfg.limit]
    cases = []
    for c in selected:
        cid = c["component_id"]
        component = validate_component(read_json(bench / "components" / f"{cid}.json"), catalogue, cid)
        ref_path = bench / "reference_plans" / f"{cid}_ref.json"
        cases.append({**c, "component": component, "reference": load_plan(ref_path) if ref_path.exists() else None})
    return manifest, cases


# --------------------------------------------------------------------------- initial plans


def corrupt_reference(reference: ProcessPlan, component: Component, catalogue: Catalogue, cfg: ExperimentConfig, seed: int) -> PlanResult:
    """Inject ``faults_per_case`` distinct-operation faults into the reference plan (deterministic per component+seed)."""
    rng = random.Random(f"{component.component_id}|{seed}")
    kinds = list(cfg.corruption_faults)
    rng.shuffle(kinds)
    plan = reference.model_copy(update={"plan_id": f"{component.component_id}_corrupted_s{seed}", "provenance": None})
    touched: set[str] = set()
    records = []
    for kind in kinds:
        if len(records) == cfg.faults_per_case:
            break
        try:
            plan, record = inject_fault(plan, component, catalogue, kind, rng, exclude_operations=touched)
        except FaultNotApplicable:
            continue
        touched.update(record.operations)
        records.append(record.model_dump())
    return PlanResult(status="ok", plan=plan, planner="corruption", injected_faults=records)


def initial_plan(
    case: dict[str, Any], track: Track, seed: int, cfg: ExperimentConfig, catalogue: Catalogue, cache_dir: Path,
    replay_dir: Path | None = None,
) -> PlanResult:
    cid = case["component_id"]
    name = f"{track}__{cid}__s{seed}.json"
    path = cache_dir / name
    if path.exists():
        return PlanResult.model_validate_json(path.read_text(encoding="utf-8"))
    if replay_dir is not None:
        if not (replay_dir / name).exists():
            raise FileNotFoundError(f"initial_plans_from: {replay_dir / name} is missing (was that experiment finished?)")
        result = PlanResult.model_validate_json((replay_dir / name).read_text(encoding="utf-8"))
    elif track == "generation":
        options = {k: v for k, v in cfg.planner.items() if k != "provider"}
        planner = make_planner(cfg.planner["provider"], seed=seed, **options)
        result = planner.generate_plan(case["component"], catalogue)
    else:
        result = corrupt_reference(case["reference"], case["component"], catalogue, cfg, seed)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result


# --------------------------------------------------------------------------- rows


def _planner_latency_tokens(pr: PlanResult) -> tuple[float, int]:
    lat = sum(a.latency_s or 0 for a in pr.attempts)
    tok = sum((a.prompt_tokens or 0) + (a.completion_tokens or 0) for a in pr.attempts)
    return lat, tok


def _repair_latency_tokens(record: RunRecord) -> tuple[float, int]:
    calls = [it.repair for it in record.iterations if it.repair] + ([record.terminal_repair] if record.terminal_repair else [])
    lat = sum(c.latency_s for c in calls)
    tok = sum((a.prompt_tokens or 0) + (a.completion_tokens or 0) for c in calls for a in c.attempts)
    return lat, tok


def make_row(case: dict[str, Any], track: Track, system: System, seed: int, pr: PlanResult, record: RunRecord, run_file: str) -> dict[str, Any]:
    """One result row. B0 rows are derived from the validate-only record: same plan, but never checked."""
    reference = case["reference"]
    expected = case["expected_outcome"]
    first = record.iterations[0] if record.iterations else None
    p_lat, p_tok = _planner_latency_tokens(pr)

    if system == "B0":
        final_plan, final_val = (first.plan, first.validation) if first else (None, None)
        final_status, stop_reason, repairs, r_lat, r_tok = ("UNCHECKED" if first else "NO_PLAN"), "not_checked", 0, 0.0, 0
    else:
        final_plan, final_val = record.final_plan, record.final_validation
        final_status, stop_reason, repairs = record.final_status, record.stop_reason, record.repairs_used
        r_lat, r_tok = _repair_latency_tokens(record)

    final_valid = bool(final_val and final_val.valid)
    if expected == "feasible":
        correct = final_valid
    else:
        correct = final_status == "NEEDS_HUMAN_REVIEW"
    return {
        "track": track,
        "system": system,
        "component_id": case["component_id"],
        "seed": seed,
        "split": case["split"],
        "expected_outcome": expected,
        "planner_status": pr.status,
        "initial_valid": first.validation.valid if first else None,
        "initial_hard_violations": len(first.validation.hard_constraint_violations) if first else None,
        "initial_violations_by_rule": violations_by_rule(first.validation if first else None),
        "final_valid": final_valid,
        "final_hard_violations": len(final_val.hard_constraint_violations) if final_val else None,
        "final_violations_by_rule": violations_by_rule(final_val),
        "final_coverage": coverage_ratio(final_val) if final_val else None,
        "final_precedence_accuracy": precedence_accuracy(final_plan, reference) if final_plan else None,
        "final_sequence_similarity": sequence_similarity(final_plan, reference) if final_plan else None,
        "final_status": final_status,
        "stop_reason": stop_reason,
        "repairs_used": repairs,
        "correct_outcome": correct,
        "latency_s": round(p_lat + r_lat, 3),
        "tokens": (p_tok + r_tok) or None,
        "injected_faults": [f["kind"] for f in pr.injected_faults],
        "run_file": run_file,
    }


# --------------------------------------------------------------------------- main loop


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def run_experiment(cfg: ExperimentConfig, *, fresh: bool = False, log=print) -> Path:
    """Run (or resume) an experiment; return its output directory."""
    catalogue = load_catalogue()
    replay_dir = check_replay_source(cfg) if cfg.initial_plans_from else None
    out = (REPO_ROOT / cfg.output_dir / cfg.experiment_id).resolve()
    if fresh and out.exists():
        import shutil

        shutil.rmtree(out)
    (out / "plans").mkdir(parents=True, exist_ok=True)
    (out / "runs").mkdir(parents=True, exist_ok=True)

    config_path = out / "config.json"
    if config_path.exists():
        previous = ExperimentConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
        if previous.model_dump(exclude={"limit"}) != cfg.model_dump(exclude={"limit"}):
            raise ValueError(f"{config_path} differs from the given config; use a new experiment_id or --fresh")
    config_path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")

    manifest, cases = load_benchmark(cfg, catalogue)
    bench_dir = (REPO_ROOT / cfg.benchmark_dir).resolve()
    env_path = out / "environment.json"
    if env_path.exists() and any((out / "runs").iterdir()):
        previous_env = json.loads(env_path.read_text(encoding="utf-8"))
        stale = {k: (previous_env.get(k), v) for k, v in {
            "rule_set_version": RULE_SET_VERSION,
            "catalogue_sha256": _sha(DEFAULT_CATALOGUE_PATH),
            "benchmark_manifest_sha256": _sha(bench_dir / "manifest.json"),
        }.items() if previous_env.get(k) != v}
        if stale:
            raise ValueError(
                f"cached runs in {out / 'runs'} were produced with different {stale} (old, new); "
                "delete the runs/ folder (planner outputs in plans/ can be kept) or use --fresh"
            )
    (out / "environment.json").write_text(json.dumps({
        "scmpa_version": scmpa.__version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "rule_set_version": RULE_SET_VERSION,
        "catalogue_id": catalogue.catalogue_id,
        "catalogue_sha256": _sha(DEFAULT_CATALOGUE_PATH),
        "benchmark_id": manifest["benchmark_id"],
        "benchmark_manifest_sha256": _sha(bench_dir / "manifest.json"),
        "n_cases_selected": len(cases),
    }, indent=2), encoding="utf-8")

    repair_agents = {"R": make_repair_agent("rule_based")}
    if cfg.llm_repair:
        options = {k: v for k, v in cfg.llm_repair.items() if k != "provider"}
        repair_agents["B2"] = make_repair_agent(cfg.llm_repair["provider"], **options)

    rows: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for track in cfg.tracks:
        track_cases = cases if track == "generation" else [c for c in cases if c["reference"] is not None]
        for case in track_cases:
            for seed in cfg.seeds:
                cid = case["component_id"]
                pr = initial_plan(case, track, seed, cfg, catalogue, out / "plans", replay_dir)
                needed = {"validate_only" if s in ("B0", "B1") else s for s in cfg.systems if not (track == "corruption" and s == "B0")}
                records: dict[str, tuple[RunRecord, str]] = {}
                for variant in sorted(needed):
                    run_id = f"{track}__{variant}__{cid}__s{seed}"
                    path = out / "runs" / f"{cid}_{run_id}.json"
                    if path.exists():
                        record = load_run(path)
                    else:
                        agent = None if variant == "validate_only" else repair_agents[variant]
                        record = solve(
                            case["component"], catalogue, FixedPlanner(pr), agent,
                            max_repairs=0 if agent is None else cfg.max_repairs, run_id=run_id,
                        )
                        path = save_run(record, out / "runs")
                    records[variant] = (record, path.relative_to(out).as_posix())
                new_rows = []
                for system in cfg.systems:
                    if track == "corruption" and system == "B0":
                        continue
                    record, rel = records["validate_only" if system in ("B0", "B1") else system]
                    new_rows.append(make_row(case, track, system, seed, pr, record, rel))
                rows += new_rows
                done = ", ".join(f"{r['system']}={'valid' if r['final_valid'] else r['final_status']}" for r in new_rows)
                log(f"[{time.perf_counter() - t0:7.1f}s] {track:<10} {cid} s{seed}: initial_valid={records[next(iter(records))][0].initially_valid} | {done}")

    write_results(rows, out)
    from scmpa.evaluation.report import build_report

    build_report(out)
    log(f"results: {out}")
    return out


def write_results(rows: list[dict[str, Any]], out: Path) -> None:
    """Raw per-case rows as JSONL (lossless) and CSV (dict fields JSON-encoded)."""
    with (out / "results.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    if not rows:
        return
    with (out / "results.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        for r in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in r.items()})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, help="experiment config JSON")
    parser.add_argument("--limit", type=int, help="only the first N components of the split (smoke runs)")
    parser.add_argument("--fresh", action="store_true", help="delete cached results for this experiment first")
    args = parser.parse_args(argv)
    cfg = ExperimentConfig.model_validate(read_json(args.config))
    if args.limit is not None:
        cfg = cfg.model_copy(update={"limit": args.limit})
    run_experiment(cfg, fresh=args.fresh, log=lambda m: print(m, flush=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
