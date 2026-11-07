"""Milestone 3 acceptance: corrupted plans are repaired; non-repairable cases stop safely; the loop is bounded."""

from __future__ import annotations

import itertools
import json

import pytest

from scmpa.io import EXAMPLE_COMPONENTS_DIR, load_catalogue, load_component, read_json, validate_component
from scmpa.llm import LLMError, ScriptedLLMClient
from scmpa.planning import FAULT_KINDS, FaultNotApplicable, LLMPlanner, MockPlanner, build_baseline_plan
from scmpa.planning.output_schema import SYSTEM_OWNED_PLAN_FIELDS
from scmpa.repair import REPAIR_OUTPUT_SCHEMA, LLMRepairAgent, RuleBasedRepairAgent
from scmpa.workflow import load_run, save_run, solve, stable_plan_hash

CATALOGUE = load_catalogue()
COMPONENT_IDS = ["demo_bracket_001", "demo_plate_002", "demo_block_003"]


def comp(cid: str):
    return load_component(EXAMPLE_COMPONENTS_DIR / f"{cid}.json", CATALOGUE)


def states(record) -> list[str]:
    return [t.state for t in record.transitions]


def model_json(plan, **overrides) -> str:
    data = plan.model_dump(mode="json", exclude=set(SYSTEM_OWNED_PLAN_FIELDS))
    data.update(overrides)
    return json.dumps(data)


def repaired_reply(plan, changes=("fixed",)) -> str:
    return json.dumps({"status": "REPAIRED", "changes": list(changes), "missing_information": [], "plan": json.loads(model_json(plan))})


def faulty_plan(cid: str, kind: str, seed: int = 0):
    return MockPlanner(faults=[kind], seed=seed).generate_plan(comp(cid), CATALOGUE).plan


# =========================================================================== happy path


@pytest.mark.parametrize("cid", COMPONENT_IDS)
def test_valid_initial_plan_is_accepted_without_repair(cid: str) -> None:
    record = solve(comp(cid), CATALOGUE, MockPlanner(), RuleBasedRepairAgent())
    assert record.final_status == "ACCEPTED" and record.stop_reason == "valid"
    assert record.repairs_used == 0 and len(record.iterations) == 1
    assert states(record) == ["RECEIVED", "INPUT_VALIDATED", "PLAN_GENERATED", "PLAN_VALIDATED", "ACCEPTED"]


# =========================================================================== repair of every injected fault kind


def _fault_cases():
    for cid, kind in itertools.product(COMPONENT_IDS, sorted(FAULT_KINDS)):
        for seed in range(3):
            yield cid, kind, seed


@pytest.mark.parametrize(("cid", "kind", "seed"), list(_fault_cases()))
def test_rule_based_repair_fixes_injected_fault(cid: str, kind: str, seed: int) -> None:
    try:
        planner = MockPlanner(faults=[kind], seed=seed)
        planner.generate_plan(comp(cid), CATALOGUE)
    except FaultNotApplicable:
        pytest.skip(f"{kind} not applicable to {cid}")
    record = solve(comp(cid), CATALOGUE, planner, RuleBasedRepairAgent(), max_repairs=3)
    assert record.initially_valid is False
    assert FAULT_KINDS[kind] in {v.rule_id for v in record.iterations[0].validation.hard_constraint_violations}
    assert record.final_status == "ACCEPTED", [v.message for v in record.final_validation.hard_constraint_violations]
    assert 1 <= record.repairs_used <= 3
    assert record.final_validation.warnings == []  # repair did not introduce duplicates etc.


@pytest.mark.parametrize("cid", ["demo_plate_002", "demo_block_003"])
def test_rule_based_repair_fixes_combined_faults(cid: str) -> None:
    # 3 faults on distinct operations (the block has only 4 operations; swap_precedence touches 2)
    faults = ["incompatible_tool", "swap_precedence", "invalid_duration"]
    record = solve(comp(cid), CATALOGUE, MockPlanner(faults=faults, seed=4), RuleBasedRepairAgent())
    assert record.initially_valid is False
    assert record.final_status == "ACCEPTED"


def test_repair_preserves_unaffected_operations() -> None:
    record = solve(comp("demo_plate_002"), CATALOGUE, MockPlanner(faults=["incompatible_tool"], seed=0), RuleBasedRepairAgent())
    diff = record.iterations[1].repair.diff
    assert diff["added"] == [] and diff["removed"] == []
    assert len(diff["modified"]) == 1
    [(op_id, fields)] = diff["modified"].items()
    assert set(fields) == {"tool_id"}
    assert len(diff["unchanged_operations"]) == 4


# =========================================================================== safe stops


def test_non_repairable_violation_stops_before_repair() -> None:
    data = read_json(EXAMPLE_COMPONENTS_DIR / "demo_block_003.json")
    data["features"][4]["required"] = True  # chamfer with no chamfer resources
    component = validate_component(data, CATALOGUE)

    class ExplodingAgent:
        name = "should_not_be_called"

        def repair_plan(self, *a, **k):
            raise AssertionError("repair must not be attempted for a non-repairable violation")

    record = solve(component, CATALOGUE, MockPlanner(), ExplodingAgent())
    assert record.final_status == "NEEDS_HUMAN_REVIEW"
    assert record.stop_reason == "non_repairable_violation"
    assert "chamfering" in record.stop_detail
    assert record.repairs_used == 0


def test_repeated_plan_detected() -> None:
    bad = faulty_plan("demo_bracket_001", "incompatible_tool")
    # The "repair" returns the same decisions with reworded text: same hash -> stop.
    reply = json.dumps({
        "status": "REPAIRED", "changes": ["reworded"], "missing_information": [],
        "plan": json.loads(model_json(bad, explanation="I promise this is fixed now.")),
    })
    agent = LLMRepairAgent(ScriptedLLMClient([reply]))
    record = solve(comp("demo_bracket_001"), CATALOGUE, MockPlanner(faults=["incompatible_tool"]), agent)
    assert record.stop_reason == "repeated_plan"
    assert record.final_status == "NEEDS_HUMAN_REVIEW"
    assert len(record.iterations) == 2
    assert record.iterations[0].plan_hash == record.iterations[1].plan_hash


def test_max_repairs_reached_and_loop_is_bounded() -> None:
    bad = faulty_plan("demo_bracket_001", "incompatible_tool")
    # Each "repair" changes a duration (new hash) but never fixes the tool.
    replies = []
    for n in range(10):
        data = json.loads(model_json(bad))
        data["operations"][0]["duration_min"] = 4.0 + n + 1
        replies.append(json.dumps({"status": "REPAIRED", "changes": [f"try {n}"], "missing_information": [], "plan": data}))
    client = ScriptedLLMClient(replies)
    record = solve(comp("demo_bracket_001"), CATALOGUE, MockPlanner(faults=["incompatible_tool"]), LLMRepairAgent(client), max_repairs=3)
    assert record.stop_reason == "max_repairs_reached"
    assert len(record.iterations) == 4 and record.repairs_used == 3
    assert len(client.calls) == 3


@pytest.mark.parametrize("max_repairs", [0, 1, 5])
def test_max_repairs_configurable(max_repairs: int) -> None:
    bad = faulty_plan("demo_bracket_001", "incompatible_tool")
    replies = []
    for n in range(10):
        data = json.loads(model_json(bad))
        data["operations"][0]["duration_min"] = 10.0 + n
        replies.append(json.dumps({"status": "REPAIRED", "changes": [], "missing_information": [], "plan": data}))
    client = ScriptedLLMClient(replies)
    record = solve(comp("demo_bracket_001"), CATALOGUE, MockPlanner(faults=["incompatible_tool"]), LLMRepairAgent(client), max_repairs=max_repairs)
    assert len(client.calls) == max_repairs
    assert record.stop_reason == "max_repairs_reached"


def test_max_repairs_from_env(monkeypatch) -> None:
    monkeypatch.setenv("SCMPA_MAX_REPAIRS", "1")
    record = solve(comp("demo_bracket_001"), CATALOGUE, MockPlanner(), RuleBasedRepairAgent())
    assert record.max_repairs == 1


def test_no_repair_agent_is_validate_only_baseline() -> None:
    record = solve(comp("demo_bracket_001"), CATALOGUE, MockPlanner(faults=["incompatible_tool"]), None)
    assert record.max_repairs == 0 and record.repairs_used == 0
    assert record.stop_reason == "max_repairs_reached"
    assert "REPAIR_REQUESTED" not in states(record)


def test_planner_failure_stops_safely() -> None:
    planner = LLMPlanner(ScriptedLLMClient(["garbage", "more garbage"]))
    record = solve(comp("demo_bracket_001"), CATALOGUE, planner, RuleBasedRepairAgent())
    assert record.final_status == "NEEDS_HUMAN_REVIEW" and record.stop_reason == "planner_output_invalid"
    assert record.iterations == [] and record.final_plan is None
    assert len(record.planner_result.attempts) == 2  # raw outputs preserved for analysis


def test_repair_output_invalid_stops_safely() -> None:
    agent = LLMRepairAgent(ScriptedLLMClient(["not json", LLMError("timeout")]))
    record = solve(comp("demo_bracket_001"), CATALOGUE, MockPlanner(faults=["incompatible_tool"]), agent)
    assert record.stop_reason == "repair_output_invalid"
    assert record.terminal_repair is not None and record.terminal_repair.status == "failed"
    assert record.repairs_used == 1


def test_repair_agent_can_request_human_review() -> None:
    reply = json.dumps({"status": "NEEDS_HUMAN_REVIEW", "changes": [], "missing_information": ["tap size unknown"]})
    agent = LLMRepairAgent(ScriptedLLMClient([reply]))
    record = solve(comp("demo_bracket_001"), CATALOGUE, MockPlanner(faults=["incompatible_tool"]), agent)
    assert record.stop_reason == "repair_agent_requested_review"
    assert "tap size unknown" in record.stop_detail
    assert record.terminal_repair.missing_information == ["tap size unknown"]


# =========================================================================== validator authority


def test_llm_claim_of_repair_is_revalidated_not_trusted() -> None:
    bad = faulty_plan("demo_bracket_001", "incompatible_tool")
    still_bad = build_baseline_plan(comp("demo_bracket_001"), CATALOGUE, "x").model_copy()
    still_bad_data = json.loads(model_json(still_bad))
    still_bad_data["operations"][1]["machine_id"] = "M_INVENTED"
    reply = json.dumps({"status": "REPAIRED", "changes": ["all fixed, plan is valid"], "missing_information": [], "plan": still_bad_data})
    good = repaired_reply(build_baseline_plan(comp("demo_bracket_001"), CATALOGUE, "y"))
    agent = LLMRepairAgent(ScriptedLLMClient([reply, good]))
    record = solve(comp("demo_bracket_001"), CATALOGUE, MockPlanner(faults=["incompatible_tool"]), agent)
    assert bad is not None
    assert record.iterations[1].validation.valid is False
    assert {v.rule_id for v in record.iterations[1].validation.hard_constraint_violations} == {"R2_MACHINE_EXISTS"}
    assert record.final_status == "ACCEPTED" and len(record.iterations) == 3


def test_repair_prompt_contains_exact_validator_findings() -> None:
    client = ScriptedLLMClient([repaired_reply(build_baseline_plan(comp("demo_bracket_001"), CATALOGUE, "y"))])
    solve(comp("demo_bracket_001"), CATALOGUE, MockPlanner(faults=["incompatible_tool"]), LLMRepairAgent(client))
    call = client.calls[0]
    assert call["json_schema"] is REPAIR_OUTPUT_SCHEMA
    user = call["messages"][1]["content"]
    assert '"rule_id": "R5_TOOL_COMPATIBILITY"' in user
    assert '"compatible_available_tools"' in user
    assert "1 hard violation(s)" in user


# =========================================================================== run record


def test_run_record_roundtrip_and_contents(tmp_path) -> None:
    record = solve(
        comp("demo_plate_002"), CATALOGUE, MockPlanner(faults=["swap_precedence"], seed=0), RuleBasedRepairAgent(), run_id="test123"
    )
    path = save_run(record, tmp_path)
    assert path.name == "demo_plate_002_test123.json"
    loaded = load_run(path)
    assert loaded == record
    assert loaded.versions["rule_set_version"] and loaded.versions["catalogue_id"] == CATALOGUE.catalogue_id
    assert loaded.planner_result.injected_faults[0]["kind"] == "swap_precedence"
    assert [it.source for it in loaded.iterations] == ["planner", "repair"]
    assert loaded.iterations[1].repair.changes == ["reordered operations to satisfy precedence"]
    assert states(loaded) == [
        "RECEIVED", "INPUT_VALIDATED", "PLAN_GENERATED", "PLAN_VALIDATED",
        "REPAIR_REQUESTED", "PLAN_REPAIRED", "PLAN_VALIDATED", "ACCEPTED",
    ]


def test_plan_hash_ignores_text_and_edge_order() -> None:
    plan = build_baseline_plan(comp("demo_plate_002"), CATALOGUE, "a")
    reworded = plan.model_copy(update={"plan_id": "b", "explanation": "different", "precedence": list(reversed(plan.precedence))})
    assert stable_plan_hash(plan) == stable_plan_hash(reworded)
    changed = plan.model_copy(update={"operations": list(reversed(plan.operations))})
    assert stable_plan_hash(plan) != stable_plan_hash(changed)


def test_optional_operation_without_resources_is_removed_not_escalated() -> None:
    """Regression from the LLM pilot: an extra spot-drilling op with no spot drill is repaired, not sent to review."""
    from scmpa.planning import PlanResult
    from scmpa.schemas import ProcessPlan

    component = comp("demo_plate_002")
    data = build_baseline_plan(component, CATALOGUE, "p").model_dump(mode="json")
    data["operations"].insert(2, {"operation_id": "OP9", "type": "spot_drilling", "target_features": ["F2"],
                                  "machine_id": "M1", "tool_id": "T2", "duration_min": 0.5, "notes": ""})

    class Fixed:
        name = "fixed"

        def generate_plan(self, *a, **k):
            return PlanResult(status="ok", plan=ProcessPlan.model_validate(data), planner="fixed")

    record = solve(component, CATALOGUE, Fixed(), RuleBasedRepairAgent())
    assert record.stop_reason == "valid" and record.repairs_used == 1
    assert "OP9" not in record.final_plan.sequence
