# Experiment `llm_test_full_gemma3-4b_v1.2`

Post-hoc re-run of llm_test_full_gemma3-4b under rule set v1.2 (spot drilling is preparatory, so a spot-drill-only hole is a coverage violation) with best-candidate selection in the loop. The initial plans are replayed from the v1.1 run, so only validation and repair differ. The flaw was found on the test split, so report this next to the v1.1 run, never in place of it.

- Benchmark: `scmpa_synthetic_v1` (manifest sha256 `6f5de0faafb24a07`), split **test**, 16 components, seeds [0, 1, 2]
- Planner: `{"provider": "ollama", "model": "gemma3:4b", "temperature": 0.7}`; LLM repair (B2): `{"provider": "ollama", "model": "gemma3:4b", "temperature": 0.7}`; max repairs 3
- Rule set 1.2, catalogue `scmpa_demo_catalogue_v1` (sha256 `1770637895736ed9`), scmpa 0.1.0, Python 3.11.11
- Initial plans **replayed** from experiment `llm_test_full_gemma3-4b` (no new planner calls), so differences from that experiment come only from validation and repair.
- **All data is synthetic.** These results describe software behaviour on a toy benchmark, not industrial performance.
- R is a deterministic rule-based repair agent included as a reference point. It is not an AI result.

## Track: corruption

Initial plans are reference plans with injected faults, so this track measures repair independently of planner quality. B0 is not applicable.

| System | Cases | Planner failures | Hard-violation rate [95% CI] | Repair success | Coverage | Precedence acc. | Seq. similarity | Human-review recall | Human-review precision | Correct outcome | Invalid plan accepted | Mean latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 + validator | 39 | 0% (0/39) | 100% (39/39) [91%–100%] | 0% (0/39) | 0.93 | 0.77 | 0.95 | – | 0% (0/39) | 0% (0/39) | 0% (0/39) | 0.0 |
| B2 + LLM repair loop | 39 | 0% (0/39) | 38% (15/39) [25%–54%] | 62% (24/39) | 0.96 | 0.91 | 0.94 | – | 0% (0/15) | 62% (24/39) | 0% (0/39) | 42.4 |
| R rule-based repair (non-AI reference) | 39 | 0% (0/39) | 0% (0/39) [0%–9%] | 100% (39/39) | 1.00 | 1.00 | 0.96 | – | – | 100% (39/39) | 0% (0/39) | 0.0 |

Spread across seeds (SD of the per-seed hard-violation rate): B1 0.00, B2 0.08, R 0.00

Repair rounds among repaired cases (mean / median): B2 1.38 / 1, R 1.00 / 1

Initial hard violations by rule, over 39 initial plans:

| Rule | Violations | Plans affected |
|---|---|---|
| R9_PRECEDENCE_ORDER | 39 | 15 |
| R6_FEATURE_COVERAGE | 13 | 12 |
| R11_DURATION | 11 | 11 |
| R2_MACHINE_EXISTS | 9 | 9 |
| R5_TOOL_COMPATIBILITY | 8 | 8 |
| R7_FEATURE_REFERENCE | 8 | 8 |
| R1_OPERATION_TYPE | 7 | 7 |
| R3_MACHINE_CAPABILITY | 7 | 7 |
| R8_PRECEDENCE_VALIDITY | 7 | 7 |
| R4_TOOL_EXISTS | 5 | 5 |

Stop reasons:

| System | Stop reason | Count |
|---|---|---|
| B1 | max_repairs_reached | 39 |
| B2 | max_repairs_reached | 4 |
| B2 | repair_output_invalid | 2 |
| B2 | repeated_plan | 9 |
| B2 | valid | 24 |
| R | valid | 39 |

## Track: generation

| System | Cases | Planner failures | Hard-violation rate [95% CI] | Repair success | Coverage | Precedence acc. | Seq. similarity | Human-review recall | Human-review precision | Correct outcome | Invalid plan accepted | Mean latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 LLM-only (unchecked) | 48 | 0% (0/48) | 79% (38/48) [66%–88%] | 0% (0/38) | 0.67 | 0.55 | 0.96 | 0% (0/9) | – | 21% (10/48) | 79% (38/48) | 3.5 |
| B1 + validator | 48 | 0% (0/48) | 79% (38/48) [66%–88%] | 0% (0/38) | 0.67 | 0.55 | 0.96 | 100% (9/9) | 24% (9/38) | 40% (19/48) | 0% (0/48) | 3.5 |
| B2 + LLM repair loop | 48 | 0% (0/48) | 62% (30/48) [48%–75%] | 21% (8/38) | 0.77 | 0.69 | 0.95 | 100% (9/9) | 30% (9/30) | 56% (27/48) | 0% (0/48) | 29.3 |
| R rule-based repair (non-AI reference) | 48 | 0% (0/48) | 19% (9/48) [10%–32%] | 76% (29/38) | 0.94 | 0.95 | 0.92 | 100% (9/9) | 100% (9/9) | 100% (48/48) | 0% (0/48) | 3.5 |

Spread across seeds (SD of the per-seed hard-violation rate): B0 0.07, B1 0.07, B2 0.11, R 0.00

Repair rounds among repaired cases (mean / median): B2 1.25 / 1, R 1.00 / 1

Initial hard violations by rule, over 48 initial plans:

| Rule | Violations | Plans affected |
|---|---|---|
| R6_FEATURE_COVERAGE | 92 | 35 |
| R5_TOOL_COMPATIBILITY | 65 | 20 |
| R3_MACHINE_CAPABILITY | 36 | 18 |
| R9_PRECEDENCE_ORDER | 12 | 6 |

Stop reasons:

| System | Stop reason | Count |
|---|---|---|
| B1 | max_repairs_reached | 29 |
| B1 | non_repairable_violation | 9 |
| B1 | valid | 10 |
| B2 | max_repairs_reached | 5 |
| B2 | non_repairable_violation | 9 |
| B2 | repair_output_invalid | 1 |
| B2 | repeated_plan | 15 |
| B2 | valid | 18 |
| R | non_repairable_violation | 9 |
| R | valid | 39 |

## How to read this

- **Hard-violation rate**: share of cases whose final plan breaks at least one hard rule. A planner failure counts as invalid.
- **Repair success**: share of initially invalid cases that end valid. This includes infeasible components, which cannot become valid by design.
- **Correct outcome**: a feasible component ends with a valid plan, or an infeasible component is routed to human review.
- **Sequence similarity** compares the plan with one generated reference plan. Other valid orders exist, so this is descriptive only.
- The validator can mark a plan valid that is wrong in ways it does not model (tool size, access, setups). See `docs/assumptions_and_limits.md`.
