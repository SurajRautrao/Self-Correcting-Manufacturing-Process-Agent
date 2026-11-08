"""Seeded generator for the synthetic SCMPA benchmark.

Everything produced here is **synthetic** and labelled so. It exists to test
software behaviour (constraint checking, repair, human-review routing) on
parts harder than the hand-written examples, not to estimate industrial
performance.

Each component gets:

* a datum face F1 plus 3–7 further features (pockets, slots, plain, blind,
  threaded and reamed holes, contours, chamfers; some chamfers optional);
* 1–3 machines drawn from templates, topped up so every needed operation has
  a capable machine; a compatible tool per needed operation type plus 0–2
  distractor tools;
* declared, component-specific precedence assumptions (datum-first, pocket
  floor before hole, drill before tap/ream, contour before edge chamfer);
* ``expected_outcome``: ``feasible``, or ``needs_human_review`` for the
  deliberately infeasible fraction, where one required operation has no
  capable machine or no compatible tool.

Feasible components get a reference plan built by the deterministic mock
planner and checked by the validator. It is one valid plan, not the only one.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from scmpa.io import validate_component
from scmpa.planning.mock import build_baseline_plan
from scmpa.schemas import Catalogue
from scmpa.validation import validate_plan
from scmpa.validation.context import ValidationContext

GENERATOR_VERSION = "1.0"
BENCHMARK_ID = "scmpa_synthetic_v1"

MACHINE_TEMPLATES: dict[str, tuple[str, list[str]]] = {
    "vmc": ("3-axis vertical machining centre", ["face_milling", "contour_milling", "pocket_milling", "slot_milling", "spot_drilling", "drilling", "chamfering"]),
    "knee_mill": ("Knee-type milling machine", ["face_milling", "pocket_milling", "slot_milling", "drilling"]),
    "drill_press": ("Pillar drill with tapping head", ["spot_drilling", "drilling", "tapping", "reaming"]),
    "drill_tap_centre": ("Drill-tap centre", ["drilling", "tapping", "chamfering"]),
}

#: kind -> (feature type, required_operation_types or None, weight)
FEATURE_KINDS: dict[str, tuple[str, list[str] | None, int]] = {
    "pocket": ("pocket", None, 3),
    "slot": ("slot", None, 2),
    "through_hole": ("through_hole", None, 3),
    "blind_hole": ("blind_hole", None, 2),
    "threaded_hole": ("threaded_hole", ["drilling", "tapping"], 3),
    "reamed_hole": ("through_hole", ["drilling", "reaming"], 2),
    "outer_contour": ("outer_contour", None, 1),
    "chamfer": ("chamfer", None, 2),
}

MATERIALS = ["aluminium", "steel_s235", "stainless_1.4301", "brass"]

#: v2 machines are specialised, with partly overlapping capabilities. Some operation types run on
#: two machine kinds and others on one, so minimising machine changes and minimising tool changes
#: can pull in different directions (needed to test the optimizer's weighting, H3).
MACHINE_TEMPLATES_V2: dict[str, tuple[str, list[str]]] = {
    "mill_centre": ("Milling centre (no drilling)", ["face_milling", "contour_milling", "pocket_milling", "slot_milling", "chamfering"]),
    "drill_tap_unit": ("Drill-tap unit", ["spot_drilling", "drilling", "tapping"]),
    "boring_mill": ("Horizontal boring mill", ["drilling", "reaming", "pocket_milling", "face_milling"]),
    "slot_cell": ("Slotting and chamfering cell", ["slot_milling", "chamfering", "spot_drilling"]),
}

#: Generator profiles. "v1" reproduces benchmark_v1 exactly (same random calls, same parameters).
PROFILES: dict[str, dict[str, Any]] = {
    "v1": {"benchmark_id": BENCHMARK_ID, "generator_version": GENERATOR_VERSION, "templates": MACHINE_TEMPLATES,
           "n_features": (3, 7), "n_machines": (1, 3), "distractors": (0, 2), "p_datum": 0.7, "p_pocket_floor": 0.5},
    "v2": {"benchmark_id": "scmpa_synthetic_v2", "generator_version": "2.0", "templates": MACHINE_TEMPLATES_V2,
           "n_features": (6, 10), "n_machines": (2, 3), "distractors": (1, 3), "p_datum": 0.9, "p_pocket_floor": 0.8},
}


def _dims(kind: str, rng: random.Random) -> dict[str, float]:
    r = lambda a, b: round(rng.uniform(a, b), 1)  # noqa: E731
    if kind == "pocket":
        return {"depth_mm": r(3, 15), "width_mm": r(10, 40), "length_mm": r(15, 60)}
    if kind == "slot":
        return {"depth_mm": r(2, 8), "width_mm": r(4, 12), "length_mm": r(20, 80)}
    if kind in ("through_hole", "reamed_hole"):
        return {"diameter_mm": float(rng.choice([4, 5, 6, 8, 10, 12]))}
    if kind == "blind_hole":
        return {"diameter_mm": float(rng.choice([3, 4, 5, 6, 8])), "depth_mm": r(5, 20)}
    if kind == "threaded_hole":
        return {"diameter_mm": float(rng.choice([4, 5, 6, 8, 10])), "depth_mm": r(8, 20)}
    if kind == "chamfer":
        return {"width_mm": float(rng.choice([0.5, 1.0, 1.5]))}
    return {}


def _main_operation(feature_type: str, catalogue: Catalogue) -> str:  # noqa: D103
    return catalogue.completing_operation_types(feature_type)[0]


def generate_component(index: int, rng: random.Random, catalogue: Catalogue, *, infeasible: bool, profile: str = "v1") -> dict[str, Any]:
    """Return one component as plain JSON-compatible data (validated before return)."""
    prof = PROFILES[profile]
    templates = prof["templates"]
    cid = f"syn_{index:03d}" if profile == "v1" else f"syn{profile}_{index:03d}"
    features: list[dict[str, Any]] = [{"feature_id": "F1", "type": "planar_face", "required": True, "description": "Datum face"}]
    kinds = list(FEATURE_KINDS)
    weights = [FEATURE_KINDS[k][2] for k in kinds]
    picked: list[str] = []
    for n in range(rng.randint(*prof["n_features"])):
        kind = rng.choices(kinds, weights)[0]
        ftype, req_ops, _ = FEATURE_KINDS[kind]
        feature: dict[str, Any] = {
            "feature_id": f"F{n + 2}", "type": ftype, "required": not (kind == "chamfer" and rng.random() < 0.5),
            "description": kind.replace("_", " "), **_dims(kind, rng),
        }
        if req_ops:
            feature["required_operation_types"] = list(req_ops)
        features.append(feature)
        picked.append(kind)

    def needed_ops(f: dict[str, Any]) -> list[str]:
        return f.get("required_operation_types") or [_main_operation(f["type"], catalogue)]

    required_needs = sorted({t for f in features if f["required"] for t in needed_ops(f)})
    all_needs = sorted({t for f in features for t in needed_ops(f)})

    # Machines: random templates, then top up until every needed op is covered.
    names = rng.sample(sorted(templates), rng.randint(*prof["n_machines"]))
    for op in all_needs:
        if not any(op in templates[n][1] for n in names):
            names.append(next(n for n in sorted(templates) if op in templates[n][1]))
    machines = [
        {"machine_id": f"M{i + 1}", "description": templates[n][0], "capabilities": list(templates[n][1])}
        for i, n in enumerate(names)
    ]

    # Tools: one compatible tool per needed op type (shared where types coincide), plus distractors.
    tool_types: list[str] = []
    for op in all_needs:
        t = catalogue.tool_compatibility[op][0]
        if t not in tool_types:
            tool_types.append(t)
    if "drill" in tool_types and rng.random() < 0.6:
        tool_types.append("drill")  # a second drill of a different (unmodelled) size
    for _ in range(rng.randint(*prof["distractors"])):
        tool_types.append(rng.choice(catalogue.tool_types))
    rng.shuffle(tool_types)
    tools = [{"tool_id": f"T{i + 1}", "type": t} for i, t in enumerate(tool_types)]

    infeasible_reason = None
    if infeasible:
        # Remove the means to perform one required op that only some features need.
        candidates = [op for op in required_needs if op not in ("face_milling", "drilling")] or [op for op in required_needs if op != "face_milling"]
        op = rng.choice(candidates)
        allowed_tools = set(catalogue.tool_compatibility[op])
        remaining_tools = [t for t in tools if t["type"] not in allowed_tools]
        if rng.random() < 0.5 and remaining_tools:
            tools = remaining_tools
            infeasible_reason = f"no tool compatible with required operation {op!r}"
        else:
            for m in machines:
                m["capabilities"] = [c for c in m["capabilities"] if c != op]
            machines = [m for m in machines if m["capabilities"]]
            if not machines:  # keep at least one machine
                machines = [{"machine_id": "M1", "description": "Knee-type milling machine", "capabilities": ["face_milling"]}]
            infeasible_reason = f"no machine capable of required operation {op!r}"

    # Precedence assumptions (component-specific, each with a rationale).
    constraints: list[dict[str, Any]] = []
    for f in features[1:]:
        if rng.random() < prof["p_datum"]:
            constraints.append({
                "before": {"feature_id": "F1"}, "after": {"feature_id": f["feature_id"]},
                "rationale": "Demo assumption: F1 is the datum face; this feature is located or dimensioned from it.",
            })
        req = f.get("required_operation_types") or []
        for second in ("tapping", "reaming"):
            if "drilling" in req and second in req:
                constraints.append({
                    "before": {"feature_id": f["feature_id"], "operation_type": "drilling"},
                    "after": {"feature_id": f["feature_id"], "operation_type": second},
                    "rationale": f"{second.capitalize()} requires a pre-drilled hole.",
                })
    pockets = [f for f in features if f["type"] == "pocket"]
    blind = [f for f in features if f["type"] == "blind_hole"]
    for hole in blind:
        if pockets and rng.random() < prof["p_pocket_floor"]:
            pocket = rng.choice(pockets)
            hole["description"] = f"blind hole in the floor of {pocket['feature_id']}"
            constraints.append({
                "before": {"feature_id": pocket["feature_id"]}, "after": {"feature_id": hole["feature_id"]},
                "rationale": f"Demo assumption: the hole starts at the floor of pocket {pocket['feature_id']}.",
            })
    contours = [f for f in features if f["type"] == "outer_contour"]
    for ch in (f for f in features if f["type"] == "chamfer"):
        if contours:
            constraints.append({
                "before": {"feature_id": contours[0]["feature_id"]}, "after": {"feature_id": ch["feature_id"]},
                "rationale": "Demo assumption: the chamfer is on the contour edge.",
            })

    data = {
        "schema_version": "1.0",
        "component_id": cid,
        "description": f"Synthetic prismatic part with {len(features)} features ({', '.join(sorted(set(picked)))}).",
        "material": rng.choice(MATERIALS),
        "features": features,
        "resources": {"machines": machines, "tools": tools},
        "precedence_constraints": constraints,
        "assumptions": [
            "Synthetic component generated for software evaluation; not derived from real geometry.",
            "Tool size, tool access, collisions and setups are not modelled.",
            "Precedence constraints are generated demo assumptions, not general manufacturing rules.",
        ],
        "provenance": {
            "source_type": "synthetic",
            "source": f"scmpa.evaluation.synthetic v{prof['generator_version']}",
            "notes": f"benchmark {prof['benchmark_id']}; index {index}" + (f"; deliberately infeasible: {infeasible_reason}" if infeasible_reason else ""),
        },
    }
    validate_component(data, catalogue, cid)  # raises if the generator produced bad input
    data["_meta"] = {"infeasible_reason": infeasible_reason}
    return data


def generate_benchmark(
    out_dir: str | Path,
    catalogue: Catalogue,
    *,
    n_components: int = 24,
    seed: int = 2026,
    infeasible_fraction: float = 0.2,
    dev_fraction: float = 1 / 3,
    profile: str = "v1",
) -> dict[str, Any]:
    """Write components, reference plans and ``manifest.json`` to ``out_dir``; return the manifest."""
    rng = random.Random(seed)
    out = Path(out_dir)
    (out / "components").mkdir(parents=True, exist_ok=True)
    (out / "reference_plans").mkdir(parents=True, exist_ok=True)

    n_infeasible = round(n_components * infeasible_fraction)
    infeasible_idx = set(rng.sample(range(1, n_components + 1), n_infeasible))
    cases = []
    for i in range(1, n_components + 1):
        data = generate_component(i, rng, catalogue, infeasible=i in infeasible_idx, profile=profile)
        meta = data.pop("_meta")
        component = validate_component(data, catalogue, data["component_id"])
        (out / "components" / f"{component.component_id}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

        expected = "needs_human_review" if meta["infeasible_reason"] else "feasible"
        has_reference = False
        if expected == "feasible":
            plan = build_baseline_plan(component, catalogue, f"{component.component_id}_ref")
            result = validate_plan(plan, component, catalogue)
            if not result.valid:  # pragma: no cover - generator invariant
                raise AssertionError(f"reference plan for {component.component_id} is invalid: {result.hard_constraint_violations}")
            plan_data = plan.model_dump(mode="json")
            plan_data["provenance"] = {
                "source_type": "synthetic",
                "source": "scmpa.planning.mock.build_baseline_plan",
                "notes": "Generated reference plan, checked by the validator; one valid sequence among possibly many. Not expert-reviewed.",
            }
            (out / "reference_plans" / f"{component.component_id}_ref.json").write_text(json.dumps(plan_data, indent=2), encoding="utf-8")
            has_reference = True
        else:
            ctx = ValidationContext(component, catalogue)
            assert any(not ctx.resource_options(t) for f in component.features if f.required
                       for t in (f.required_operation_types or ctx.suitable_operation_types(f)))
        cases.append({
            "component_id": component.component_id,
            "expected_outcome": expected,
            "infeasible_reason": meta["infeasible_reason"],
            "has_reference_plan": has_reference,
            "n_features": len(component.features),
            "n_required_features": len(component.required_feature_ids),
            "n_machines": len(component.resources.machines),
            "n_tools": len(component.resources.tools),
            "n_precedence_constraints": len(component.precedence_constraints),
        })

    # Split by component ID, stratified by expected outcome.
    split: dict[str, list[str]] = {"dev": [], "test": []}
    for outcome in ("feasible", "needs_human_review"):
        ids = sorted(c["component_id"] for c in cases if c["expected_outcome"] == outcome)
        rng.shuffle(ids)
        n_dev = max(1, round(len(ids) * dev_fraction)) if ids else 0
        split["dev"] += sorted(ids[:n_dev])
        split["test"] += sorted(ids[n_dev:])
    for c in cases:
        c["split"] = "dev" if c["component_id"] in split["dev"] else "test"
    split = {k: sorted(v) for k, v in split.items()}

    manifest = {
        "benchmark_id": PROFILES[profile]["benchmark_id"],
        "generator": "scmpa.evaluation.synthetic",
        "generator_version": PROFILES[profile]["generator_version"],
        **({"profile": profile} if profile != "v1" else {}),
        "catalogue_id": catalogue.catalogue_id,
        "seed": seed,
        "n_components": n_components,
        "infeasible_fraction": infeasible_fraction,
        "source_type": "synthetic",
        "split": split,
        "split_policy": "by component_id, stratified by expected_outcome; the test split must not be used to tune prompts or rules",
        "cases": cases,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
