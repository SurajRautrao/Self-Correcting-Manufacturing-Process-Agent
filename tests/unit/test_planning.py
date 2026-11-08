"""Milestone 2 acceptance: the planner returns a schema-valid plan or a controlled, understandable failure."""

from __future__ import annotations

import io
import json
import random
import urllib.error

import pytest

from scmpa.io import EXAMPLE_COMPONENTS_DIR, REFERENCE_PLANS_DIR, load_catalogue, load_component, read_json, validate_component
from scmpa.llm import LLMError, OllamaClient, OllamaConfig, ScriptedLLMClient
from scmpa.planning import (
    FAULT_KINDS,
    FaultNotApplicable,
    LLMPlanner,
    MockPlanner,
    PlanningError,
    build_baseline_plan,
    inject_fault,
    make_planner,
    normalize_plan_output,
)
from scmpa.planning.output_schema import PLAN_OUTPUT_SCHEMA, SYSTEM_OWNED_PLAN_FIELDS
from scmpa.prompts import load_prompt
from scmpa.schemas import Operation, ProcessPlan
from scmpa.validation import validate_plan

CATALOGUE = load_catalogue()
COMPONENT_IDS = ["demo_bracket_001", "demo_plate_002", "demo_block_003"]


def comp(cid: str):
    return load_component(EXAMPLE_COMPONENTS_DIR / f"{cid}.json", CATALOGUE)


def ref_plan_json(cid: str) -> str:
    """A reference plan as a model would return it (no system-owned fields)."""
    data = read_json(REFERENCE_PLANS_DIR / f"{cid}_ref.json")
    for key in SYSTEM_OWNED_PLAN_FIELDS:
        data.pop(key, None)
    return json.dumps(data)


# =========================================================================== mock planner


@pytest.mark.parametrize("cid", COMPONENT_IDS)
def test_mock_plan_is_valid(cid: str) -> None:
    component = comp(cid)
    result = MockPlanner().generate_plan(component, CATALOGUE)
    assert result.status == "ok" and result.plan is not None
    validation = validate_plan(result.plan, component, CATALOGUE)
    assert validation.valid, [v.message for v in validation.hard_constraint_violations]
    assert validation.warnings == []


def test_mock_plan_is_deterministic() -> None:
    a = MockPlanner(faults=["incompatible_tool"], seed=3).generate_plan(comp("demo_plate_002"), CATALOGUE)
    b = MockPlanner(faults=["incompatible_tool"], seed=3).generate_plan(comp("demo_plate_002"), CATALOGUE)
    assert a.model_dump() == b.model_dump()


def test_mock_respects_operation_level_precedence() -> None:
    plan = build_baseline_plan(comp("demo_plate_002"), CATALOGUE, "p")
    seq = [(o.type, o.target_features[0]) for o in plan.operations]
    assert seq.index(("drilling", "F3")) < seq.index(("tapping", "F3"))
    assert seq[0] == ("face_milling", "F1")


def test_mock_unproducible_feature_yields_non_repairable_plan() -> None:
    data = read_json(EXAMPLE_COMPONENTS_DIR / "demo_block_003.json")
    data["features"][4]["required"] = True  # chamfer, but no chamfer resources
    component = validate_component(data, CATALOGUE)
    result = MockPlanner().generate_plan(component, CATALOGUE)
    assert result.plan.uncertainties and "F5" in result.plan.uncertainties[0]
    validation = validate_plan(result.plan, component, CATALOGUE)
    [v] = validation.hard_constraint_violations
    assert v.rule_id == "R6_FEATURE_COVERAGE" and v.repairable is False


# =========================================================================== fault injection


@pytest.mark.parametrize("kind", sorted(FAULT_KINDS))
def test_each_fault_is_detected_by_its_rule(kind: str) -> None:
    component = comp("demo_plate_002")
    result = MockPlanner(faults=[kind], seed=1).generate_plan(component, CATALOGUE)
    [record] = result.injected_faults
    assert record["expected_rule"] == FAULT_KINDS[kind]
    validation = validate_plan(result.plan, component, CATALOGUE)
    assert FAULT_KINDS[kind] in {v.rule_id for v in validation.hard_constraint_violations}


def test_fault_does_not_mutate_input() -> None:
    component = comp("demo_bracket_001")
    plan = build_baseline_plan(component, CATALOGUE, "p")
    before = plan.model_dump()
    inject_fault(plan, component, CATALOGUE, "swap_precedence", random.Random(0))
    assert plan.model_dump() == before


def test_inapplicable_fault_raises() -> None:
    component = comp("demo_bracket_001")  # single machine: no incapable alternative exists
    plan = build_baseline_plan(component, CATALOGUE, "p")
    with pytest.raises(FaultNotApplicable):
        inject_fault(plan, component, CATALOGUE, "incapable_machine", random.Random(0))


def test_unknown_fault_kind_rejected() -> None:
    with pytest.raises(ValueError, match="unknown fault kind"):
        MockPlanner(faults=["gremlins"]).generate_plan(comp("demo_bracket_001"), CATALOGUE)


# =========================================================================== normalizer


def test_normalize_plain_json() -> None:
    plan, notes = normalize_plan_output(ref_plan_json("demo_bracket_001"), plan_id="x")
    assert plan.plan_id == "x" and plan.component_id == "demo_bracket_001"
    assert notes == []


@pytest.mark.parametrize(
    "wrap",
    [
        lambda s: f"```json\n{s}\n```",
        lambda s: f"Here is the plan:\n{s}\nHope this helps!",
        lambda s: f"Sure.\n```\n{s}\n```",
    ],
    ids=["fenced", "prose", "bare-fence"],
)
def test_normalize_extracts_wrapped_json(wrap) -> None:
    plan, _ = normalize_plan_output(wrap(ref_plan_json("demo_bracket_001")), plan_id="x")
    assert len(plan.operations) == 3


def test_normalize_drops_unknown_fields_and_records_them() -> None:
    data = json.loads(ref_plan_json("demo_bracket_001"))
    data["notes"] = "extra"
    data["operations"][0]["spindle_rpm"] = 12000
    data["plan_id"] = "model_chose_this"
    plan, notes = normalize_plan_output(json.dumps(data), plan_id="sys_id")
    assert plan.plan_id == "sys_id"
    assert "dropped unknown plan field 'notes'" in notes
    assert "operations[0]: dropped unknown field 'spindle_rpm'" in notes
    assert "ignored model-supplied system field 'plan_id'" in notes


def test_normalize_benign_shape_fixes() -> None:
    data = json.loads(ref_plan_json("demo_bracket_001"))
    data["operations"][0]["target_features"] = "F1"
    data["precedence"] = [{"before": "OP1", "after": "OP2"}, ["OP1", "OP3"]]
    plan, notes = normalize_plan_output(json.dumps(data), plan_id="x")
    assert plan.operations[0].target_features == ["F1"]
    assert plan.precedence == [["OP1", "OP2"], ["OP1", "OP3"]]
    assert len(notes) == 2


def test_normalize_does_not_fix_semantics() -> None:
    """Unknown IDs survive normalization; the validator must see them."""
    data = json.loads(ref_plan_json("demo_bracket_001"))
    data["operations"][1]["tool_id"] = "T_INVENTED"
    plan, _ = normalize_plan_output(json.dumps(data), plan_id="x")
    assert plan.operations[1].tool_id == "T_INVENTED"


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("I cannot help with that.", "not valid JSON"),
        ("", "not valid JSON"),
        ("[1, 2, 3]", "must be an object"),
        ('{"component_id": "c", "operations": []}', "explanation"),
        (
            '{"component_id": "c", "explanation": "e", "operations": [{"operation_id": "OP1", "type": "drilling"}]}',
            "operations.0.machine_id",
        ),
    ],
)
def test_normalize_controlled_failures(text: str, fragment: str) -> None:
    with pytest.raises(PlanningError) as exc:
        normalize_plan_output(text, plan_id="x")
    assert any(fragment in issue for issue in exc.value.issues), exc.value.issues


# =========================================================================== LLM planner (scripted client)


def test_llm_planner_success() -> None:
    client = ScriptedLLMClient([ref_plan_json("demo_bracket_001")])
    result = LLMPlanner(client).generate_plan(comp("demo_bracket_001"), CATALOGUE)
    assert result.status == "ok"
    assert result.plan.plan_id == "demo_bracket_001_plan_v0"
    assert len(result.attempts) == 1 and result.attempts[0].issues == []
    assert all("@v1#" in ref for ref in result.prompt_refs)
    # structured-output schema was passed to the provider
    assert client.calls[0]["json_schema"] is PLAN_OUTPUT_SCHEMA


def test_llm_planner_prompt_contains_only_component_and_catalogue() -> None:
    client = ScriptedLLMClient([ref_plan_json("demo_bracket_001")])
    LLMPlanner(client).generate_plan(comp("demo_bracket_001"), CATALOGUE)
    system, user = client.calls[0]["messages"]
    assert system["role"] == "system" and "Never invent IDs" in system["content"]
    assert '"machine_id": "M1"' in user["content"] and '"tool_compatibility"' in user["content"]
    assert "provenance" not in user["content"]  # bookkeeping not sent to the model
    assert "{component_json}" not in user["content"]  # template fully rendered


def test_llm_planner_retries_on_schema_failure_with_feedback() -> None:
    client = ScriptedLLMClient(["not json at all", ref_plan_json("demo_bracket_001")])
    result = LLMPlanner(client, max_attempts=2).generate_plan(comp("demo_bracket_001"), CATALOGUE)
    assert result.status == "ok"
    assert len(result.attempts) == 2 and result.attempts[0].issues
    retry_msgs = client.calls[1]["messages"]
    assert retry_msgs[-2] == {"role": "assistant", "content": "not json at all"}
    assert "not valid JSON" in retry_msgs[-1]["content"]
    assert any(r.startswith("planner_retry@v1") for r in result.prompt_refs)


def test_llm_planner_controlled_failure_after_budget() -> None:
    client = ScriptedLLMClient(["nope", '{"operations": 5}'])
    result = LLMPlanner(client, max_attempts=2).generate_plan(comp("demo_bracket_001"), CATALOGUE)
    assert result.status == "failed" and result.plan is None
    assert "after 2 attempt(s)" in result.error
    assert [a.raw_output for a in result.attempts] == ["nope", '{"operations": 5}']


def test_llm_planner_transport_error_is_controlled() -> None:
    client = ScriptedLLMClient([LLMError("cannot reach Ollama"), LLMError("cannot reach Ollama")])
    result = LLMPlanner(client).generate_plan(comp("demo_bracket_001"), CATALOGUE)
    assert result.status == "failed"
    assert "cannot reach Ollama" in result.error


def test_llm_planner_ok_does_not_mean_valid() -> None:
    """Schema-valid but rule-violating output is returned as ok; the validator decides feasibility."""
    data = json.loads(ref_plan_json("demo_bracket_001"))
    data["operations"][1]["tool_id"] = "T3"
    result = LLMPlanner(ScriptedLLMClient([json.dumps(data)])).generate_plan(comp("demo_bracket_001"), CATALOGUE)
    assert result.status == "ok"
    assert not validate_plan(result.plan, comp("demo_bracket_001"), CATALOGUE).valid


# =========================================================================== prompts and output schema


def test_prompts_load_and_render() -> None:
    user = load_prompt("planner_user", "v1").render(component_json="{}", catalogue_json="{}", component_id="c1")
    assert '"component_id": "c1"' in user
    assert load_prompt("planner_retry", "v1").render(issues="- x").count("- x") == 1


def test_output_schema_matches_process_plan_model() -> None:
    plan_fields = set(ProcessPlan.model_fields) - SYSTEM_OWNED_PLAN_FIELDS
    assert set(PLAN_OUTPUT_SCHEMA["properties"]) == plan_fields
    op_schema = PLAN_OUTPUT_SCHEMA["properties"]["operations"]["items"]
    assert set(op_schema["properties"]) == set(Operation.model_fields) - {"notes"}
    assert set(op_schema["required"]) == {n for n, f in Operation.model_fields.items() if f.is_required()}


# =========================================================================== Ollama adapter (no network)


def test_ollama_request_body() -> None:
    client = OllamaClient(OllamaConfig(model="m", seed=7, temperature=0.1))
    body = client.build_request([{"role": "user", "content": "hi"}], {"type": "object"})
    assert body["model"] == "m" and body["stream"] is False
    assert body["format"] == {"type": "object"}
    assert body["options"]["seed"] == 7 and body["options"]["temperature"] == 0.1
    assert body["think"] is False


def test_ollama_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("SCMPA_LLM_MODEL", "gemma3:4b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example:1234")
    cfg = OllamaConfig.from_env(seed=5)
    assert (cfg.model, cfg.base_url, cfg.seed) == ("gemma3:4b", "http://example:1234", 5)


class _FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_ollama_parses_response(monkeypatch) -> None:
    payload = {"model": "m", "message": {"role": "assistant", "content": "{}"}, "prompt_eval_count": 10, "eval_count": 3}
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: _FakeHTTPResponse(json.dumps(payload).encode()))
    resp = OllamaClient(OllamaConfig(model="m")).complete([{"role": "user", "content": "x"}])
    assert (resp.text, resp.prompt_tokens, resp.completion_tokens) == ("{}", 10, 3)


def test_ollama_unreachable_raises_llm_error(monkeypatch) -> None:
    def boom(req, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(LLMError, match="cannot reach Ollama"):
        OllamaClient(OllamaConfig(model="m")).complete([{"role": "user", "content": "x"}])


def test_ollama_error_payload_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout: _FakeHTTPResponse(b'{"error": "model not found"}')
    )
    with pytest.raises(LLMError, match="model not found"):
        OllamaClient(OllamaConfig(model="m")).complete([{"role": "user", "content": "x"}])


# =========================================================================== factory


def test_factory_default_is_mock(monkeypatch) -> None:
    monkeypatch.delenv("SCMPA_LLM_PROVIDER", raising=False)
    assert isinstance(make_planner(), MockPlanner)


def test_factory_ollama(monkeypatch) -> None:
    planner = make_planner("ollama", model="gemma3:4b", max_attempts=3)
    assert isinstance(planner, LLMPlanner)
    assert planner.client.model == "gemma3:4b" and planner.max_attempts == 3


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unsupported LLM provider"):
        make_planner("skynet")


def test_multiple_faults_hit_distinct_operations() -> None:
    component = comp("demo_plate_002")
    result = MockPlanner(faults=["incompatible_tool", "swap_precedence", "missing_operation"], seed=2).generate_plan(component, CATALOGUE)
    touched = [op for f in result.injected_faults for op in f["operations"]]
    assert len(touched) == len(set(touched))
    rules = {v.rule_id for v in validate_plan(result.plan, component, CATALOGUE).hard_constraint_violations}
    assert {f["expected_rule"] for f in result.injected_faults} <= rules


# --------------------------------------------------------------------------- prompt v2


def test_prompt_v1_catalogue_view_is_unchanged_and_v2_adds_preparatory() -> None:
    v1 = LLMPlanner(ScriptedLLMClient([]), prompt_version="v1").build_messages(comp("demo_bracket_001"), CATALOGUE)
    v2 = LLMPlanner(ScriptedLLMClient([]), prompt_version="v2").build_messages(comp("demo_bracket_001"), CATALOGUE)
    assert "preparatory_operation_types" not in v1[1]["content"]  # v1 stays byte-identical to the recorded runs
    assert '"preparatory_operation_types"' in v2[1]["content"] and "spot_drilling" in v2[1]["content"]
    assert "NEVER complete it on their own" in v2[0]["content"] and "preparatory" not in v1[0]["content"]


def test_prompt_v2_planner_produces_a_plan_and_records_v2_refs() -> None:
    planner = LLMPlanner(ScriptedLLMClient([ref_plan_json("demo_bracket_001")]), prompt_version="v2")
    result = planner.generate_plan(comp("demo_bracket_001"), CATALOGUE)
    assert result.status == "ok"
    assert result.prompt_refs and all("@v2#" in ref for ref in result.prompt_refs)


def test_factory_passes_prompt_version() -> None:
    from scmpa.planning import make_planner

    assert make_planner("ollama", model="x", prompt_version="v2").prompt_version == "v2"
    assert make_planner("ollama", model="x").prompt_version == "v1"
