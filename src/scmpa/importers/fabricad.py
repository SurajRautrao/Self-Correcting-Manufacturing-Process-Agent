"""FabriCAD importer (Milestone 6): map FabriCAD samples to SCMPA components (derived data).

    python -m scmpa.importers.fabricad <fabricad_root> --out data/external/fabricad

FabriCAD (CIMTT, FH Kiel; https://github.com/CIMTT-Kiel/FabriCAD) is a synthetic
dataset of process plans paired with CAD models. Its data is licensed
**CC BY-NC 4.0** (non-commercial; citation required), so no FabriCAD data is
shipped with this MIT repository. The importer reads a local copy and writes
its output under ``data/external/``, which is git-ignored. See docs/fabricad.md
for the inspected format, the mapping and its limits.

Only the drilling (``bohren``) and milling (``fräsen``) features have SCMPA
equivalents. Every other feature is omitted and listed, never forced into a type:

=========================================  ==================================================
FabriCAD feature text (German)             SCMPA mapping
=========================================  ==================================================
``Bohrung Ø.. x ..`` (+ Senkung)           ``blind_hole`` (through/blind is not stated; the counterbore is not modelled)
``Bohrung … mit M.. Gewinde``              ``threaded_hole``, requires drilling + tapping
``Bohrung … mit Passung H7``               ``blind_hole``, requires drilling + reaming (fit grade ≤ 8 only)
``Rechteckige Tasche`` / ``Tasche …``      ``pocket``
``Langloch Ø.. x ..``                      ``slot``
steps, shoulders, O-ring grooves           omitted: no SCMPA feature type
turning, welding, grinding features        omitted: outside the prismatic milling/drilling scope
=========================================  ==================================================
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import Field

from scmpa.io import load_catalogue, validate_component
from scmpa.planning.mock import DEFAULT_DURATION_MIN, PLACEHOLDER_DURATION_MIN
from scmpa.schemas import Component, ProcessPlan
from scmpa.schemas.base import StrictModel

SOURCE = "FabriCAD (CIMTT, FH Kiel), https://github.com/CIMTT-Kiel/FabriCAD"
LICENSE = "CC BY-NC 4.0 (FabriCAD data); cite Kruse et al., FabriCAD, Procedia CIRP (CIRP ICME 2026)"

#: Machine capability templates by FabriCAD workstation prefix (an SCMPA assumption; FabriCAD lists no capabilities).
WORKSTATION_CAPABILITIES = {
    "Drill_Press": ("Drill press (FabriCAD workstation; capabilities assumed)", ["spot_drilling", "drilling", "tapping", "reaming"]),
    "CNC_Mill": ("CNC milling machine (FabriCAD workstation; capabilities assumed)",
                 ["face_milling", "contour_milling", "pocket_milling", "slot_milling", "spot_drilling", "drilling", "chamfering"]),
}
TOOL_TYPES = {"Spiralbohrer": "drill", "Schruppfräser": "end_mill"}
MAPPED_STEPS = {"bohren": "Drill_Press", "fräsen": "CNC_Mill"}
MATERIALS = {"Baustahl": "structural steel (Baustahl)", "Aluminiumlegierungen": "aluminium alloy"}

NUM = r"([\d.]+)"
RE_HOLE = re.compile(rf"^Bohrung\s*Ø\s*{NUM}\s*x\s*{NUM}\s*\[mm\]")
RE_THREAD = re.compile(r"M\s*(\d+(?:\.\d+)?)\s*Gewinde")
RE_FIT = re.compile(r"Passung\s*([A-Za-z])\s*(\d+)")
RE_RECT_POCKET = re.compile(rf"^Rechteckige Tasche mit\s*{NUM}\s*\[mm\]\s*x\s*{NUM}\s*\[mm\]\s*x\s*{NUM}\s*\[mm\]")
RE_DEPTH = re.compile(rf"Tiefe\s*{NUM}")
RE_NUT_POCKET = re.compile(rf"^Tasche für Sechskantmutter D=\s*{NUM}\s*\[mm\]\s*x\s*{NUM}\s*\[mm\]")
RE_SLOT = re.compile(rf"^Langloch\s*Ø\s*{NUM}\s*\[mm\]\s*x\s*{NUM}\s*\[mm\]")
RE_TOOL = re.compile(r"^\s*(\S+)\s*\(\s*([\d.]+)\s*\)")
RE_REF = re.compile(r"\s*\(#\d+\)\s*$")


class OmittedFeature(StrictModel):
    substep: str
    text: str
    reason: str


class ImportResult(StrictModel):
    """One FabriCAD sample. ``component`` is None when no feature maps."""

    sample_id: str
    component: Component | None = None
    reference_plan: ProcessPlan | None = None
    mapped: int = 0
    omitted: list[OmittedFeature] = Field(default_factory=list)
    problem: str | None = None


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh, delimiter=";")]


def classify(text: str) -> dict[str, Any] | None:
    """Map one FabriCAD feature text to SCMPA feature fields, or None if it has no equivalent."""
    if m := RE_HOLE.match(text):
        dia, depth = float(m[1]), float(m[2])
        if t := RE_THREAD.search(text):
            return {"type": "threaded_hole", "diameter_mm": float(t[1]), "depth_mm": depth,
                    "required_operation_types": ["drilling", "tapping"], "kind": "thread"}
        fit = RE_FIT.search(text)
        if fit and int(fit[2]) <= 8:  # a tight fit (e.g. H7) is reamed; a loose one (e.g. H12) is just drilled
            return {"type": "blind_hole", "diameter_mm": dia, "depth_mm": depth,
                    "required_operation_types": ["drilling", "reaming"], "kind": "fit"}
        return {"type": "blind_hole", "diameter_mm": dia, "depth_mm": depth, "kind": "hole"}
    if m := RE_RECT_POCKET.match(text):
        return {"type": "pocket", "length_mm": float(m[1]), "width_mm": float(m[2]), "depth_mm": float(m[3]), "kind": "pocket"}
    if m := RE_NUT_POCKET.match(text):
        return {"type": "pocket", "width_mm": float(m[1]), "depth_mm": float(m[2]), "kind": "pocket"}
    if text.startswith("Tasche"):
        d = RE_DEPTH.search(text)
        return {"type": "pocket", **({"depth_mm": float(d[1])} if d else {}), "kind": "pocket"}
    if m := RE_SLOT.match(text):
        return {"type": "slot", "width_mm": float(m[1]), "depth_mm": float(m[2]), "kind": "slot"}
    return None


def omission_reason(step: str, text: str) -> str:
    if step not in MAPPED_STEPS:
        return f"process step '{step}' is outside SCMPA's prismatic milling/drilling scope"
    if "Nut" in text:
        return "circular groove (O-ring groove): no SCMPA feature type"
    if "stufe" in text.lower() or "absatz" in text.lower():
        return "step/shoulder: no SCMPA feature type"
    return "feature text not recognised by the importer"


def import_sample(sample_dir: Path, catalogue=None) -> ImportResult:
    """Import one FabriCAD sample folder (``plan.csv``, ``plan_metadata.csv``, ``interim/substeps/features.csv``)."""
    catalogue = catalogue or load_catalogue()
    sid = sample_dir.name
    plan_rows = read_csv(sample_dir / "plan.csv")
    meta = read_csv(sample_dir / "plan_metadata.csv")[0]
    feat_rows = read_csv(sample_dir / "interim" / "substeps" / "features.csv")
    steps = {r["Nr."]: r for r in plan_rows}

    features, omitted, ops_spec = [], [], []
    machines: dict[str, dict[str, Any]] = {}
    tools: dict[tuple[str, float], str] = {}
    assumed_tools: dict[tuple[str, float], str] = {}
    tool_list: list[dict[str, str]] = []

    def tool_id(kind: str, dia: float, label: str, assumed: bool) -> str:
        table = assumed_tools if assumed else tools
        if (kind, dia) not in table:
            tid = f"T{len(tool_list) + 1}"
            table[(kind, dia)] = tid
            tool_list.append({"tool_id": tid, "type": kind, "description": label})
        return table[(kind, dia)]

    for row in sorted(feat_rows, key=lambda r: [int(x) for x in r["Subschritt"].split(".")]):
        step = steps.get(row["Arbeitsschritt"], {})
        step_name, text = step.get("Schritt", "?"), RE_REF.sub("", row["Kurztext"])
        spec = classify(text) if step_name in MAPPED_STEPS else None
        tool = RE_TOOL.match(row.get("Werkzeug[mm](D)", ""))
        if spec is None or tool is None or tool[1] not in TOOL_TYPES:
            omitted.append(OmittedFeature(substep=row["Subschritt"], text=text,
                                          reason=omission_reason(step_name, text) if spec is None else "tool not mappable"))
            continue
        ws = step["Arbeitsplatz"]
        prefix = MAPPED_STEPS[step_name]
        if not ws.startswith(prefix):
            omitted.append(OmittedFeature(substep=row["Subschritt"], text=text, reason=f"unexpected workstation {ws!r}"))
            continue
        desc, caps = WORKSTATION_CAPABILITIES[prefix]
        machines.setdefault(ws, {"machine_id": ws, "description": desc, "capabilities": caps})
        fid = f"F{len(features) + 1}"
        kind = spec.pop("kind")
        features.append({"feature_id": fid, "required": True, "description": f"FabriCAD {row['Subschritt']}: {text}", **spec})
        main_type = {"pocket": "pocket_milling", "slot": "slot_milling"}.get(kind, "drilling")
        tname, tdia = tool[1], float(tool[2])
        main_tool = tool_id(TOOL_TYPES[tname], tdia, f"{tname} Ø{tdia} mm (from FabriCAD)", assumed=False)
        dur = float(row["Dauer[min]"]) if row.get("Dauer[min]", "-") not in ("", "-") else 0.0
        ops_spec.append((fid, main_type, ws, main_tool, dur if dur > 0 else PLACEHOLDER_DURATION_MIN.get(main_type, DEFAULT_DURATION_MIN)))
        if kind in ("thread", "fit"):
            second = "tapping" if kind == "thread" else "reaming"
            label = f"M{spec['diameter_mm']:g} tap" if kind == "thread" else f"Ø{spec['diameter_mm']:g} reamer"
            t2 = tool_id("tap" if kind == "thread" else "reamer", spec["diameter_mm"], f"{label} (ASSUMED: FabriCAD lists no tap/reamer)", assumed=True)
            ops_spec.append((fid, second, ws, t2, PLACEHOLDER_DURATION_MIN.get(second, DEFAULT_DURATION_MIN)))

    if not features:
        return ImportResult(sample_id=sid, omitted=omitted, problem="no feature maps to an SCMPA feature type")

    constraints = [
        {"before": {"feature_id": f["feature_id"], "operation_type": "drilling"},
         "after": {"feature_id": f["feature_id"], "operation_type": second},
         "rationale": f"A {'thread is cut into' if second == 'tapping' else 'fit is reamed in'} a previously drilled hole (derived from the FabriCAD feature text)."}
        for f in features for second in (f.get("required_operation_types") or [])[1:]
    ]
    cid = f"fabricad_{sid}"
    data = {
        "component_id": cid,
        "description": f"FabriCAD sample {sid} ({meta.get('Kurzbezeichnung', '').rstrip(',')}); stock {meta.get('Abmaße', '?')} mm. Derived data.",
        "material": MATERIALS.get(meta.get("Material", ""), meta.get("Material") or "unknown"),
        "features": features,
        "resources": {"machines": list(machines.values()), "tools": tool_list},
        "precedence_constraints": constraints,
        "assumptions": [
            "Derived from FabriCAD by scmpa.importers.fabricad; feature types are mapped from German free text (see docs/fabricad.md).",
            "Machine capabilities are SCMPA templates per workstation type; FabriCAD does not list capabilities.",
            "Holes are typed blind_hole because FabriCAD does not state through/blind; counterbores and countersinks are not modelled.",
            "FabriCAD lists no taps or reamers; one per thread size or fit is ASSUMED so threaded/fitted holes stay producible.",
            "FabriCAD's process-step order is Markov-chain generated, so it is not encoded as precedence constraints.",
            *([f"{len(omitted)} FabriCAD feature(s) omitted (no SCMPA equivalent): "
               + "; ".join(f"{o.substep} {o.text[:60]}" for o in omitted)] if omitted else []),
        ],
        "provenance": {"source_type": "derived", "source": f"{SOURCE}, sample {sid}", "license": LICENSE,
                       "notes": "FabriCAD itself is synthetic (Markov chains fitted to real plans); this record is derived from it."},
    }
    component = validate_component(data, catalogue, cid)

    ops = [{"operation_id": f"OP{i}", "type": t, "target_features": [fid], "machine_id": ws, "tool_id": tid,
            "duration_min": round(d, 3), "notes": ""} for i, (fid, t, ws, tid, d) in enumerate(ops_spec, 1)]
    precedence = [[a["operation_id"], b["operation_id"]] for a, b in zip(ops, ops[1:])
                  if a["target_features"] == b["target_features"] and a["type"] == "drilling" and b["type"] in ("tapping", "reaming")]
    plan = ProcessPlan.model_validate({
        "plan_id": f"{cid}_fabricad", "component_id": cid, "operations": ops, "precedence": precedence,
        "explanation": "FabriCAD's own sequence (step order, then feature order within each step), mapped to SCMPA operations. "
                       "Tapping and reaming steps use assumed tools.",
        "assumptions": ["Durations of drilling/milling are FabriCAD's per-feature estimates; tapping/reaming use SCMPA placeholders."],
        "provenance": {"source_type": "derived", "source": f"{SOURCE}, sample {sid}", "license": LICENSE},
    })
    return ImportResult(sample_id=sid, component=component, reference_plan=plan, mapped=len(features), omitted=omitted)


def import_folder(root: Path, out: Path | None = None, log=print) -> list[ImportResult]:
    """Import every sample folder under ``root`` (folders containing ``plan.csv``); optionally write the results."""
    from scmpa.validation import validate_plan

    catalogue = load_catalogue()
    samples = sorted(p.parent for p in Path(root).rglob("plan.csv") if (p.parent / "interim" / "substeps" / "features.csv").exists())
    results = [import_sample(s, catalogue) for s in samples]
    if out is not None:
        out = Path(out)
        (out / "components").mkdir(parents=True, exist_ok=True)
        (out / "reference_plans").mkdir(parents=True, exist_ok=True)
        report = []
        for r in results:
            row = {"sample_id": r.sample_id, "mapped": r.mapped, "omitted": len(r.omitted), "problem": r.problem}
            if r.component:
                (out / "components" / f"{r.component.component_id}.json").write_text(r.component.model_dump_json(indent=2), encoding="utf-8")
                (out / "reference_plans" / f"{r.component.component_id}_ref.json").write_text(r.reference_plan.model_dump_json(indent=2), encoding="utf-8")
                v = validate_plan(r.reference_plan, r.component, catalogue)
                row["fabricad_plan_valid"] = v.valid
                row["fabricad_plan_violations"] = sorted({x.rule_id for x in v.hard_constraint_violations})
            row["omitted_reasons"] = sorted({o.reason for o in r.omitted})
            report.append(row)
        (out / "import_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"{sum(1 for r in results if r.component)}/{len(results)} samples imported into {out}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", help="local FabriCAD folder (e.g. data/preview of a clone)")
    parser.add_argument("--out", default="data/external/fabricad", help="output folder (git-ignored)")
    args = parser.parse_args(argv)
    import_folder(Path(args.root), Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
