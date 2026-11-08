"""Apply the sequence optimizer to an experiment's accepted plans (B3 and H3).

    python -m scmpa.evaluation.optimize_results reports/experiments/llm_test_full_qwen3.5-9b

This is offline and deterministic: no LLM calls. For every run that ended
ACCEPTED, the final plan is optimized, and the independent validator re-checks
the result. Systems after optimization are labelled ``B3`` (B2 repair loop +
optimizer, as in the spec), ``B1+opt`` (initially valid plans) and ``R+opt``.
Reference plans of the components the experiment ran are included as context (``REF+opt``).

Two optimizer modes are reported: ``order`` (reorder only) and ``order+resources``
(also reassign eligible machine/tool pairs). A weight sensitivity check repeats
the ``order+resources`` mode with other machine:tool weights. Optimization and
repair are reported separately, as the spec requires (section 6.5).

Writes ``optimization.jsonl`` (one row per plan, mode and weight setting) and
``optimization.md`` into the experiment folder.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from scmpa.io import REPO_ROOT, load_catalogue, load_plan, read_json, validate_component
from scmpa.optimization import OptimizationConfig, optimize_sequence
from scmpa.workflow import load_run, stable_plan_hash

SYSTEM_AFTER = {"validate_only": "B1+opt", "B2": "B3", "R": "R+opt", "reference": "REF+opt"}
MODES = {"order": False, "order+resources": True}
MAIN_WEIGHTS = (10, 1)
SENSITIVITY_WEIGHTS = [(1, 1), (1, 10), (10, 1), (100, 1)]


def collect_plans(exp_dir: Path, catalogue) -> list[dict[str, Any]]:
    """Accepted final plans from the run records, plus the split's reference plans."""
    config = read_json(exp_dir / "config.json")
    bench = (REPO_ROOT / config["benchmark_dir"]).resolve()
    components: dict[str, Any] = {}

    def component(cid: str):
        if cid not in components:
            components[cid] = validate_component(read_json(bench / "components" / f"{cid}.json"), catalogue, cid)
        return components[cid]

    items = []
    seen: set[str] = set()  # components the experiment ran (respects split and limit)
    for path in sorted((exp_dir / "runs").glob("*.json")):
        record = load_run(path)
        seen.add(record.component_id)
        if record.final_status != "ACCEPTED" or record.final_plan is None:
            continue
        track, variant, cid, seed = record.run_id.split("__")
        items.append({"track": track, "variant": variant, "component_id": cid, "seed": int(seed.lstrip("s")),
                      "plan": record.final_plan, "component": component(cid)})
    for cid in sorted(seen):
        ref = bench / "reference_plans" / f"{cid}_ref.json"
        if ref.exists():
            items.append({"track": "reference", "variant": "reference", "component_id": cid, "seed": None,
                          "plan": load_plan(ref), "component": component(cid)})
    return items


def optimize_all(items: list[dict[str, Any]], catalogue, log=print) -> list[dict[str, Any]]:
    settings = [(mode, MAIN_WEIGHTS) for mode in MODES] + [("order+resources", w) for w in SENSITIVITY_WEIGHTS if w != MAIN_WEIGHTS]
    cache: dict[tuple, dict[str, Any]] = {}  # identical plans recur across systems (e.g. initially valid plans)
    rows = []
    t0 = time.perf_counter()
    for n, item in enumerate(items, 1):
        for mode, (wm, wt) in settings:
            cfg = OptimizationConfig(machine_change_weight=wm, tool_change_weight=wt, reassign_resources=MODES[mode])
            key = (item["component_id"], stable_plan_hash(item["plan"]), mode, wm, wt)
            if key not in cache:
                r = optimize_sequence(item["plan"], item["component"], catalogue, cfg)
                before = {o.operation_id: (i, o.machine_id, o.tool_id) for i, o in enumerate(item["plan"].operations)}
                cache[key] = {
                    "status": r.status, "solver_status": r.solver_status, "tie_break_status": r.tie_break_status,
                    "valid_after": bool(r.validation and r.validation.valid),
                    "before_machine_changes": r.before.machine_changes if r.before else None,
                    "before_tool_changes": r.before.tool_changes if r.before else None,
                    "before_cost": r.before.cost if r.before else None,
                    "after_machine_changes": r.after.machine_changes if r.after else None,
                    "after_tool_changes": r.after.tool_changes if r.after else None,
                    "after_cost": r.after.cost if r.after else None,
                    "operations": len(item["plan"].operations),
                    "moved": sum(1 for i, o in enumerate(r.plan.operations) if before[o.operation_id][0] != i),
                    "reassigned": sum(1 for o in r.plan.operations if before[o.operation_id][1:] != (o.machine_id, o.tool_id)),
                    "latency_s": r.latency_s,
                }
            rows.append({"track": item["track"], "system": SYSTEM_AFTER[item["variant"]], "component_id": item["component_id"],
                         "seed": item["seed"], "mode": mode, "machine_change_weight": wm, "tool_change_weight": wt, **cache[key]})
        if n % 25 == 0:
            log(f"[{time.perf_counter() - t0:6.1f}s] {n}/{len(items)} plans")
    return rows


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def _fmt(x, f="{:.2f}"):
    return "–" if x is None else f.format(x)


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    keys = sorted({(r["track"], r["system"], r["mode"]) for r in rows if (r["machine_change_weight"], r["tool_change_weight"]) == MAIN_WEIGHTS})
    for track, system, mode in keys:
        g = [r for r in rows if (r["track"], r["system"], r["mode"]) == (track, system, mode)
             and (r["machine_change_weight"], r["tool_change_weight"]) == MAIN_WEIGHTS]
        rel = [1 - r["after_cost"] / r["before_cost"] for r in g if r["before_cost"]]
        out.append({
            "track": track, "system": system, "mode": mode, "plans": len(g),
            "improved": sum(r["status"] == "optimized" for r in g),
            "valid_after": sum(r["valid_after"] for r in g),
            "proven_optimal": sum(r["solver_status"] == "OPTIMAL" for r in g),
            "machine_before": _mean([r["before_machine_changes"] for r in g]), "machine_after": _mean([r["after_machine_changes"] for r in g]),
            "tool_before": _mean([r["before_tool_changes"] for r in g]), "tool_after": _mean([r["after_tool_changes"] for r in g]),
            "cost_before": _mean([r["before_cost"] for r in g]), "cost_after": _mean([r["after_cost"] for r in g]),
            "median_cost_reduction": statistics.median(rel) if rel else None,
            "mean_moved": _mean([r["moved"] for r in g]), "mean_reassigned": _mean([r["reassigned"] for r in g]),
            "max_latency_s": max((r["latency_s"] for r in g), default=None),
        })
    return out


def render(exp_id: str, rows: list[dict[str, Any]], summary: list[dict[str, Any]]) -> str:
    lines = [
        f"# Optimization of accepted plans: `{exp_id}`",
        "",
        "Deterministic CP-SAT sequence optimizer (`scmpa.optimization`), applied after repair to every accepted plan. "
        f"Objective: {MAIN_WEIGHTS[0]} × machine changes + {MAIN_WEIGHTS[1]} × tool changes between consecutive operations. "
        "Hard constraints: declared plan and component precedence, and eligible machine/tool pairs. Every result is re-checked by the validator. "
        "Total duration is a sum of fixed estimates and cannot change. "
        "B3 = B2 + optimizer; REF+opt = the benchmark's reference plans of this split (context, not a system).",
        "",
        "Improvement is non-negative by construction, because the input plan is kept when nothing better exists. "
        "The questions are how large the improvement is and whether validity is preserved.",
        "",
        "| Track | System | Mode | Plans | Improved | Valid after | Proven optimal | Machine changes | Tool changes | Cost | Median cost reduction | Ops moved | Ops reassigned |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summary:
        lines.append(
            f"| {s['track']} | {s['system']} | {s['mode']} | {s['plans']} | {s['improved']} | {s['valid_after']}/{s['plans']} | "
            f"{s['proven_optimal']}/{s['plans']} | {_fmt(s['machine_before'])} → {_fmt(s['machine_after'])} | "
            f"{_fmt(s['tool_before'])} → {_fmt(s['tool_after'])} | {_fmt(s['cost_before'], '{:.1f}')} → {_fmt(s['cost_after'], '{:.1f}')} | "
            f"{_fmt(s['median_cost_reduction'], '{:.0%}')} | {_fmt(s['mean_moved'], '{:.1f}')} | {_fmt(s['mean_reassigned'], '{:.1f}')} |"
        )
    lines += ["", "## Weight sensitivity (order+resources, all accepted LLM-system plans)", "",
              "| Machine : tool weight | Machine changes after | Tool changes after | Plans improved |", "|---|---|---|---|"]
    sys_rows = [r for r in rows if r["mode"] == "order+resources" and r["system"] in ("B1+opt", "B3")]
    before_m = _mean([r["before_machine_changes"] for r in sys_rows if (r["machine_change_weight"], r["tool_change_weight"]) == MAIN_WEIGHTS])
    before_t = _mean([r["before_tool_changes"] for r in sys_rows if (r["machine_change_weight"], r["tool_change_weight"]) == MAIN_WEIGHTS])
    lines.append(f"| (input plans) | {_fmt(before_m)} | {_fmt(before_t)} | – |")
    for wm, wt in SENSITIVITY_WEIGHTS:
        g = [r for r in sys_rows if (r["machine_change_weight"], r["tool_change_weight"]) == (wm, wt)]
        lines.append(f"| {wm} : {wt} | {_fmt(_mean([r['after_machine_changes'] for r in g]))} | "
                     f"{_fmt(_mean([r['after_tool_changes'] for r in g]))} | {sum(r['status'] == 'optimized' for r in g)}/{len(g)} |")
    invalid = [r for r in rows if not r["valid_after"]]
    lines += ["", f"Plans invalid after optimization: **{len(invalid)}** of {len(rows)} optimizer runs.",
              f"Solver statuses: {dict(sorted(_count(r['solver_status'] for r in rows).items()))}; "
              f"tie-break statuses: {dict(sorted(_count(r['tie_break_status'] for r in rows).items()))}.", ""]
    return "\n".join(lines)


def _count(xs) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in xs:
        out[str(x)] = out.get(str(x), 0) + 1
    return out


def run(exp_dir: str | Path, log=print) -> Path:
    exp_dir = Path(exp_dir).resolve()
    catalogue = load_catalogue()
    items = collect_plans(exp_dir, catalogue)
    log(f"{len(items)} accepted/reference plans in {exp_dir.name}")
    rows = optimize_all(items, catalogue, log)
    with (exp_dir / "optimization.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    (exp_dir / "optimization.md").write_text(render(exp_dir.name, rows, summarize(rows)), encoding="utf-8")
    log(f"wrote {exp_dir / 'optimization.md'}")
    return exp_dir / "optimization.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("experiments", nargs="+", help="experiment folders, e.g. reports/experiments/<id>")
    args = parser.parse_args(argv)
    for e in args.experiments:
        run(e, log=lambda m: print(m, flush=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
