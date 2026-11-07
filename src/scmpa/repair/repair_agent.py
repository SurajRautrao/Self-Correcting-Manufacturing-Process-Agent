"""Repair-agent interface, result type, and the LLM-backed repair agent.

A repair agent receives a plan plus the validator's findings and returns a
revised plan, a request for human review, or a controlled failure. It never
decides validity: the workflow revalidates every repaired plan.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import Field

from scmpa.llm.base import ChatMessage, LLMClient, LLMError
from scmpa.planning.normalize import PlanningError, extract_json, normalize_plan_data
from scmpa.planning.output_schema import PLAN_OUTPUT_SCHEMA
from scmpa.planning.planner import PlanAttempt, model_view_of_catalogue, model_view_of_component
from scmpa.prompts import load_prompt
from scmpa.schemas import Catalogue, Component, ProcessPlan, ValidationResult
from scmpa.schemas.base import StrictModel

REPAIR_PROMPT_VERSION = "v1"

REPAIR_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["REPAIRED", "NEEDS_HUMAN_REVIEW"]},
        "changes": {"type": "array", "items": {"type": "string"}},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "plan": PLAN_OUTPUT_SCHEMA,
    },
    "required": ["status", "changes", "missing_information"],
}


class RepairResult(StrictModel):
    """Outcome of one repair request."""

    status: Literal["repaired", "needs_human_review", "failed"]
    plan: ProcessPlan | None = None
    changes: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    agent: str
    model: str | None = None
    prompt_refs: list[str] = Field(default_factory=list)
    attempts: list[PlanAttempt] = Field(default_factory=list)
    normalization_notes: list[str] = Field(default_factory=list)
    error: str | None = None


class RepairAgent(Protocol):
    """Anything that revises a plan given validator findings."""

    name: str

    def repair_plan(
        self, component: Component, catalogue: Catalogue, plan: ProcessPlan, validation: ValidationResult, *, plan_id: str
    ) -> RepairResult: ...


def model_view_of_plan(plan: ProcessPlan) -> dict[str, Any]:
    """The plan as the model should see it: no system-owned bookkeeping."""
    return plan.model_dump(mode="json", exclude={"plan_id", "schema_version", "provenance"})


def model_view_of_findings(validation: ValidationResult) -> dict[str, Any]:
    """Exact validator output passed to the repair model."""
    return validation.model_dump(mode="json", include={"hard_constraint_violations", "warnings", "coverage"})


def parse_repair_output(text: str, *, plan_id: str) -> tuple[str, ProcessPlan | None, list[str], list[str], list[str]]:
    """Return ``(status, plan, changes, missing_information, notes)``; raise :class:`PlanningError` if unusable."""
    data = extract_json(text)
    if not isinstance(data, dict):
        raise PlanningError([f"top-level JSON must be an object, got {type(data).__name__}"])
    status = data.get("status")
    if status not in ("REPAIRED", "NEEDS_HUMAN_REVIEW"):
        raise PlanningError([f"status must be 'REPAIRED' or 'NEEDS_HUMAN_REVIEW', got {status!r}"])
    changes = [str(c) for c in data.get("changes") or []]
    missing = [str(m) for m in data.get("missing_information") or []]
    if status == "NEEDS_HUMAN_REVIEW":
        return status, None, changes, missing, []
    if not isinstance(data.get("plan"), dict):
        raise PlanningError(["status is 'REPAIRED' but 'plan' is missing or not an object"])
    plan, notes = normalize_plan_data(data["plan"], plan_id=plan_id)
    return status, plan, changes, missing, notes


class LLMRepairAgent:
    """Repairs a plan with an LLM. Retries only on schema/parse failures of its own output."""

    name = "llm"

    def __init__(self, client: LLMClient, *, max_attempts: int = 2, prompt_version: str = REPAIR_PROMPT_VERSION) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.client = client
        self.max_attempts = max_attempts
        self.system_prompt = load_prompt("repair_system", prompt_version)
        self.user_prompt = load_prompt("repair_user", prompt_version)
        self.retry_prompt = load_prompt("planner_retry", "v1")

    def build_messages(
        self, component: Component, catalogue: Catalogue, plan: ProcessPlan, validation: ValidationResult
    ) -> list[ChatMessage]:
        user = self.user_prompt.render(
            component_json=json.dumps(model_view_of_component(component), indent=2),
            catalogue_json=json.dumps(model_view_of_catalogue(catalogue), indent=2),
            plan_json=json.dumps(model_view_of_plan(plan), indent=2),
            findings_json=json.dumps(model_view_of_findings(validation), indent=2),
            violation_count=len(validation.hard_constraint_violations),
            component_id=component.component_id,
        )
        return [{"role": "system", "content": self.system_prompt.text}, {"role": "user", "content": user}]

    def repair_plan(
        self, component: Component, catalogue: Catalogue, plan: ProcessPlan, validation: ValidationResult, *, plan_id: str
    ) -> RepairResult:
        messages = self.build_messages(component, catalogue, plan, validation)
        refs = [self.system_prompt.ref, self.user_prompt.ref]
        attempts: list[PlanAttempt] = []
        for n in range(1, self.max_attempts + 1):
            try:
                response = self.client.complete(messages, json_schema=REPAIR_OUTPUT_SCHEMA)
            except LLMError as exc:
                attempts.append(PlanAttempt(attempt=n, issues=[f"LLM error: {exc}"]))
                continue
            attempt = PlanAttempt(
                attempt=n, raw_output=response.text, latency_s=response.latency_s,
                prompt_tokens=response.prompt_tokens, completion_tokens=response.completion_tokens,
            )
            attempts.append(attempt)
            try:
                status, new_plan, changes, missing, notes = parse_repair_output(response.text, plan_id=plan_id)
            except PlanningError as exc:
                attempt.issues = exc.issues
                if self.retry_prompt.ref not in refs:
                    refs.append(self.retry_prompt.ref)
                messages = messages + [
                    {"role": "assistant", "content": response.text},
                    {"role": "user", "content": self.retry_prompt.render(issues="\n".join(f"- {i}" for i in exc.issues))},
                ]
                continue
            return RepairResult(
                status="repaired" if status == "REPAIRED" else "needs_human_review",
                plan=new_plan, changes=changes, missing_information=missing, agent=self.name,
                model=self.client.model, prompt_refs=refs, attempts=attempts, normalization_notes=notes,
            )
        last = attempts[-1].issues if attempts else []
        return RepairResult(
            status="failed", agent=self.name, model=self.client.model, prompt_refs=refs, attempts=attempts,
            error=f"no usable repair output after {len(attempts)} attempt(s): " + "; ".join(last),
        )
