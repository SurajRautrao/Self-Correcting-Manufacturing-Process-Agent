"""Planner interface, run-record types, and the LLM-backed planner."""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import Field

from scmpa.llm.base import ChatMessage, LLMClient, LLMError
from scmpa.planning.normalize import PlanningError, normalize_plan_output
from scmpa.planning.output_schema import PLAN_OUTPUT_SCHEMA
from scmpa.prompts import PLANNER_PROMPT_VERSION, load_prompt
from scmpa.schemas import Catalogue, Component, ProcessPlan
from scmpa.schemas.base import StrictModel


class PlanAttempt(StrictModel):
    """One model call and what came of it."""

    attempt: int
    raw_output: str | None = None
    issues: list[str] = Field(default_factory=list)
    latency_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class PlanResult(StrictModel):
    """Outcome of one planning request: a schema-valid plan, or a controlled failure with reasons.

    ``ok`` means the plan is *well-formed*, not that it satisfies the
    manufacturing rules — that is the validator's job.
    """

    status: Literal["ok", "failed"]
    plan: ProcessPlan | None = None
    planner: str
    model: str | None = None
    prompt_refs: list[str] = Field(default_factory=list)
    attempts: list[PlanAttempt] = Field(default_factory=list)
    normalization_notes: list[str] = Field(default_factory=list)
    injected_faults: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class Planner(Protocol):
    """Anything that proposes a process plan for a component."""

    name: str

    def generate_plan(self, component: Component, catalogue: Catalogue, *, plan_id: str | None = None) -> PlanResult: ...


def default_plan_id(component: Component, suffix: str = "v0") -> str:
    return f"{component.component_id}_plan_{suffix}"


def model_view_of_component(component: Component) -> dict[str, Any]:
    """What the model sees of a component: everything except data-provenance bookkeeping."""
    return component.model_dump(mode="json", exclude={"provenance", "schema_version"}, exclude_none=True)


def model_view_of_catalogue(catalogue: Catalogue) -> dict[str, Any]:
    """What the model sees of the catalogue: the vocabulary and compatibility maps."""
    return catalogue.model_dump(mode="json", include={"operation_types", "tool_types", "feature_types", "tool_compatibility"})


class LLMPlanner:
    """Generates a plan with an LLM, retrying only on *schema* failures.

    Retry feedback reports parse/schema problems only, never validator
    findings — so this planner remains a valid "LLM-only" baseline (B0/B1).
    """

    name = "llm"

    def __init__(self, client: LLMClient, *, max_attempts: int = 2, prompt_version: str = PLANNER_PROMPT_VERSION) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.client = client
        self.max_attempts = max_attempts
        self.system_prompt = load_prompt("planner_system", prompt_version)
        self.user_prompt = load_prompt("planner_user", prompt_version)
        self.retry_prompt = load_prompt("planner_retry", prompt_version)

    def build_messages(self, component: Component, catalogue: Catalogue) -> list[ChatMessage]:
        user = self.user_prompt.render(
            component_json=json.dumps(model_view_of_component(component), indent=2),
            catalogue_json=json.dumps(model_view_of_catalogue(catalogue), indent=2),
            component_id=component.component_id,
        )
        return [{"role": "system", "content": self.system_prompt.text}, {"role": "user", "content": user}]

    def generate_plan(self, component: Component, catalogue: Catalogue, *, plan_id: str | None = None) -> PlanResult:
        plan_id = plan_id or default_plan_id(component)
        messages = self.build_messages(component, catalogue)
        attempts: list[PlanAttempt] = []
        refs = [self.system_prompt.ref, self.user_prompt.ref]

        for n in range(1, self.max_attempts + 1):
            try:
                response = self.client.complete(messages, json_schema=PLAN_OUTPUT_SCHEMA)
            except LLMError as exc:
                attempts.append(PlanAttempt(attempt=n, issues=[f"LLM error: {exc}"]))
                continue
            attempt = PlanAttempt(
                attempt=n,
                raw_output=response.text,
                latency_s=response.latency_s,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
            )
            attempts.append(attempt)
            try:
                plan, notes = normalize_plan_output(response.text, plan_id=plan_id)
            except PlanningError as exc:
                attempt.issues = exc.issues
                if self.retry_prompt.ref not in refs:
                    refs.append(self.retry_prompt.ref)
                messages = messages + [
                    {"role": "assistant", "content": response.text},
                    {"role": "user", "content": self.retry_prompt.render(issues="\n".join(f"- {i}" for i in exc.issues))},
                ]
                continue
            return PlanResult(
                status="ok", plan=plan, planner=self.name, model=self.client.model,
                prompt_refs=refs, attempts=attempts, normalization_notes=notes,
            )

        last = attempts[-1].issues if attempts else []
        return PlanResult(
            status="failed", planner=self.name, model=self.client.model, prompt_refs=refs, attempts=attempts,
            error=f"no schema-valid plan after {len(attempts)} attempt(s): " + "; ".join(last),
        )
