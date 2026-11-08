"""Per-case metrics and aggregation (spec section 8.2).

Definitions
-----------
Operation key
    ``"<feature_id>:<operation_type>"`` for each target of an operation. Keys let
    two plans be compared independently of their operation IDs.
Precedence accuracy
    Of the reference plan's precedence edges (mapped to key pairs), the fraction
    the candidate's *sequence* satisfies (both keys present and the first comes
    earlier). ``None`` if there is no reference or it has no edges.
Sequence similarity
    Pairwise order agreement (concordant pairs ÷ comparable pairs) over keys present
    in both plans, in ``[0, 1]``. One expert or reference sequence is not the only
    valid one, so this is descriptive only: low similarity does not mean wrong.
Feature coverage
    Required features covered (validator definition) ÷ required features.
Correct outcome
    Expected feasible and final plan valid, or expected ``needs_human_review``
    and the system stopped for human review.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

from scmpa.schemas import ProcessPlan, ValidationResult


def operation_keys(plan: ProcessPlan) -> list[str]:
    """Keys in sequence order (one per operation target)."""
    return [f"{fid}:{op.type}" for op in plan.operations for fid in op.target_features]


def _first_positions(plan: ProcessPlan) -> dict[str, int]:
    pos: dict[str, int] = {}
    for i, op in enumerate(plan.operations):
        for fid in op.target_features:
            pos.setdefault(f"{fid}:{op.type}", i)
    return pos


def precedence_accuracy(candidate: ProcessPlan, reference: ProcessPlan | None) -> float | None:
    if reference is None or not reference.precedence:
        return None
    ref_ops = {op.operation_id: op for op in reference.operations}
    pairs = {
        (f"{fa}:{ref_ops[a].type}", f"{fb}:{ref_ops[b].type}")
        for a, b in reference.precedence
        for fa in ref_ops[a].target_features
        for fb in ref_ops[b].target_features
    }
    pos = _first_positions(candidate)
    satisfied = sum(1 for ka, kb in pairs if ka in pos and kb in pos and pos[ka] < pos[kb])
    return satisfied / len(pairs)


def sequence_similarity(candidate: ProcessPlan, reference: ProcessPlan | None) -> float | None:
    if reference is None:
        return None
    pc, pr = _first_positions(candidate), _first_positions(reference)
    shared = sorted(pc.keys() & pr.keys())
    concordant = total = 0
    for i, a in enumerate(shared):
        for b in shared[i + 1:]:
            if pc[a] == pc[b] or pr[a] == pr[b]:
                continue  # same operation in one plan: not comparable
            total += 1
            concordant += (pc[a] < pc[b]) == (pr[a] < pr[b])
    return concordant / total if total else None


def coverage_ratio(validation: ValidationResult) -> float:
    c = validation.coverage
    return c.covered_features / c.required_features if c.required_features else 1.0


def violations_by_rule(validation: ValidationResult | None) -> dict[str, int]:
    if validation is None:
        return {}
    return dict(sorted(Counter(v.rule_id for v in validation.hard_constraint_violations).items()))


# --------------------------------------------------------------------------- aggregation helpers


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | tuple[None, None]:
    """95% Wilson score interval for a proportion (robust for small n and p near 0/1)."""
    if n == 0:
        return None, None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    # Clamp so the interval always contains p: at p = 0 or 1, rounding can put a bound a hair on the wrong side.
    return max(0.0, min(p, centre - half)), min(1.0, max(p, centre + half))


def _mean(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.fmean(vals) if vals else None


def _median(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None


def _rate(rows: Sequence[dict[str, Any]], predicate) -> dict[str, Any]:
    n = len(rows)
    k = sum(1 for r in rows if predicate(r))
    lo, hi = wilson_interval(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci_low": lo, "ci_high": hi}


def _seed_spread(rows: Sequence[dict[str, Any]], predicate) -> float | None:
    """Standard deviation across seeds of a per-seed rate (None with < 2 seeds)."""
    by_seed: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        by_seed.setdefault(r["seed"], []).append(r)
    rates = [sum(1 for r in rs if predicate(r)) / len(rs) for rs in by_seed.values() if rs]
    return statistics.stdev(rates) if len(rates) >= 2 else None


def aggregate(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Summary metrics for one (track, system) group of per-case rows."""
    invalid = lambda r: not r["final_valid"]  # noqa: E731
    initially_invalid = [r for r in rows if r["initial_valid"] is False]
    initially_invalid_feasible = [r for r in initially_invalid if r["expected_outcome"] == "feasible"]
    repaired = [r for r in initially_invalid if r["final_valid"]]
    hr_expected = [r for r in rows if r["expected_outcome"] == "needs_human_review"]
    hr_flagged = [r for r in rows if r["final_status"] == "NEEDS_HUMAN_REVIEW"]
    return {
        "n_cases": len(rows),
        "n_components": len({r["component_id"] for r in rows}),
        "n_seeds": len({r["seed"] for r in rows}),
        "planner_failure": _rate(rows, lambda r: r["planner_status"] != "ok"),
        "initial_hard_violation_rate": _rate(rows, lambda r: r["initial_valid"] is not True),
        "hard_violation_rate": _rate(rows, invalid),
        "hard_violation_rate_seed_sd": _seed_spread(rows, invalid),
        "mean_final_violations": _mean(r["final_hard_violations"] for r in rows),
        "repair_success": _rate(initially_invalid, lambda r: r["final_valid"]),
        "repair_success_feasible_only": _rate(initially_invalid_feasible, lambda r: r["final_valid"]),
        "mean_feature_coverage": _mean(r["final_coverage"] for r in rows),
        "mean_precedence_accuracy": _mean(r["final_precedence_accuracy"] for r in rows),
        "mean_sequence_similarity": _mean(r["final_sequence_similarity"] for r in rows),
        "repair_iterations_mean": _mean(r["repairs_used"] for r in repaired),
        "repair_iterations_median": _median(r["repairs_used"] for r in repaired),
        "human_review_rate": _rate(rows, lambda r: r["final_status"] == "NEEDS_HUMAN_REVIEW"),
        "human_review_recall": _rate(hr_expected, lambda r: r["final_status"] == "NEEDS_HUMAN_REVIEW"),
        "human_review_precision": _rate(hr_flagged, lambda r: r["expected_outcome"] == "needs_human_review"),
        "correct_outcome": _rate(rows, lambda r: r["correct_outcome"]),
        "invalid_plan_accepted": _rate(rows, lambda r: r["final_status"] in ("ACCEPTED", "UNCHECKED") and not r["final_valid"]),
        "mean_latency_s": _mean(r["latency_s"] for r in rows),
        "total_latency_s": round(math.fsum(r["latency_s"] or 0 for r in rows), 3),  # fsum: same on every Python version
        "mean_tokens": _mean(r["tokens"] for r in rows),
    }
