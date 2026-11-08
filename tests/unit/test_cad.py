"""Milestone 6: FreeCAD feature extraction (geometry -> SCMPA features).

The fixture block (scripts/freecad/make_cad_fixture.py) has 7 known features. Tests that need FreeCAD
are skipped when it is not installed; conversion is tested on a stored extraction.
"""

from __future__ import annotations

import pytest

from scmpa.cad import FreeCADNotFound, extract_features, find_freecad, to_component
from scmpa.io import REPO_ROOT, load_catalogue, read_json
from scmpa.planning import MockPlanner
from scmpa.repair import RuleBasedRepairAgent
from scmpa.workflow import solve

FIX = REPO_ROOT / "tests" / "fixtures" / "cad"
CATALOGUE = load_catalogue()


def _freecad_available() -> bool:
    try:
        find_freecad()
        return True
    except FreeCADNotFound:
        return False


needs_freecad = pytest.mark.skipif(not _freecad_available(), reason="FreeCAD not installed (set SCMPA_FREECAD_DIR)")


def _key(f: dict) -> tuple:
    return (f["type"], f.get("diameter_mm"), f.get("depth_mm"), f.get("length_mm"), f.get("width_mm"))


def _matches_truth(features: list[dict]) -> None:
    truth = read_json(FIX / "demo_block_truth.json")["features"]
    assert len(features) == len(truth)
    remaining = list(features)
    for t in truth:
        hit = next((f for f in remaining if f["type"] == t["type"]
                    and all(abs(float(f.get(k) or 0) - float(v)) < 0.01 for k, v in t.items() if k.endswith("_mm") and not isinstance(v, list))
                    and f.get("counterbore_diameters_mm", []) == [float(x) for x in t.get("counterbore_diameters_mm", f.get("counterbore_diameters_mm", []))]), None)
        assert hit is not None, f"no extracted feature matches {t}"
        remaining.remove(hit)


def test_stored_extraction_matches_the_modelled_features() -> None:
    _matches_truth(read_json(FIX / "demo_block_extraction.json")["features"])


@needs_freecad
def test_live_extraction_matches_the_modelled_features() -> None:
    result = extract_features(FIX / "demo_block.step")
    _matches_truth(result["features"])
    stored = read_json(FIX / "demo_block_extraction.json")["features"]
    assert sorted(map(_key, result["features"])) == sorted(map(_key, stored))


def test_to_component_keeps_cad_features_distinct_and_runs_through_the_workflow() -> None:
    extraction = read_json(FIX / "demo_block_extraction.json")
    component, unsupported = to_component(extraction, "demo_block_cad", read_json(FIX / "demo_block_resources.json"),
                                          material="aluminium", catalogue=CATALOGUE)
    assert [u["type"] for u in unsupported] == ["step"]  # no SCMPA step type: reported, not forced
    assert sorted(f.type for f in component.features) == ["blind_hole", "pocket", "slot", "slot", "through_hole", "through_hole"]
    assert all(f.description.startswith("CAD: ") for f in component.features)
    assert component.provenance.source_type == "derived" and "STEP file demo_block.step" in component.provenance.source
    record = solve(component, CATALOGUE, MockPlanner(faults=["incompatible_tool"], seed=0), RuleBasedRepairAgent())
    assert record.final_status == "ACCEPTED"


def test_to_component_refuses_when_nothing_maps() -> None:
    extraction = {**read_json(FIX / "demo_block_extraction.json"), "features": [{"type": "step", "solid": 0, "faces": [1]}]}
    with pytest.raises(ValueError, match="no extracted feature"):
        to_component(extraction, "x", read_json(FIX / "demo_block_resources.json"), catalogue=CATALOGUE)


def test_missing_freecad_is_a_clear_error(monkeypatch) -> None:
    monkeypatch.setenv("SCMPA_FREECAD_DIR", str(REPO_ROOT / "does-not-exist"))
    with pytest.raises(FreeCADNotFound, match="SCMPA_FREECAD_DIR"):
        find_freecad()
