"""Render representative before/after cases from stored run records into docs/examples.md.

    python scripts/make_examples.py

Every table is generated from the run records in reports/experiments/, so the
examples cannot drift from the data (spec section 8.3: "representative
before/after examples with the exact violation and repair history").
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scmpa.io import load_catalogue, read_json, validate_component  # noqa: E402
from scmpa.optimization import OptimizationConfig, optimize_sequence  # noqa: E402
from scmpa.schemas import ProcessPlan, ValidationResult  # noqa: E402
from scmpa.workflow import RunRecord, load_run  # noqa: E402

EXP = ROOT / "reports" / "experiments"
BENCH = ROOT / "data" / "synthetic" / "benchmark_v1"
CATALOGUE = load_catalogue()

CASES = [
    (
        "A spot-drill-only hole, repaired under rule set v1.2",
        "llm_test_full_gemma3-4b_v1.2", "syn_019_generation__B2__syn_019__s0.json",
        "gemma gives hole F6 only a spot drill, and no machine on this part can spot drill. Under v1.1 this went "
        "straight to human review, because removing the step would 'uncover' the hole. Under v1.2 the validator says "
        "the hole still needs drilling, and that the spot step can be removed. The repair agent does both, and the plan is accepted.",
    ),
    (
        "A repair that claims changes it did not make",
        "llm_test_full_gemma3-4b_v1.2", "syn_001_generation__B2__syn_001__s0.json",
        "Repair 1 adds the missing drilling steps but places them after the tapping and reaming they must precede (R9). "
        "In repair 2, the agent's notes claim a fix, but the computed diff shows the plan did not change. "
        "Repeated-plan detection stops the loop, and the case goes to human review. Reading only the model's text, a "
        "reviewer would believe the plan had been fixed. This happened in 24 of 121 gemma repair calls and 1 of 66 qwen calls (H4).",
    ),
    (
        "An infeasible part, routed to human review without a repair attempt",
        "llm_test_full_qwen3.5-9b", "syn_008_generation__B2__syn_008__s0.json",
        "syn_008 is infeasible by design: one required operation has no capable resource. The validator marks that "
        "violation non-repairable, so the loop stops at once instead of spending its repair budget.",
    ),
    (
        "A false failure: a realistic step the rule set does not allow",
        "llm_test_full_qwen3.5-9b", "syn_018_generation__B2__syn_018__s0.json",
        "qwen spot drills the pocket F3, plausibly to mark an entry point. The catalogue does not list spot drilling as "
        "suitable for pockets, so the validator rejects it and the repair removes the step. The plan was arguably fine. "
        "The cost here is one needless edit, not a wrong routing. See the false-failure audit in results.md.",
    ),
]


def plan_table(plan: ProcessPlan, validation: ValidationResult | None) -> list[str]:
    issues: dict[str, list[str]] = {}
    for v in (validation.hard_constraint_violations if validation else []):
        issues.setdefault(v.operation_id or "", []).append(v.rule_id.split("_")[0])
    rows = ["| # | Op | Type | Targets | Machine | Tool | Issues |", "|---|---|---|---|---|---|---|"]
    for i, o in enumerate(plan.operations, 1):
        rows.append(f"| {i} | {o.operation_id} | {o.type} | {', '.join(o.target_features)} | {o.machine_id} | {o.tool_id} | {', '.join(issues.get(o.operation_id, [])) or ''} |")
    return rows


def violations(validation: ValidationResult) -> list[str]:
    out = []
    for v in validation.hard_constraint_violations:
        where = v.operation_id or v.feature_id or ""
        out.append(f"- **{v.rule_id}** ({where}{'' if v.repairable else ', not repairable'}): {v.message}")
    return out or ["- none: the plan is valid"]


def diff_summary(diff: dict | None) -> str:
    if not diff:
        return "no plan"
    parts = []
    if diff["added"]:
        parts.append(f"added {', '.join(diff['added'])}")
    if diff["removed"]:
        parts.append(f"removed {', '.join(diff['removed'])}")
    for op, fields in diff["modified"].items():
        parts.append(f"{op}: " + "; ".join(f"{k} {a} → {b}" for k, (a, b) in fields.items()))
    if diff["sequence_changed"]:
        parts.append("sequence changed")
    if diff["precedence_added"] or diff["precedence_removed"]:
        parts.append(f"precedence +{diff['precedence_added']} −{diff['precedence_removed']}")
    return "; ".join(parts) or "**nothing changed**"


def render_run(record: RunRecord) -> list[str]:
    lines = []
    for it in record.iterations:
        title = "Initial plan (planner)" if it.index == 0 else f"Iteration {it.index} (after repair {it.index})"
        lines += [f"**{title}**: {'valid' if it.validation.valid else f'{len(it.validation.hard_constraint_violations)} hard violation(s)'}", ""]
        if it.repair:
            lines += ["Repair agent's own change notes:", *[f"> {c}" for c in it.repair.changes or ["(none)"]], "",
                      f"Computed diff (the audit record): {diff_summary(it.repair.diff)}", ""]
        lines += plan_table(it.plan, it.validation) + [""] + violations(it.validation) + [""]
    lines += [f"**Outcome:** {record.final_status}, stop reason `{record.stop_reason}`. {record.stop_detail}".strip(), ""]
    return lines


def optimizer_case() -> list[str]:
    exp, run_file = "llm_test_full_qwen3.5-9b", "syn_013_generation__validate_only__syn_013__s0.json"
    record = load_run(EXP / exp / "runs" / run_file)
    component = validate_component(read_json(BENCH / "components" / f"{record.component_id}.json"), CATALOGUE)
    result = optimize_sequence(record.final_plan, component, CATALOGUE, OptimizationConfig())
    b, a = result.before, result.after
    return [
        "## 5. The optimizer on a valid plan (M6, B3)", "",
        f"`{exp}` / `{run_file}`: qwen's plan for {record.component_id} was valid as generated. The optimizer reorders it "
        "and reassigns eligible resources to cut machine and tool changes. Precedence and eligibility are hard constraints, "
        "and the validator re-checks the result.", "",
        "**Before**", "", *plan_table(record.final_plan, None), "",
        "**After**", "", *plan_table(result.plan, None), "",
        f"Machine changes {b.machine_changes} → {a.machine_changes}, tool changes {b.tool_changes} → {a.tool_changes}, "
        f"cost {b.cost} → {a.cost}. Solver: {result.solver_status}. Revalidated: {'valid' if result.validation.valid else 'INVALID'}.", "",
        "Changes:", *[f"- {c}" for c in result.changes], "",
    ]


def main() -> int:
    lines = [
        "# Representative cases",
        "",
        "Generated by `python scripts/make_examples.py` from the stored run records, so these tables match the data. "
        "All data is synthetic. The validator is the authority, and the repair agent's notes are shown only to compare them with the computed diff.",
        "",
    ]
    for n, (title, exp, run_file, why) in enumerate(CASES, 1):
        record = load_run(EXP / exp / "runs" / run_file)
        lines += [f"## {n}. {title}", "", f"`{exp}` / `{run_file}`", "", why, "", *render_run(record)]
    lines += optimizer_case()
    out = ROOT / "docs" / "examples.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
