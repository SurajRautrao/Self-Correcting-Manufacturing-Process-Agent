# Architecture

```
component JSON + catalogue
        │  io.load_component  (schema + catalogue checks; InputValidationError on bad input)
        ▼
   Planner.generate_plan ──────────────► PlanResult (ok | failed, raw attempts, prompt refs)
        │  LLMPlanner (Ollama) / MockPlanner (+ seeded fault injection)
        ▼
   validate_plan  (R1–R12, deterministic) ──► ValidationResult
        │ valid ──────────────────────────► ACCEPTED
        │ invalid
        │   ├─ repeated plan hash ─────────► NEEDS_HUMAN_REVIEW (repeated_plan)
        │   ├─ any repairable=False ───────► NEEDS_HUMAN_REVIEW (non_repairable_violation)
        │   ├─ repair budget used ─────────► NEEDS_HUMAN_REVIEW (max_repairs_reached)
        │   ▼
        │ RepairAgent.repair_plan ─────────► RepairResult (repaired | needs_human_review | failed)
        │   LLMRepairAgent (Ollama) / RuleBasedRepairAgent
        └──────── revised plan ──► validate_plan again (the loop)
```

The `workflow.solve()` call returns a `RunRecord` holding every candidate plan, its validation result, each repair call (changes, operation-level diff, raw model output, latency, tokens), the state transitions, the stop reason and version identifiers. `save_run()` writes it as JSON.

## Modules

| Module | Role | Deterministic |
|---|---|---|
| `schemas/` | Pydantic data contracts (component, catalogue, plan, validation result) | yes |
| `io.py` | Loading and input checks | yes |
| `validation/` | Rules R1–R12, `validate_plan()` | yes |
| `llm/` | `LLMClient` interface; `OllamaClient`, `ScriptedLLMClient` | adapter |
| `prompts.py`, `prompt_templates/` | Versioned prompt files with content hashes | yes |
| `planning/` | `LLMPlanner`, `MockPlanner`, normalizer, fault injection | LLM: no; mock: yes |
| `repair/` | `LLMRepairAgent`, `RuleBasedRepairAgent` | LLM: no; rule-based: yes |
| `workflow/` | Bounded loop, state machine, run records | yes, given its components |

## Authority boundaries

- The **validator** is the only component that decides validity. A repair agent's claim that a plan is fixed is ignored, because every repaired plan is revalidated.
- The **normalizer** may only make the shape fixes it documents, and it records each one. It never changes IDs or values. Semantic errors pass through so that the validator reports them.
- **Planner retries** report schema and parse problems only, never validator findings. `LLMPlanner` alone is therefore an honest LLM-only baseline.
- The **human-review gate** is reached by any of five routes: a violation the validator marks as non-repairable, a repeated plan, an exhausted budget, an explicit `NEEDS_HUMAN_REVIEW` from the repair agent, or unusable model output.

## Baselines this structure supports (used in M4)

| Baseline | Construction |
|---|---|
| B0 LLM-only | `LLMPlanner.generate_plan()`, validated afterwards only to measure it |
| B1 LLM + validator | `solve(..., repair_agent=None)` |
| B2 LLM + repair loop | `solve(..., repair_agent=LLMRepairAgent(...))` |
| (reference) rule-based repair | `solve(..., repair_agent=RuleBasedRepairAgent())`; not an AI result |
