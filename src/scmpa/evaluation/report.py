"""Build summary tables (and an optional chart) from saved experiment results.

    python -m scmpa.evaluation.report reports/experiments/<experiment_id>

Reads only ``results.jsonl`` + ``config.json`` + ``environment.json``, so a report can be
regenerated at any time without re-running models.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from scmpa.evaluation.metrics import aggregate

SYSTEM_LABELS = {
    "B0": "B0 LLM-only (unchecked)",
    "B1": "B1 + validator",
    "B2": "B2 + LLM repair loop",
    "R": "R rule-based repair (non-AI reference)",
}
SYSTEM_ORDER = ["B0", "B1", "B2", "R"]

# Chart tokens (reference palette, light mode).
SURFACE, INK, INK_2, GRID, SERIES_1 = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#2a78d6"


def load_rows(out: Path) -> list[dict[str, Any]]:
    with (out / "results.jsonl").open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def summarise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["track"], r["system"]), []).append(r)
    order = lambda k: (k[0], SYSTEM_ORDER.index(k[1]) if k[1] in SYSTEM_ORDER else 99)  # noqa: E731
    return [{"track": t, "system": s, **aggregate(groups[(t, s)])} for t, s in sorted(groups, key=order)]


def _flatten(summary: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for k, v in summary.items():
        if isinstance(v, dict):
            for sub, val in v.items():
                flat[f"{k}.{sub}"] = val
        else:
            flat[k] = v
    return flat


def _pct(stat: dict[str, Any] | None, ci: bool = False) -> str:
    if not stat or stat.get("rate") is None:
        return "–"
    s = f"{stat['rate']:.0%} ({stat['k']}/{stat['n']})"
    if ci:
        s += f" [{stat['ci_low']:.0%}–{stat['ci_high']:.0%}]"
    return s


def _num(v: float | None, fmt: str = "{:.2f}") -> str:
    return "–" if v is None else fmt.format(v)


def render_markdown(summaries: list[dict[str, Any]], rows: list[dict[str, Any]], config: dict[str, Any], env: dict[str, Any]) -> str:
    lines = [
        f"# Experiment `{config['experiment_id']}`",
        "",
        config.get("description") or "",
        "",
        f"- Benchmark: `{env.get('benchmark_id')}` (manifest sha256 `{env.get('benchmark_manifest_sha256')}`), split **{config['split']}**, "
        f"{env.get('n_cases_selected')} components, seeds {config['seeds']}",
        f"- Planner: `{json.dumps(config['planner'])}`; LLM repair (B2): `{json.dumps(config.get('llm_repair'))}`; max repairs {config['max_repairs']}",
        f"- Rule set {env.get('rule_set_version')}, catalogue `{env.get('catalogue_id')}`"
        + (f" (sha256 `{env['catalogue_sha256']}`)" if env.get("catalogue_sha256") else "")
        + f", scmpa {env.get('scmpa_version')}, Python {env.get('python')}",
        *(
            [f"- Initial plans **replayed** from experiment `{config['initial_plans_from']}` (no new planner calls), "
             "so differences from that experiment come only from validation and repair."]
            if config.get("initial_plans_from") else []
        ),
        "- **All data is synthetic.** These results describe software behaviour on a toy benchmark, not industrial performance.",
        "- R is a deterministic rule-based repair agent included as a reference point. It is not an AI result.",
        "",
    ]
    for track in sorted({s["track"] for s in summaries}):
        lines += [f"## Track: {track}", ""]
        if track == "corruption":
            lines += ["Initial plans are reference plans with injected faults, so this track measures repair independently of planner quality. B0 is not applicable.", ""]
        lines += [
            "| System | Cases | Planner failures | Hard-violation rate [95% CI] | Repair success | Coverage | Precedence acc. | Seq. similarity | Human-review recall | Human-review precision | Correct outcome | Invalid plan accepted | Mean latency (s) |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for s in (s for s in summaries if s["track"] == track):
            lines.append(
                f"| {SYSTEM_LABELS.get(s['system'], s['system'])} | {s['n_cases']} | {_pct(s['planner_failure'])} | "
                f"{_pct(s['hard_violation_rate'], ci=True)} | {_pct(s['repair_success'])} | {_num(s['mean_feature_coverage'])} | "
                f"{_num(s['mean_precedence_accuracy'])} | {_num(s['mean_sequence_similarity'])} | {_pct(s['human_review_recall'])} | "
                f"{_pct(s['human_review_precision'])} | {_pct(s['correct_outcome'])} | {_pct(s['invalid_plan_accepted'])} | "
                f"{_num(s['mean_latency_s'], '{:.1f}')} |"
            )
        lines.append("")
        sd = [(s["system"], s["hard_violation_rate_seed_sd"]) for s in summaries if s["track"] == track and s["hard_violation_rate_seed_sd"] is not None]
        if sd:
            lines += ["Spread across seeds (SD of the per-seed hard-violation rate): " + ", ".join(f"{k} {v:.2f}" for k, v in sd), ""]
        it = [(s["system"], s["repair_iterations_mean"], s["repair_iterations_median"]) for s in summaries if s["track"] == track and s["repair_iterations_mean"] is not None]
        if it:
            lines += ["Repair rounds among repaired cases (mean / median): " + ", ".join(f"{k} {m:.2f} / {md:g}" for k, m, md in it), ""]

        track_rows = [r for r in rows if r["track"] == track]
        initial: Counter = Counter()
        affected: Counter = Counter()
        unique_cases = list({(r["component_id"], r["seed"]): r for r in track_rows}.values())
        for r in unique_cases:
            initial.update(r["initial_violations_by_rule"])
            affected.update(r["initial_violations_by_rule"].keys())
        if initial:
            lines += [f"Initial hard violations by rule, over {len(unique_cases)} initial plans:", "",
                      "| Rule | Violations | Plans affected |", "|---|---|---|"]
            lines += [f"| {k} | {v} | {affected[k]} |" for k, v in sorted(initial.items(), key=lambda kv: (-affected[kv[0]], kv[0]))]
            lines.append("")
        stops = Counter((r["system"], r["stop_reason"]) for r in track_rows if r["system"] != "B0")
        if stops:
            lines += ["Stop reasons:", "", "| System | Stop reason | Count |", "|---|---|---|"]
            lines += [f"| {s} | {reason} | {n} |" for (s, reason), n in sorted(stops.items())]
            lines.append("")
    lines += [
        "## How to read this",
        "",
        "- **Hard-violation rate**: share of cases whose final plan breaks at least one hard rule. A planner failure counts as invalid.",
        "- **Repair success**: share of initially invalid cases that end valid. This includes infeasible components, which cannot become valid by design.",
        "- **Correct outcome**: a feasible component ends with a valid plan, or an infeasible component is routed to human review.",
        "- **Sequence similarity** compares the plan with one generated reference plan. Other valid orders exist, so this is descriptive only.",
        "- The validator can mark a plan valid that is wrong in ways it does not model (tool size, access, setups). See `docs/assumptions_and_limits.md`.",
        "",
    ]
    return "\n".join(lines)


def plot_violation_rates(summaries: list[dict[str, Any]], path: Path) -> bool:
    """Small multiples (one panel per track): final hard-violation rate per system with 95% CI. Returns False without matplotlib."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    tracks = sorted({s["track"] for s in summaries})
    n_slots = max(sum(1 for s in summaries if s["track"] == t) for t in tracks)
    fig, axes = plt.subplots(1, len(tracks), figsize=(5.2 * len(tracks), 0.55 * 4 + 1.6), squeeze=False, facecolor=SURFACE)
    for ax, track in zip(axes[0], tracks):
        items = [s for s in summaries if s["track"] == track]
        labels = [s["system"] for s in items]
        rates = [s["hard_violation_rate"]["rate"] or 0 for s in items]
        lo = [max(0.0, r - (s["hard_violation_rate"]["ci_low"] or 0)) for r, s in zip(rates, items)]
        hi = [max(0.0, (s["hard_violation_rate"]["ci_high"] or 0) - r) for r, s in zip(rates, items)]
        y = [n_slots - 1 - i for i in range(len(items))]  # same row slots in every panel, top-aligned
        ax.set_facecolor(SURFACE)
        ax.barh(y, rates, height=0.5, color=SERIES_1, zorder=2)
        ax.errorbar(rates, y, xerr=[lo, hi], fmt="none", ecolor=INK_2, elinewidth=1.2, capsize=3, zorder=3)
        for yi, r, s in zip(y, rates, items):
            ax.text(max(r, s["hard_violation_rate"]["ci_high"] or r) + 0.025, yi, f"{r:.0%}", va="center", color=INK, fontsize=9)
        ax.set_yticks(y, labels, color=INK)
        ax.set_xlim(0, 1.15)
        ax.set_ylim(-0.6, n_slots - 0.4)
        ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"], color=INK_2, fontsize=8)
        ax.grid(axis="x", color=GRID, linewidth=0.8, zorder=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(length=0)
        ax.set_title(f"{track} track", color=INK, fontsize=10, loc="left")
    fig.suptitle("Final plans with ≥1 hard violation (95% Wilson CI)", color=INK, fontsize=11, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return True


def build_report(out: str | Path) -> dict[str, Path]:
    """Write summary.json/.csv/.md, violations_by_rule.csv and (if possible) a PNG chart into ``out``."""
    out = Path(out)
    rows = load_rows(out)
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    env = json.loads((out / "environment.json").read_text(encoding="utf-8")) if (out / "environment.json").exists() else {}
    summaries = summarise(rows)
    paths = {"summary_json": out / "summary.json", "summary_csv": out / "summary.csv", "summary_md": out / "summary.md",
             "violations_csv": out / "violations_by_rule.csv"}
    paths["summary_json"].write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    flat = [_flatten(s) for s in summaries]
    if flat:
        with paths["summary_csv"].open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(flat[0]))
            writer.writeheader()
            writer.writerows(flat)
    with paths["violations_csv"].open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["track", "system", "stage", "rule_id", "count"])
        counts: Counter = Counter()
        for r in rows:
            for stage in ("initial", "final"):
                for rule, n in r[f"{stage}_violations_by_rule"].items():
                    counts[(r["track"], r["system"], stage, rule)] += n
        for key, n in sorted(counts.items()):
            writer.writerow([*key, n])
    paths["summary_md"].write_text(render_markdown(summaries, rows, config, env), encoding="utf-8")
    chart = out / "hard_violation_rate.png"
    if plot_violation_rates(summaries, chart):
        paths["chart"] = chart
    return paths


if __name__ == "__main__":
    for name, p in build_report(sys.argv[1]).items():
        print(f"{name}: {p}")
