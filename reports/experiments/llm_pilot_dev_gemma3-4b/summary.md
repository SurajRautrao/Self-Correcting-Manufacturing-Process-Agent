# Experiment `llm_pilot_dev_gemma3-4b`

Small LLM pilot on the dev split (prompt/pipeline check; numbers not to be reported as results). Ollama gemma3:4b, temperature 0.

- Benchmark: `scmpa_synthetic_v1` (manifest sha256 `2212ae165f6c2daa`), split **dev**, 4 components, seeds [0]
- Planner: `{"provider": "ollama", "model": "gemma3:4b", "temperature": 0.0}`; LLM repair (B2): `{"provider": "ollama", "model": "gemma3:4b", "temperature": 0.0}`; max repairs 3
- Rule set 1.1, catalogue `scmpa_demo_catalogue_v1`, scmpa 0.1.0, Python 3.12.4
- **All data is synthetic.** These results describe software behaviour on a toy benchmark, not industrial performance.
- R is a deterministic rule-based repair agent included as a reference point. It is not an AI result.

## Track: corruption

Initial plans are reference plans with injected faults, so this track measures repair independently of planner quality. B0 is not applicable.

| System | Cases | Planner failures | Hard-violation rate [95% CI] | Repair success | Coverage | Precedence acc. | Seq. similarity | Human-review recall | Human-review precision | Correct outcome | Invalid plan accepted | Mean latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 + validator | 3 | 0% (0/3) | 100% (3/3) [44%–100%] | 0% (0/3) | 1.00 | 0.80 | 0.89 | – | 0% (0/3) | 0% (0/3) | 0% (0/3) | 0.0 |
| B2 + LLM repair loop | 3 | 0% (0/3) | 0% (0/3) [0%–56%] | 100% (3/3) | 1.00 | 1.00 | 0.96 | – | – | 100% (3/3) | 0% (0/3) | 429.4 |
| R rule-based repair (non-AI reference) | 3 | 0% (0/3) | 0% (0/3) [0%–56%] | 100% (3/3) | 1.00 | 1.00 | 0.98 | – | – | 100% (3/3) | 0% (0/3) | 0.0 |

Repair rounds among repaired cases (mean / median): B2 1.67 / 1, R 1.00 / 1

Initial hard violations by rule, over 3 initial plans:

| Rule | Violations | Plans affected |
|---|---|---|
| R11_DURATION | 1 | 1 |
| R1_OPERATION_TYPE | 1 | 1 |
| R2_MACHINE_EXISTS | 1 | 1 |
| R5_TOOL_COMPATIBILITY | 1 | 1 |
| R7_FEATURE_REFERENCE | 1 | 1 |
| R9_PRECEDENCE_ORDER | 6 | 1 |

Stop reasons:

| System | Stop reason | Count |
|---|---|---|
| B1 | max_repairs_reached | 3 |
| B2 | valid | 3 |
| R | valid | 3 |

## Track: generation

| System | Cases | Planner failures | Hard-violation rate [95% CI] | Repair success | Coverage | Precedence acc. | Seq. similarity | Human-review recall | Human-review precision | Correct outcome | Invalid plan accepted | Mean latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 LLM-only (unchecked) | 4 | 0% (0/4) | 75% (3/4) [30%–95%] | 0% (0/3) | 0.78 | 0.60 | 0.97 | 0% (0/1) | – | 25% (1/4) | 75% (3/4) | 156.4 |
| B1 + validator | 4 | 0% (0/4) | 75% (3/4) [30%–95%] | 0% (0/3) | 0.78 | 0.60 | 0.97 | 100% (1/1) | 33% (1/3) | 50% (2/4) | 0% (0/4) | 156.4 |
| B2 + LLM repair loop | 4 | 0% (0/4) | 50% (2/4) [15%–85%] | 33% (1/3) | 0.89 | 0.80 | 0.96 | 100% (1/1) | 50% (1/2) | 75% (3/4) | 0% (0/4) | 460.6 |
| R rule-based repair (non-AI reference) | 4 | 0% (0/4) | 25% (1/4) [5%–70%] | 67% (2/3) | 0.95 | 0.93 | 0.82 | 100% (1/1) | 100% (1/1) | 100% (4/4) | 0% (0/4) | 156.4 |

Repair rounds among repaired cases (mean / median): B2 2.00 / 2, R 1.00 / 1

Initial hard violations by rule, over 4 initial plans:

| Rule | Violations | Plans affected |
|---|---|---|
| R6_FEATURE_COVERAGE | 4 | 3 |
| R5_TOOL_COMPATIBILITY | 4 | 2 |
| R3_MACHINE_CAPABILITY | 1 | 1 |
| R9_PRECEDENCE_ORDER | 1 | 1 |

Stop reasons:

| System | Stop reason | Count |
|---|---|---|
| B1 | max_repairs_reached | 2 |
| B1 | non_repairable_violation | 1 |
| B1 | valid | 1 |
| B2 | non_repairable_violation | 1 |
| B2 | repeated_plan | 1 |
| B2 | valid | 2 |
| R | non_repairable_violation | 1 |
| R | valid | 3 |

## How to read this

- **Hard-violation rate**: share of cases whose final plan breaks at least one hard rule. A planner failure counts as invalid.
- **Repair success**: share of initially invalid cases that end valid. This includes infeasible components, which cannot become valid by design.
- **Correct outcome**: a feasible component ends with a valid plan, or an infeasible component is routed to human review.
- **Sequence similarity** compares the plan with one generated reference plan. Other valid orders exist, so this is descriptive only.
- The validator can mark a plan valid that is wrong in ways it does not model (tool size, access, setups). See `docs/assumptions_and_limits.md`.
