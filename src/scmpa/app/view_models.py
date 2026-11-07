"""Pure helpers that turn domain objects into display tables and plain-language text.

Kept free of Streamlit so they can be unit-tested and reused (e.g. in reports).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scmpa.io import DATA_DIR, EXAMPLE_COMPONENTS_DIR, REPO_ROOT, read_json
from scmpa.schemas import Component, ProcessPlan, ValidationResult
from scmpa.validation import ALL_RULES
from scmpa.workflow import RunRecord

STOP_REASON_TEXT: dict[str, str] = {
    "valid": "The plan satisfies every hard rule of the declared rule set.",
    "max_repairs_reached": "The repair budget was used up (or repair was disabled) and hard violations remain.",
    "repeated_plan": "A repair produced a plan identical to an earlier one, so further attempts would loop.",
    "non_repairable_violation": "At least one violation cannot be fixed with the available machines and tools.",
    "repair_agent_requested_review": "The repair agent reported that the data is insufficient and asked for a human.",
    "planner_output_invalid": "The planner did not return a well-formed plan, even after a retry.",
    "repair_output_invalid": "The repair agent did not return a well-formed result.",
}

DISCLAIMER = (
    "Research prototype for decision support. Plans are checked only against a simplified, documented rule set: "
    "tool size, access, collisions, setups and tolerances are not modelled. Nothing shown here is a production-ready "
    "or machine-executable plan."
)


@dataclass(frozen=True)
class ComponentSource:
    label: str
    path: Path
    group: str


def list_component_sources() -> list[ComponentSource]:
    """Hand-written examples first, then the synthetic benchmark (with its expected outcome)."""
    sources = [ComponentSource(p.stem, p, "Examples") for p in sorted(EXAMPLE_COMPONENTS_DIR.glob("*.json"))]
    bench = DATA_DIR / "synthetic" / "benchmark_v1"
    if (bench / "manifest.json").exists():
        manifest = read_json(bench / "manifest.json")
        for case in manifest["cases"]:
            hint = "feasible" if case["expected_outcome"] == "feasible" else "designed infeasible"
            sources.append(ComponentSource(
                f"{case['component_id']} ({case['split']}, {hint}, {case['n_features']} features)",
                bench / "components" / f"{case['component_id']}.json", "Synthetic benchmark",
            ))
    return sources


def feature_rows(component: Component) -> list[dict[str, Any]]:
    rows = []
    for f in component.features:
        dims = ", ".join(f"{k.removesuffix('_mm')} {v:g} mm" for k in ("diameter_mm", "depth_mm", "width_mm", "length_mm") if (v := getattr(f, k)) is not None)
        rows.append({
            "Feature": f.feature_id, "Type": f.type, "Required": "yes" if f.required else "optional",
            "Must receive": ", ".join(f.required_operation_types) if f.required_operation_types else "any suitable operation",
            "Dimensions": dims or "–", "Description": f.description,
        })
    return rows


def machine_rows(component: Component) -> list[dict[str, Any]]:
    return [{"Machine": m.machine_id, "Description": m.description, "Capabilities": ", ".join(m.capabilities)} for m in component.resources.machines]


def tool_rows(component: Component) -> list[dict[str, Any]]:
    return [{"Tool": t.tool_id, "Type": t.type, "Description": t.description or "–"} for t in component.resources.tools]


def precedence_rows(component: Component) -> list[dict[str, Any]]:
    def ref(r) -> str:
        return f"{r.operation_type} on {r.feature_id}" if r.operation_type else f"all work on {r.feature_id}"

    return [{"Before": ref(pc.before), "After": ref(pc.after), "Rationale": pc.rationale} for pc in component.precedence_constraints]


def plan_rows(plan: ProcessPlan, validation: ValidationResult | None = None) -> list[dict[str, Any]]:
    """One row per operation in sequence order, with the number of hard violations touching it."""
    issues: dict[str, int] = {}
    if validation:
        for v in validation.hard_constraint_violations:
            if v.operation_id:
                issues[v.operation_id] = issues.get(v.operation_id, 0) + 1
    return [
        {
            "#": i + 1, "Operation": op.operation_id, "Type": op.type, "Targets": ", ".join(op.target_features),
            "Machine": op.machine_id, "Tool": op.tool_id, "Duration (min)": op.duration_min,
            "Issues": issues.get(op.operation_id, 0),
        }
        for i, op in enumerate(plan.operations)
    ]


def violation_rows(validation: ValidationResult) -> list[dict[str, Any]]:
    return [
        {
            "Severity": v.severity, "Rule": v.rule_id, "Operation": v.operation_id or "–", "Feature": v.feature_id or "–",
            "Message": v.message, "Repair hint": v.repair_hint, "Repairable": "yes" if v.repairable else "no (needs human)",
        }
        for v in validation.hard_constraint_violations + validation.warnings
    ]


def iteration_timeline(record: RunRecord) -> list[dict[str, Any]]:
    rows = []
    for it in record.iterations:
        v = it.validation
        rows.append({
            "Iteration": it.index,
            "Source": "planner" if it.source == "planner" else f"repair ({it.repair.agent})" if it.repair else "repair",
            "Valid": "yes" if v.valid else "no",
            "Hard violations": len(v.hard_constraint_violations),
            "Warnings": len(v.warnings),
            "Coverage": f"{v.coverage.covered_features}/{v.coverage.required_features}",
            "Changes made": len(it.repair.changes) if it.repair else 0,
            "Step time (s)": round(it.repair.latency_s, 1) if it.repair else round(sum(a.latency_s or 0 for a in record.planner_result.attempts), 1),
        })
    return rows


def outcome_summary(record: RunRecord) -> dict[str, str]:
    """Headline, status kind ('success' | 'warning') and plain-language explanation of how the run ended."""
    accepted = record.final_status == "ACCEPTED"
    repairs = record.repairs_used
    if accepted:
        headline = "Accepted: plan passes all hard rules" + (f" after {repairs} repair(s)" if repairs else " on the first attempt")
    else:
        headline = "Needs human review"
    explanation = STOP_REASON_TEXT.get(record.stop_reason, record.stop_reason)
    if record.stop_detail and record.stop_reason not in ("valid",):
        explanation += f" Detail: {record.stop_detail}"
    return {"headline": headline, "kind": "success" if accepted else "warning", "explanation": explanation}


def diff_rows(diff: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not diff:
        return []
    rows = [{"Change": "added", "Operation": op, "Details": ""} for op in diff["added"]]
    rows += [{"Change": "removed", "Operation": op, "Details": ""} for op in diff["removed"]]
    for op, fields in diff["modified"].items():
        rows.append({"Change": "modified", "Operation": op, "Details": "; ".join(f"{k}: {a} → {b}" for k, (a, b) in fields.items())})
    for e in diff.get("precedence_added", []):
        rows.append({"Change": "edge added", "Operation": f"{e[0]} → {e[1]}", "Details": ""})
    for e in diff.get("precedence_removed", []):
        rows.append({"Change": "edge removed", "Operation": f"{e[0]} → {e[1]}", "Details": ""})
    if diff.get("sequence_changed"):
        rows.append({"Change": "reordered", "Operation": "–", "Details": "operation sequence changed"})
    return rows


def rule_catalogue_rows() -> list[dict[str, str]]:
    return [{"Rule": r.rule_id, "Name": r.title, "Checks": r.description} for r in ALL_RULES]


def list_saved_runs() -> list[Path]:
    """Run records from the demo script and from experiments, newest first."""
    roots = [REPO_ROOT / "reports" / "runs", *sorted((REPO_ROOT / "reports" / "experiments").glob("*/runs"))]
    files = [p for root in roots if root.exists() for p in root.glob("*.json")]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def list_experiments() -> list[Path]:
    root = REPO_ROOT / "reports" / "experiments"
    return sorted((p for p in root.glob("*") if (p / "summary.json").exists()), key=lambda p: p.name) if root.exists() else []
