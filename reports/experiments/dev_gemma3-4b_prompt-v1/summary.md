# Experiment `dev_gemma3-4b_prompt-v1`

Prompt development on the DEV split: planner prompt v1, gemma3:4b, 8 dev parts x 3 seeds, B0/B1/R only (planner calls, no LLM repair). Compare dev_gemma3-4b_prompt-v1 with -v2; not a reportable result.

- Benchmark: `scmpa_synthetic_v1` (manifest sha256 `6f5de0faafb24a07`), split **dev**, 8 components, seeds [0, 1, 2]
- Planner: `{"provider": "ollama", "model": "gemma3:4b", "temperature": 0.7, "prompt_version": "v1"}`; LLM repair (B2): `null`; max repairs 3
- Rule set 1.2, catalogue `scmpa_demo_catalogue_v1` (sha256 `1770637895736ed9`), scmpa 0.1.0, Python 3.11.11
- **All data is synthetic.** These results describe software behaviour on a toy benchmark, not industrial performance.
- R is a deterministic rule-based repair agent included as a reference point. It is not an AI result.

## Track: generation

| System | Cases | Planner failures | Hard-violation rate [95% CI] | Repair success | Coverage | Precedence acc. | Seq. similarity | Human-review recall | Human-review precision | Correct outcome | Invalid plan accepted | Mean latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 LLM-only (unchecked) | 24 | 0% (0/24) | 62% (15/24) [43%–79%] | 0% (0/15) | 0.82 | 0.70 | 0.96 | 0% (0/6) | – | 38% (9/24) | 62% (15/24) | 5.9 |
| B1 + validator | 24 | 0% (0/24) | 62% (15/24) [43%–79%] | 0% (0/15) | 0.82 | 0.70 | 0.96 | 100% (6/6) | 40% (6/15) | 62% (15/24) | 0% (0/24) | 5.9 |
| R rule-based repair (non-AI reference) | 24 | 0% (0/24) | 25% (6/24) [12%–45%] | 60% (9/15) | 0.97 | 0.97 | 0.90 | 100% (6/6) | 100% (6/6) | 100% (24/24) | 0% (0/24) | 5.9 |

Spread across seeds (SD of the per-seed hard-violation rate): B0 0.00, B1 0.00, R 0.00

Repair rounds among repaired cases (mean / median): R 1.00 / 1

Initial hard violations by rule, over 24 initial plans:

| Rule | Violations | Plans affected |
|---|---|---|
| R6_FEATURE_COVERAGE | 20 | 12 |
| R5_TOOL_COMPATIBILITY | 27 | 11 |
| R9_PRECEDENCE_ORDER | 5 | 4 |
| R3_MACHINE_CAPABILITY | 3 | 3 |

Stop reasons:

| System | Stop reason | Count |
|---|---|---|
| B1 | max_repairs_reached | 9 |
| B1 | non_repairable_violation | 6 |
| B1 | valid | 9 |
| R | non_repairable_violation | 6 |
| R | valid | 18 |

## How to read this

- **Hard-violation rate**: share of cases whose final plan breaks at least one hard rule. A planner failure counts as invalid.
- **Repair success**: share of initially invalid cases that end valid. This includes infeasible components, which cannot become valid by design.
- **Correct outcome**: a feasible component ends with a valid plan, or an infeasible component is routed to human review.
- **Sequence similarity** compares the plan with one generated reference plan. Other valid orders exist, so this is descriptive only.
- The validator can mark a plan valid that is wrong in ways it does not model (tool size, access, setups). See `docs/assumptions_and_limits.md`.
