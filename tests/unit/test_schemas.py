"""Milestone 0 acceptance: malformed input and unknown IDs are rejected with clear errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from scmpa.io import (
    EXAMPLE_COMPONENTS_DIR,
    REFERENCE_PLANS_DIR,
    InputValidationError,
    load_component,
    load_plan,
    parse_model,
    validate_component,
)
from scmpa.schemas import Catalogue, Coverage, ProcessPlan, ValidationResult, Violation

COMPONENT_FILES = sorted(EXAMPLE_COMPONENTS_DIR.glob("*.json"))
PLAN_FILES = sorted(REFERENCE_PLANS_DIR.glob("*.json"))


def assert_rejected(excinfo: pytest.ExceptionInfo[InputValidationError], *fragments: str) -> None:
    """The error message must mention every fragment, so users can locate the problem."""
    text = str(excinfo.value)
    for fragment in fragments:
        assert fragment in text, f"expected {fragment!r} in error message:\n{text}"


# --------------------------------------------------------------------------- happy path


def test_example_data_present() -> None:
    assert len(COMPONENT_FILES) >= 3
    assert len(PLAN_FILES) == len(COMPONENT_FILES)


@pytest.mark.parametrize("path", COMPONENT_FILES, ids=lambda p: p.stem)
def test_example_components_validate(path: Path, catalogue: Catalogue) -> None:
    component = load_component(path, catalogue)
    assert component.provenance.source_type == "synthetic"
    assert component.required_feature_ids


@pytest.mark.parametrize("path", PLAN_FILES, ids=lambda p: p.stem)
def test_reference_plans_parse_and_match_a_component(path: Path) -> None:
    plan = load_plan(path)
    assert (EXAMPLE_COMPONENTS_DIR / f"{plan.component_id}.json").exists()


def test_catalogue_loads(catalogue: Catalogue) -> None:
    assert "drilling" in catalogue.operation_types
    assert catalogue.tool_compatibility["drilling"] == ["drill"]


# --------------------------------------------------------------------------- file-level failures


def test_missing_file_rejected(tmp_path: Path, catalogue: Catalogue) -> None:
    with pytest.raises(InputValidationError) as exc:
        load_component(tmp_path / "nope.json", catalogue)
    assert_rejected(exc, "cannot read file")


def test_malformed_json_rejected(tmp_path: Path, catalogue: Catalogue) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"component_id": "x",,}', encoding="utf-8")
    with pytest.raises(InputValidationError) as exc:
        load_component(bad, catalogue)
    assert_rejected(exc, "malformed JSON", "line 1")


# --------------------------------------------------------------------------- component schema failures


def test_missing_required_field(bracket_data, catalogue) -> None:
    del bracket_data["material"]
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "material", "Field required")


def test_unknown_field_rejected(bracket_data, catalogue) -> None:
    bracket_data["features"][0]["colour"] = "red"
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "features.0.colour", "Extra inputs are not permitted")


def test_missing_provenance_rejected(bracket_data, catalogue) -> None:
    del bracket_data["provenance"]
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "provenance")


def test_invalid_provenance_type(bracket_data, catalogue) -> None:
    bracket_data["provenance"]["source_type"] = "made_up"
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "provenance.source_type")


@pytest.mark.parametrize("value", [-8, 0, "eight"])
def test_bad_dimension_rejected(bracket_data, catalogue, value) -> None:
    bracket_data["features"][1]["diameter_mm"] = value
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "features.1.diameter_mm")


def test_free_text_id_rejected(bracket_data, catalogue) -> None:
    bracket_data["features"][0]["feature_id"] = "top face"
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "features.0.feature_id")


def test_duplicate_feature_ids(bracket_data, catalogue) -> None:
    bracket_data["features"][1]["feature_id"] = "F1"
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "duplicate feature_id", "F1")


def test_duplicate_tool_ids(bracket_data, catalogue) -> None:
    bracket_data["resources"]["tools"][1]["tool_id"] = "T1"
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "duplicate tool_id", "T1")


def test_duplicate_machine_ids(plate_data, catalogue) -> None:
    plate_data["resources"]["machines"][1]["machine_id"] = "M1"
    with pytest.raises(InputValidationError) as exc:
        validate_component(plate_data, catalogue)
    assert_rejected(exc, "duplicate machine_id", "M1")


def test_no_required_features(bracket_data, catalogue) -> None:
    for f in bracket_data["features"]:
        f["required"] = False
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "no required features")


def test_precedence_unknown_feature(bracket_data, catalogue) -> None:
    bracket_data["precedence_constraints"][0]["after"]["feature_id"] = "F99"
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "unknown feature", "F99")


def test_precedence_requires_rationale(bracket_data, catalogue) -> None:
    del bracket_data["precedence_constraints"][0]["rationale"]
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "rationale")


# --------------------------------------------------------------------------- catalogue cross-checks (unknown types)


def test_unknown_feature_type(bracket_data, catalogue) -> None:
    bracket_data["features"][2]["type"] = "dovetail"
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "F3", "unknown feature type", "dovetail")


def test_unknown_machine_capability(bracket_data, catalogue) -> None:
    bracket_data["resources"]["machines"][0]["capabilities"].append("laser_cutting")
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "M1", "unknown capabilities", "laser_cutting")


def test_unknown_tool_type(bracket_data, catalogue) -> None:
    bracket_data["resources"]["tools"][0]["type"] = "boring_bar"
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "T1", "unknown tool type", "boring_bar")


def test_unsuitable_required_operation(plate_data, catalogue) -> None:
    plate_data["features"][2]["required_operation_types"] = ["drilling", "pocket_milling"]
    with pytest.raises(InputValidationError) as exc:
        validate_component(plate_data, catalogue)
    assert_rejected(exc, "F3", "pocket_milling", "not suitable")


def test_precedence_inapplicable_operation(plate_data, catalogue) -> None:
    plate_data["precedence_constraints"][0]["after"]["operation_type"] = "reaming"
    with pytest.raises(InputValidationError) as exc:
        validate_component(plate_data, catalogue)
    assert_rejected(exc, "precedence_constraints[0].after", "reaming", "not applicable")


def test_precedence_cycle(bracket_data, catalogue) -> None:
    bracket_data["precedence_constraints"].append(
        {"before": {"feature_id": "F3"}, "after": {"feature_id": "F1"}, "rationale": "deliberate cycle"}
    )
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert_rejected(exc, "cycle", "F1:*", "F3:*")


def test_precedence_cycle_through_wildcard(plate_data, catalogue) -> None:
    # F3 tapping before all of F1, but all of F1 before all of F3 => F1 before F3 tapping: cycle.
    plate_data["precedence_constraints"].append(
        {"before": {"feature_id": "F3", "operation_type": "tapping"}, "after": {"feature_id": "F1"}, "rationale": "x"}
    )
    plate_data["precedence_constraints"].append(
        {"before": {"feature_id": "F1"}, "after": {"feature_id": "F3"}, "rationale": "y"}
    )
    with pytest.raises(InputValidationError) as exc:
        validate_component(plate_data, catalogue)
    assert_rejected(exc, "cycle")


def test_same_feature_op_precedence_is_not_a_cycle(plate_data, catalogue) -> None:
    # drilling -> tapping on F3 is a within-feature order, not a self-loop.
    validate_component(plate_data, catalogue)


def test_all_problems_reported_at_once(bracket_data, catalogue) -> None:
    bracket_data["features"][2]["type"] = "dovetail"
    bracket_data["resources"]["tools"][0]["type"] = "boring_bar"
    with pytest.raises(InputValidationError) as exc:
        validate_component(bracket_data, catalogue)
    assert len(exc.value.issues) == 2


# --------------------------------------------------------------------------- catalogue consistency


def test_catalogue_unknown_tool_in_compatibility(catalogue_data) -> None:
    catalogue_data["tool_compatibility"]["drilling"] = ["laser"]
    with pytest.raises(InputValidationError) as exc:
        parse_model(Catalogue, catalogue_data)
    assert_rejected(exc, "drilling", "unknown tool types", "laser")


def test_catalogue_operation_without_compatibility(catalogue_data) -> None:
    catalogue_data["operation_types"].append("grinding")
    with pytest.raises(InputValidationError) as exc:
        parse_model(Catalogue, catalogue_data)
    assert_rejected(exc, "without a tool_compatibility entry", "grinding")


# --------------------------------------------------------------------------- plan schema


def test_plan_missing_field(bracket_plan_data) -> None:
    del bracket_plan_data["operations"][0]["tool_id"]
    with pytest.raises(InputValidationError) as exc:
        parse_model(ProcessPlan, bracket_plan_data)
    assert_rejected(exc, "operations.0.tool_id", "Field required")


def test_plan_duplicate_operation_ids(bracket_plan_data) -> None:
    bracket_plan_data["operations"][1]["operation_id"] = "OP1"
    with pytest.raises(InputValidationError) as exc:
        parse_model(ProcessPlan, bracket_plan_data)
    assert_rejected(exc, "duplicate operation_id", "OP1")


@pytest.mark.parametrize("edge", [["OP1"], ["OP1", "OP2", "OP3"]])
def test_plan_malformed_precedence_edge(bracket_plan_data, edge) -> None:
    bracket_plan_data["precedence"] = [edge]
    with pytest.raises(InputValidationError) as exc:
        parse_model(ProcessPlan, bracket_plan_data)
    assert_rejected(exc, "precedence.0")


def test_plan_semantic_errors_left_to_validator(bracket_plan_data) -> None:
    """Unknown tool IDs, bad op types and negative durations parse; rules R1–R12 report them."""
    bracket_plan_data["operations"][0]["tool_id"] = "T99"
    bracket_plan_data["operations"][0]["type"] = "laser_cutting"
    bracket_plan_data["operations"][0]["duration_min"] = -1
    plan = parse_model(ProcessPlan, bracket_plan_data)
    assert plan.operations[0].tool_id == "T99"


# --------------------------------------------------------------------------- validation result schema


def test_validation_result_consistency() -> None:
    v = Violation(rule_id="R5_TOOL_COMPATIBILITY", severity="hard", message="x")
    cov = Coverage(required_features=3, covered_features=2, missing_features=["F3"])
    ValidationResult(valid=False, hard_constraint_violations=[v], coverage=cov)
    with pytest.raises(ValueError):
        ValidationResult(valid=True, hard_constraint_violations=[v], coverage=cov)
    with pytest.raises(ValueError):
        ValidationResult(valid=False, coverage=cov)
    with pytest.raises(ValueError):
        Coverage(required_features=3, covered_features=2, missing_features=[])
