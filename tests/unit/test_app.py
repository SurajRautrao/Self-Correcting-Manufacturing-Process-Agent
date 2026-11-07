"""Milestone 5: view helpers and a headless smoke test of the Streamlit app."""

from __future__ import annotations

import pytest

from scmpa.app.view_models import (
    STOP_REASON_TEXT,
    diff_rows,
    feature_rows,
    iteration_timeline,
    list_component_sources,
    outcome_summary,
    plan_rows,
    precedence_rows,
    violation_rows,
)
from scmpa.io import EXAMPLE_COMPONENTS_DIR, REPO_ROOT, load_catalogue, load_component
from scmpa.planning import MockPlanner
from scmpa.repair import RuleBasedRepairAgent
from scmpa.workflow import solve
from scmpa.workflow.orchestration import StopReason

CATALOGUE = load_catalogue()
APP = str(REPO_ROOT / "src" / "scmpa" / "app" / "streamlit_app.py")


def plate():
    return load_component(EXAMPLE_COMPONENTS_DIR / "demo_plate_002.json", CATALOGUE)


def test_every_stop_reason_has_plain_text() -> None:
    assert set(STOP_REASON_TEXT) == set(StopReason.__args__)


def test_component_sources_include_examples_and_benchmark() -> None:
    groups = {s.group for s in list_component_sources()}
    assert groups == {"Examples", "Synthetic benchmark"}
    assert all(s.path.exists() for s in list_component_sources())


def test_component_tables() -> None:
    rows = feature_rows(plate())
    f3 = next(r for r in rows if r["Feature"] == "F3")
    assert f3["Must receive"] == "drilling, tapping" and "diameter 6 mm" in f3["Dimensions"]
    assert precedence_rows(plate())[0] == {
        "Before": "drilling on F3", "After": "tapping on F3", "Rationale": plate().precedence_constraints[0].rationale,
    }


def test_trace_tables_for_repaired_run() -> None:
    record = solve(plate(), CATALOGUE, MockPlanner(faults=["incompatible_tool"], seed=0), RuleBasedRepairAgent())
    timeline = iteration_timeline(record)
    assert [r["Valid"] for r in timeline] == ["no", "yes"]
    assert timeline[1]["Source"] == "repair (rule_based)" and timeline[1]["Changes made"] == 1
    first = record.iterations[0]
    rows = plan_rows(first.plan, first.validation)
    assert sum(r["Issues"] for r in rows) == 1
    assert violation_rows(first.validation)[0]["Rule"] == "R5_TOOL_COMPATIBILITY"
    [d] = diff_rows(record.iterations[1].repair.diff)
    assert d["Change"] == "modified" and "tool_id" in d["Details"]
    summary = outcome_summary(record)
    assert summary["kind"] == "success" and "after 1 repair" in summary["headline"]


def test_outcome_for_human_review() -> None:
    record = solve(plate(), CATALOGUE, MockPlanner(faults=["incompatible_tool"]), None)
    summary = outcome_summary(record)
    assert summary["kind"] == "warning" and summary["headline"] == "Needs human review"
    assert "repair budget" in summary["explanation"]


# --------------------------------------------------------------------------- headless app


streamlit_testing = pytest.importorskip("streamlit.testing.v1", reason="streamlit not installed (pip install -e .[app])")


def test_app_renders_and_runs_mock_workflow() -> None:
    at = streamlit_testing.AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    assert at.title[0].value == "Self-Correcting Manufacturing Process Agent"
    # inject a fault and run
    at.sidebar.multiselect[0].set_value(["incompatible_tool"])
    at.sidebar.button[0].click()
    at.run()
    assert not at.exception
    assert any("Accepted" in s.value for s in at.success)
    assert any("Deliberately injected faults" in i.value for i in at.info)


def test_app_other_views_render() -> None:
    at = streamlit_testing.AppTest.from_file(APP, default_timeout=60)
    at.run()
    for view in ("Inspect a saved run", "Experiment results"):
        at.sidebar.radio[0].set_value(view)
        at.run()
        assert not at.exception, view
