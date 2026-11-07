"""Live smoke test against a local Ollama server. Skipped unless SCMPA_TEST_OLLAMA=1.

It only asserts *controlled behaviour* (schema-valid plan or controlled
failure, validator runs), never that the model produces a valid plan —
that is an empirical question for the experiments, not a test.
"""

from __future__ import annotations

import os

import pytest

from scmpa.io import EXAMPLE_COMPONENTS_DIR, load_catalogue, load_component
from scmpa.planning import make_planner
from scmpa.validation import validate_plan

pytestmark = [
    pytest.mark.ollama,
    pytest.mark.skipif(os.environ.get("SCMPA_TEST_OLLAMA") != "1", reason="set SCMPA_TEST_OLLAMA=1 to run"),
]


def test_live_ollama_planner_controlled_outcome() -> None:
    catalogue = load_catalogue()
    component = load_component(EXAMPLE_COMPONENTS_DIR / "demo_bracket_001.json", catalogue)
    result = make_planner("ollama").generate_plan(component, catalogue)
    assert result.status in {"ok", "failed"}
    if result.status == "ok":
        validation = validate_plan(result.plan, component, catalogue)
        assert validation.coverage.required_features == 3
    else:
        assert result.error
