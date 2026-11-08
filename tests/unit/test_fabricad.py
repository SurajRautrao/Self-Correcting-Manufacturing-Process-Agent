"""Milestone 6: FabriCAD importer, on a hand-written fixture in FabriCAD's file format (no FabriCAD data)."""

from __future__ import annotations

import json

from scmpa.importers.fabricad import classify, import_folder, import_sample
from scmpa.io import REPO_ROOT, load_catalogue
from scmpa.planning import MockPlanner
from scmpa.repair import RuleBasedRepairAgent
from scmpa.validation import validate_plan
from scmpa.workflow import solve

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "fabricad"
CATALOGUE = load_catalogue()


def test_classify_maps_known_texts_conservatively() -> None:
    assert classify("Bohrung Ø8 x 20.0[mm] mit 45°-Senkung mit M8 Gewinde")["required_operation_types"] == ["drilling", "tapping"]
    assert classify("Bohrung Ø10 x 30.0[mm]mit Passung H7")["required_operation_types"] == ["drilling", "reaming"]
    loose = classify("Bohrung Ø12 x 30.0[mm]mit Passung H12")
    assert loose["type"] == "blind_hole" and "required_operation_types" not in loose  # a loose fit is just drilled
    assert classify("Rechteckige Tasche mit 40.0[mm] x 30.0[mm] x 10.0[mm]") | {} == {
        "type": "pocket", "length_mm": 40.0, "width_mm": 30.0, "depth_mm": 10.0, "kind": "pocket"}
    assert classify("Langloch Ø12.0[mm] x 8.0[mm] DIN3771")["type"] == "slot"
    for unmapped in ("Abgerundete Viertelstufe  Ø40 [mm] x 10.0[mm]", "O-Ring-Nut Ø30.0[mm] x 4.0[mm] DIN3771",
                     "Durchgehender Absatz: 186.75[mm] x 50.0[mm] x 16.0[mm]"):
        assert classify(unmapped) is None, unmapped


def test_import_sample_builds_a_valid_derived_component_and_plan() -> None:
    r = import_sample(FIXTURE / "90000001", CATALOGUE)
    c = r.component
    assert r.mapped == 6 and len(r.omitted) == 3
    assert [f.type for f in c.features] == ["threaded_hole", "blind_hole", "blind_hole", "blind_hole", "pocket", "slot"]
    assert c.provenance.source_type == "derived" and "CC BY-NC" in c.provenance.license
    assert all(f.description.startswith("FabriCAD ") for f in c.features)  # derived features stay identifiable
    assert {m.machine_id for m in c.resources.machines} == {"Drill_Press_01", "CNC_Mill_02"}
    assumed = [t for t in c.resources.tools if "ASSUMED" in t.description]
    assert sorted(t.type for t in assumed) == ["reamer", "tap"]
    assert len(c.precedence_constraints) == 2  # drill before tap; drill before ream
    reasons = {o.substep: o.reason for o in r.omitted}
    assert "step/shoulder" in reasons["3.3"] and "groove" in reasons["3.4"] and "schweißen" in reasons["4.1"]
    assert validate_plan(r.reference_plan, c, CATALOGUE).valid
    assert [o.type for o in r.reference_plan.operations][:2] == ["drilling", "tapping"]


def test_sample_without_mappable_features_is_reported_not_forced() -> None:
    r = import_sample(FIXTURE / "90000002", CATALOGUE)
    assert r.component is None and r.problem and r.omitted[0].reason.startswith("process step")


def test_imported_component_runs_through_the_workflow() -> None:
    c = import_sample(FIXTURE / "90000001", CATALOGUE).component
    record = solve(c, CATALOGUE, MockPlanner(faults=["incompatible_tool"], seed=0), RuleBasedRepairAgent())
    assert record.final_status == "ACCEPTED"


def test_import_folder_writes_outputs_and_report(tmp_path) -> None:
    results = import_folder(FIXTURE, tmp_path, log=lambda m: None)
    assert len(results) == 2
    assert (tmp_path / "components" / "fabricad_90000001.json").exists()
    report = {r["sample_id"]: r for r in json.loads((tmp_path / "import_report.json").read_text(encoding="utf-8"))}
    assert report["90000001"]["fabricad_plan_valid"] is True and report["90000002"]["problem"]
