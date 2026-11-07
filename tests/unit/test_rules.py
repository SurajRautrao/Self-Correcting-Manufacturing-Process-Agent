"""Milestone 1 acceptance: every rule R1–R12 has positive and negative deterministic tests.

Each negative test corrupts one reference plan (or component) in a single,
targeted way and checks that the expected rule fires with usable evidence —
and, where it matters, that more basic failures do not cascade into noise.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable
from typing import Any

import pytest

from scmpa.io import EXAMPLE_COMPONENTS_DIR, REFERENCE_PLANS_DIR, load_catalogue, parse_model, read_json, validate_component
from scmpa.schemas import Component, ProcessPlan, ValidationResult, Violation
from scmpa.validation import ALL_RULES, ValidationConfig, validate_plan

COMPONENT_IDS = ["demo_bracket_001", "demo_plate_002", "demo_block_003"]
CATALOGUE = load_catalogue()

Mutator = Callable[[dict[str, Any]], None]


def component(cid: str, mutate: Mutator | None = None) -> Component:
    data = copy.deepcopy(read_json(EXAMPLE_COMPONENTS_DIR / f"{cid}.json"))
    if mutate:
        mutate(data)
    return validate_component(data, CATALOGUE, cid)


def plan(cid: str, mutate: Mutator | None = None) -> ProcessPlan:
    data = copy.deepcopy(read_json(REFERENCE_PLANS_DIR / f"{cid}_ref.json"))
    if mutate:
        mutate(data)
    return parse_model(ProcessPlan, data, cid)


def run(
    cid: str,
    plan_mut: Mutator | None = None,
    comp_mut: Mutator | None = None,
    config: ValidationConfig | None = None,
) -> ValidationResult:
    return validate_plan(plan(cid, plan_mut), component(cid, comp_mut), CATALOGUE, config)


def hard(result: ValidationResult, rule_id: str | None = None) -> list[Violation]:
    return [v for v in result.hard_constraint_violations if rule_id is None or v.rule_id == rule_id]


def rule_ids(result: ValidationResult) -> set[str]:
    return {v.rule_id for v in result.hard_constraint_violations + result.warnings}


def op(data: dict[str, Any], op_id: str) -> dict[str, Any]:
    return next(o for o in data["operations"] if o["operation_id"] == op_id)


# =========================================================================== positive: reference plans


@pytest.mark.parametrize("cid", COMPONENT_IDS)
def test_reference_plan_is_valid_with_no_warnings(cid: str) -> None:
    result = run(cid)
    assert result.valid, [v.message for v in result.hard_constraint_violations]
    assert result.warnings == []
    assert result.coverage.missing_features == []
    assert result.coverage.covered_features == result.coverage.required_features


@pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r.rule_id)
@pytest.mark.parametrize("cid", COMPONENT_IDS)
def test_each_rule_passes_each_reference_plan(rule, cid: str) -> None:
    """Positive case for every rule individually, on every reference plan."""
    assert rule.check(plan(cid), _ctx(cid)) == []


def _ctx(cid: str):
    from scmpa.validation import ValidationContext

    return ValidationContext(component(cid), CATALOGUE)


def test_rule_registry_complete() -> None:
    ids = [r.rule_id for r in ALL_RULES]
    assert len(ids) == 12 and len(set(ids)) == 12
    assert [i.split("_")[0] for i in ids] == [f"R{n}" for n in range(1, 13)]


def test_validation_is_deterministic() -> None:
    mut = lambda d: (op(d, "OP2").update(tool_id="T3"), d["operations"].reverse())  # noqa: E731
    a, b = run("demo_bracket_001", mut), run("demo_bracket_001", mut)
    assert a.model_dump() == b.model_dump()


def test_result_records_versions() -> None:
    result = run("demo_bracket_001")
    assert result.catalogue_id == CATALOGUE.catalogue_id
    assert result.rule_set_version


# =========================================================================== R1 operation type


def test_r1_unknown_operation_type() -> None:
    result = run("demo_bracket_001", lambda d: op(d, "OP2").update(type="laser_cutting"))
    [v] = hard(result, "R1_OPERATION_TYPE")
    assert v.operation_id == "OP2"
    assert v.evidence["operation_type"] == "laser_cutting"
    assert "drilling" in v.repair_hint  # suggests a suitable type for F2
    # no cascade into capability / tool rules for the same op
    assert not hard(result, "R3_MACHINE_CAPABILITY") and not hard(result, "R5_TOOL_COMPATIBILITY")


# =========================================================================== R2 machine exists


def test_r2_unknown_machine() -> None:
    result = run("demo_bracket_001", lambda d: op(d, "OP1").update(machine_id="M9"))
    [v] = hard(result, "R2_MACHINE_EXISTS")
    assert v.operation_id == "OP1" and v.evidence["selected_machine"] == "M9"
    assert "M1" in v.repair_hint
    assert rule_ids(result) == {"R2_MACHINE_EXISTS"}


# =========================================================================== R3 machine capability


def test_r3_machine_lacks_capability() -> None:
    # M1 on the plate cannot tap
    result = run("demo_plate_002", lambda d: op(d, "OP5").update(machine_id="M1"))
    [v] = hard(result, "R3_MACHINE_CAPABILITY")
    assert v.operation_id == "OP5"
    assert v.evidence["capable_machines"] == ["M2"]
    assert v.repairable
    assert rule_ids(result) == {"R3_MACHINE_CAPABILITY"}


def test_r3_no_capable_machine_is_not_repairable() -> None:
    def drop_tapping(d):
        d["resources"]["machines"][1]["capabilities"] = ["drilling"]

    result = run("demo_plate_002", comp_mut=drop_tapping)
    [v] = hard(result, "R3_MACHINE_CAPABILITY")
    assert v.repairable is False and "human review" in v.repair_hint


# =========================================================================== R4 tool exists


def test_r4_unknown_tool() -> None:
    result = run("demo_bracket_001", lambda d: op(d, "OP2").update(tool_id="T99"))
    [v] = hard(result, "R4_TOOL_EXISTS")
    assert v.evidence["selected_tool"] == "T99"
    assert "T2" in v.repair_hint
    assert rule_ids(result) == {"R4_TOOL_EXISTS"}  # no R5 cascade


# =========================================================================== R5 tool compatibility


def test_r5_incompatible_tool_brief_example() -> None:
    """The exact example from the project brief, section 4.3."""
    result = run("demo_bracket_001", lambda d: op(d, "OP2").update(tool_id="T3"))
    [v] = hard(result, "R5_TOOL_COMPATIBILITY")
    assert v.operation_id == "OP2"
    assert v.evidence["selected_tool"] == "T3"
    assert v.evidence["allowed_tool_types"] == ["drill"]
    assert v.evidence["compatible_available_tools"] == ["T2"]
    assert rule_ids(result) == {"R5_TOOL_COMPATIBILITY"}


def test_r5_no_compatible_tool_is_not_repairable() -> None:
    def remove_tap(d):
        d["resources"]["tools"] = [t for t in d["resources"]["tools"] if t["type"] != "tap"]

    result = run("demo_plate_002", lambda d: op(d, "OP5").update(tool_id="T3"), remove_tap)
    [v] = hard(result, "R5_TOOL_COMPATIBILITY")
    assert v.repairable is False


# =========================================================================== R6 feature coverage


def test_r6_missing_required_feature() -> None:
    def drop_pocket(d):
        d["operations"] = [o for o in d["operations"] if o["operation_id"] != "OP3"]
        d["precedence"] = [e for e in d["precedence"] if "OP3" not in e]

    result = run("demo_bracket_001", drop_pocket)
    [v] = hard(result, "R6_FEATURE_COVERAGE")
    assert v.feature_id == "F3" and v.evidence["requirement"] == "any_of"
    assert v.repairable and "pocket_milling on M1 with T3" in v.repair_hint
    assert result.coverage.missing_features == ["F3"]
    assert result.coverage.covered_features == 2
    assert rule_ids(result) == {"R6_FEATURE_COVERAGE"}


def test_r6_partially_covered_multi_operation_feature() -> None:
    def drop_tapping(d):
        d["operations"] = [o for o in d["operations"] if o["operation_id"] != "OP5"]
        d["precedence"] = [e for e in d["precedence"] if "OP5" not in e]

    result = run("demo_plate_002", drop_tapping)
    [v] = hard(result, "R6_FEATURE_COVERAGE")
    assert v.feature_id == "F3"
    assert v.evidence["requirement"] == "all_of"
    assert v.evidence["missing_operation_types"] == ["tapping"]
    assert v.evidence["applied_operation_types"] == ["drilling"]


def test_r6_unsuitable_operation_for_feature() -> None:
    # Drilling op retargeted at the pocket: unsuitable pairing, and F2 becomes uncovered.
    result = run("demo_bracket_001", lambda d: op(d, "OP2").update(target_features=["F3"]))
    violations = hard(result, "R6_FEATURE_COVERAGE")
    unsuitable = [v for v in violations if v.operation_id == "OP2"]
    missing = [v for v in violations if v.operation_id is None]
    assert len(unsuitable) == 1 and unsuitable[0].feature_id == "F3"
    assert [v.feature_id for v in missing] == ["F2"]


def test_r6_unproducible_required_feature_needs_human_review() -> None:
    # F5 (chamfer) made required, but the block has no chamfer capability or tool.
    result = run("demo_block_003", comp_mut=lambda d: d["features"][4].update(required=True))
    [v] = hard(result, "R6_FEATURE_COVERAGE")
    assert v.feature_id == "F5"
    assert v.repairable is False
    assert v.evidence["resource_options"] == {"chamfering": []}
    assert "human review" in v.repair_hint


def test_r6_optional_feature_may_be_omitted() -> None:
    assert "R6_FEATURE_COVERAGE" not in rule_ids(run("demo_block_003"))


# =========================================================================== R7 feature references


def test_r7_unknown_feature_reference() -> None:
    result = run("demo_bracket_001", lambda d: op(d, "OP2").update(target_features=["F2", "F9"]))
    [v] = hard(result, "R7_FEATURE_REFERENCE")
    assert v.operation_id == "OP2" and v.feature_id == "F9"
    assert rule_ids(result) == {"R7_FEATURE_REFERENCE"}


# =========================================================================== R8 precedence validity


def test_r8_edge_to_unknown_operation() -> None:
    result = run("demo_bracket_001", lambda d: d["precedence"].append(["OP1", "OP9"]))
    [v] = hard(result, "R8_PRECEDENCE_VALIDITY")
    assert v.evidence["unknown_operations"] == ["OP9"]
    assert rule_ids(result) == {"R8_PRECEDENCE_VALIDITY"}


def test_r8_cycle() -> None:
    result = run("demo_bracket_001", lambda d: d["precedence"].append(["OP3", "OP1"]))
    [v] = hard(result, "R8_PRECEDENCE_VALIDITY")
    assert v.evidence["cycle"] == ["OP1", "OP3", "OP1"]


def test_r8_self_loop() -> None:
    result = run("demo_bracket_001", lambda d: d["precedence"].append(["OP2", "OP2"]))
    [v] = hard(result, "R8_PRECEDENCE_VALIDITY")
    assert v.evidence["cycle"] == ["OP2", "OP2"]
    assert not hard(result, "R9_PRECEDENCE_ORDER")


# =========================================================================== R9 precedence order


def test_r9_plan_edge_violated_by_sequence() -> None:
    # Declare OP3 -> OP2 but leave OP2 first in the sequence. No component constraint covers F2/F3.
    result = run("demo_bracket_001", lambda d: d["precedence"].append(["OP3", "OP2"]))
    [v] = hard(result, "R9_PRECEDENCE_ORDER")
    assert v.evidence["source"] == "plan_precedence"
    assert v.operation_id == "OP2"


def test_r9_component_constraint_violated_without_plan_edges() -> None:
    def drill_first_no_edges(d):
        d["operations"] = [op(d, "OP2"), op(d, "OP1"), op(d, "OP3")]
        d["precedence"] = []

    result = run("demo_bracket_001", drill_first_no_edges)
    [v] = hard(result, "R9_PRECEDENCE_ORDER")
    assert v.evidence["source"] == "component_precedence_constraint"
    assert v.evidence["before_operation"] == "OP1" and v.evidence["after_operation"] == "OP2"
    assert "datum" in v.evidence["rationale"]


def test_r9_operation_specific_constraint() -> None:
    def tap_before_drill(d):
        ops = d["operations"]
        ops[3], ops[4] = ops[4], ops[3]
        d["precedence"] = [e for e in d["precedence"] if e != ["OP4", "OP5"]]

    result = run("demo_plate_002", tap_before_drill)
    [v] = hard(result, "R9_PRECEDENCE_ORDER")
    assert v.evidence["before"] == {"feature_id": "F3", "operation_type": "drilling"}
    assert v.operation_id == "OP5"


def test_r9_single_operation_spanning_ordered_features() -> None:
    # Bracket: OP1 faces F1 *and* claims F2; F1 must precede F2.
    result = run("demo_bracket_001", lambda d: op(d, "OP1").update(target_features=["F1", "F2"]))
    spans = [v for v in hard(result, "R9_PRECEDENCE_ORDER") if v.evidence["before_operation"] == v.evidence["after_operation"]]
    assert len(spans) == 1 and spans[0].operation_id == "OP1"


def test_r9_alternative_valid_order_accepted() -> None:
    """OP2 and OP3 are unordered relative to each other; swapping them must stay valid."""
    def swap(d):
        ops = d["operations"]
        ops[1], ops[2] = ops[2], ops[1]

    assert run("demo_bracket_001", swap).valid


# =========================================================================== R10 duplicates


def _duplicate_drill(d):
    d["operations"].append(dict(op(d, "OP2"), operation_id="OP4"))


def test_r10_duplicate_is_warning_by_default() -> None:
    result = run("demo_bracket_001", _duplicate_drill)
    assert result.valid
    [w] = result.warnings
    assert w.rule_id == "R10_DUPLICATE_OPERATION" and w.evidence["operation_ids"] == ["OP2", "OP4"]


def test_r10_duplicate_can_be_hard() -> None:
    result = run("demo_bracket_001", _duplicate_drill, config=ValidationConfig(duplicate_severity="hard"))
    assert not result.valid
    assert [v.rule_id for v in hard(result)] == ["R10_DUPLICATE_OPERATION"]


def test_r10_allowed_duplicate_type() -> None:
    result = run("demo_bracket_001", _duplicate_drill, config=ValidationConfig(allowed_duplicate_operation_types=["drilling"]))
    assert rule_ids(result) == set()


def test_r10_different_operations_on_same_feature_are_not_duplicates() -> None:
    assert "R10_DUPLICATE_OPERATION" not in rule_ids(run("demo_plate_002"))  # drill + tap on F3


# =========================================================================== R11 durations


@pytest.mark.parametrize("value", [0, -1.5, math.inf, math.nan])
def test_r11_non_positive_or_non_finite_duration_is_hard(value: float) -> None:
    result = run("demo_bracket_001", lambda d: op(d, "OP1").update(duration_min=value))
    [v] = hard(result, "R11_DURATION")
    assert v.operation_id == "OP1"


def test_r11_over_bound_is_warning_by_default() -> None:
    result = run("demo_bracket_001", lambda d: op(d, "OP1").update(duration_min=500))
    assert result.valid
    [w] = result.warnings
    assert w.rule_id == "R11_DURATION" and w.evidence["max_duration_min"] == 240.0


def test_r11_over_bound_configurable() -> None:
    cfg = ValidationConfig(max_duration_min=3.0, duration_bound_severity="hard")
    result = run("demo_bracket_001", config=cfg)
    assert {v.operation_id for v in hard(result, "R11_DURATION")} == {"OP1", "OP3"}  # 4.0 and 6.0 min


# =========================================================================== R12 completeness


def test_r12_wrong_component_id() -> None:
    result = run("demo_bracket_001", lambda d: d.update(component_id="demo_plate_002"))
    [v] = hard(result, "R12_COMPLETENESS")
    assert v.evidence["expected_component_id"] == "demo_bracket_001"


def test_r12_empty_plan() -> None:
    def empty(d):
        d["operations"], d["precedence"] = [], []

    result = run("demo_bracket_001", empty)
    assert any(v.message == "Plan contains no operations." for v in hard(result, "R12_COMPLETENESS"))
    assert result.coverage.covered_features == 0


def test_r12_operation_without_targets() -> None:
    result = run("demo_block_003", lambda d: op(d, "OP3").update(target_features=[]))
    [v] = hard(result, "R12_COMPLETENESS")
    assert v.operation_id == "OP3"


def test_r12_blank_explanation() -> None:
    result = run("demo_bracket_001", lambda d: d.update(explanation="   "))
    [v] = hard(result, "R12_COMPLETENESS")
    assert v.evidence["field"] == "explanation"


# =========================================================================== combined


def test_multiple_independent_violations_all_reported() -> None:
    def corrupt(d):
        op(d, "OP1").update(machine_id="M9")
        op(d, "OP2").update(tool_id="T3")
        op(d, "OP3").update(duration_min=-2)

    result = run("demo_bracket_001", corrupt)
    assert [v.rule_id for v in result.hard_constraint_violations] == [
        "R2_MACHINE_EXISTS",
        "R5_TOOL_COMPATIBILITY",
        "R11_DURATION",
    ]
    assert result.model_dump_json()  # serialisable for run logs


# =========================================================================== R3/R5 repairability of optional operations


def _add_spot_drill(d):
    """Spot drilling on F2 with a drill: the bracket has no spot drill, and drilling (OP2) already covers F2."""
    d["operations"].insert(1, {"operation_id": "OP9", "type": "spot_drilling", "target_features": ["F2"],
                               "machine_id": "M1", "tool_id": "T2", "duration_min": 0.5})


def _m1_can_spot_drill(d):
    d["resources"]["machines"][0]["capabilities"].append("spot_drilling")


def test_r5_unresolvable_but_removable_operation_is_repairable() -> None:
    result = run("demo_bracket_001", _add_spot_drill, _m1_can_spot_drill)
    [v] = hard(result, "R5_TOOL_COMPATIBILITY")
    assert v.operation_id == "OP9"
    assert v.evidence["compatible_available_tools"] == []
    assert v.evidence["operation_removable"] is True
    assert v.repairable is True and "remove it" in v.repair_hint


def test_r3_unresolvable_but_removable_operation_is_repairable() -> None:
    result = run("demo_bracket_001", _add_spot_drill)  # no machine can spot drill
    [v] = hard(result, "R3_MACHINE_CAPABILITY")
    assert v.repairable is True and v.evidence["operation_removable"] is True


def test_r5_needed_operation_without_tool_stays_non_repairable() -> None:
    def remove_tap(d):
        d["resources"]["tools"] = [t for t in d["resources"]["tools"] if t["type"] != "tap"]

    result = run("demo_plate_002", lambda d: op(d, "OP5").update(tool_id="T3"), remove_tap)
    [v] = hard(result, "R5_TOOL_COMPATIBILITY")
    assert v.evidence["operation_removable"] is False and v.repairable is False
