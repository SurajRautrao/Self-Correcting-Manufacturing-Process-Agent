# Experiment `llm_test_full_gemma3-27b_bench-v2`

Model-size check: gemma3:27b on benchmark v2, test split, prompt v1. Same family as gemma3:4b and same settings as llm_test_full_gemma3-4b_bench-v2 and llm_test_full_qwen3.5-9b_bench-v2, so it separates model size from model family. B0/B1/B2 (+R), both tracks, 3 seeds at temperature 0.7.

- Benchmark: `scmpa_synthetic_v2` (manifest sha256 `cd5264d26d08396a`), split **test**, 16 components, seeds [0, 1, 2]
- Planner: `{"provider": "ollama", "model": "gemma3:27b", "temperature": 0.7}`; LLM repair (B2): `{"provider": "ollama", "model": "gemma3:27b", "temperature": 0.7}`; max repairs 3
- Rule set 1.2, catalogue `scmpa_demo_catalogue_v1` (sha256 `1770637895736ed9`), scmpa 0.1.0, Python 3.11.11
- **All data is synthetic.** These results describe software behaviour on a toy benchmark, not industrial performance.
- R is a deterministic rule-based repair agent included as a reference point. It is not an AI result.

## Track: corruption

Initial plans are reference plans with injected faults, so this track measures repair independently of planner quality. B0 is not applicable.

| System | Cases | Planner failures | Hard-violation rate [95% CI] | Repair success | Coverage | Precedence acc. | Seq. similarity | Human-review recall | Human-review precision | Correct outcome | Invalid plan accepted | Mean latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 + validator | 39 | 0% (0/39) | 100% (39/39) [91%–100%] | 0% (0/39) | 0.95 | 0.85 | 0.97 | – | 0% (0/39) | 0% (0/39) | 0% (0/39) | 0.0 |
| B2 + LLM repair loop | 39 | 0% (0/39) | 8% (3/39) [3%–20%] | 92% (36/39) | 1.00 | 0.99 | 0.99 | – | 0% (0/3) | 92% (36/39) | 0% (0/39) | 20.7 |
| R rule-based repair (non-AI reference) | 39 | 0% (0/39) | 0% (0/39) [0%–9%] | 100% (39/39) | 1.00 | 1.00 | 0.97 | – | – | 100% (39/39) | 0% (0/39) | 0.0 |

Spread across seeds (SD of the per-seed hard-violation rate): B1 0.00, B2 0.13, R 0.00

Repair rounds among repaired cases (mean / median): B2 1.08 / 1, R 1.00 / 1

Initial hard violations by rule, over 39 initial plans:

| Rule | Violations | Plans affected |
|---|---|---|
| R6_FEATURE_COVERAGE | 16 | 16 |
| R3_MACHINE_CAPABILITY | 11 | 11 |
| R9_PRECEDENCE_ORDER | 64 | 11 |
| R5_TOOL_COMPATIBILITY | 10 | 10 |
| R7_FEATURE_REFERENCE | 10 | 10 |
| R11_DURATION | 7 | 7 |
| R4_TOOL_EXISTS | 7 | 7 |
| R2_MACHINE_EXISTS | 6 | 6 |
| R8_PRECEDENCE_VALIDITY | 6 | 6 |
| R1_OPERATION_TYPE | 5 | 5 |

Stop reasons:

| System | Stop reason | Count |
|---|---|---|
| B1 | max_repairs_reached | 39 |
| B2 | max_repairs_reached | 2 |
| B2 | repeated_plan | 1 |
| B2 | valid | 36 |
| R | valid | 39 |

## Track: generation

| System | Cases | Planner failures | Hard-violation rate [95% CI] | Repair success | Coverage | Precedence acc. | Seq. similarity | Human-review recall | Human-review precision | Correct outcome | Invalid plan accepted | Mean latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 LLM-only (unchecked) | 48 | 0% (0/48) | 38% (18/48) [25%–52%] | 0% (0/18) | 1.00 | 0.97 | 0.93 | 0% (0/9) | – | 62% (30/48) | 38% (18/48) | 18.5 |
| B1 + validator | 48 | 0% (0/48) | 38% (18/48) [25%–52%] | 0% (0/18) | 1.00 | 0.97 | 0.93 | 100% (9/9) | 50% (9/18) | 81% (39/48) | 0% (0/48) | 18.5 |
| B2 + LLM repair loop | 48 | 0% (0/48) | 21% (10/48) [12%–34%] | 44% (8/18) | 1.00 | 0.98 | 0.93 | 100% (9/9) | 90% (9/10) | 98% (47/48) | 0% (0/48) | 24.9 |
| R rule-based repair (non-AI reference) | 48 | 0% (0/48) | 19% (9/48) [10%–32%] | 50% (9/18) | 1.00 | 0.98 | 0.93 | 100% (9/9) | 100% (9/9) | 100% (48/48) | 0% (0/48) | 18.5 |

Spread across seeds (SD of the per-seed hard-violation rate): B0 0.06, B1 0.06, B2 0.04, R 0.00

Repair rounds among repaired cases (mean / median): B2 1.62 / 1.5, R 1.00 / 1

Initial hard violations by rule, over 48 initial plans:

| Rule | Violations | Plans affected |
|---|---|---|
| R5_TOOL_COMPATIBILITY | 40 | 14 |
| R9_PRECEDENCE_ORDER | 9 | 6 |
| R3_MACHINE_CAPABILITY | 3 | 3 |

Stop reasons:

| System | Stop reason | Count |
|---|---|---|
| B1 | max_repairs_reached | 9 |
| B1 | non_repairable_violation | 9 |
| B1 | valid | 30 |
| B2 | max_repairs_reached | 1 |
| B2 | non_repairable_violation | 9 |
| B2 | valid | 38 |
| R | non_repairable_violation | 9 |
| R | valid | 39 |

## How to read this

- **Hard-violation rate**: share of cases whose final plan breaks at least one hard rule. A planner failure counts as invalid.
- **Repair success**: share of initially invalid cases that end valid. This includes infeasible components, which cannot become valid by design.
- **Correct outcome**: a feasible component ends with a valid plan, or an infeasible component is routed to human review.
- **Sequence similarity** compares the plan with one generated reference plan. Other valid orders exist, so this is descriptive only.
- The validator can mark a plan valid that is wrong in ways it does not model (tool size, access, setups). See `docs/assumptions_and_limits.md`.
