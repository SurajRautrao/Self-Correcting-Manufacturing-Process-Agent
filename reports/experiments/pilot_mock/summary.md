# Experiment `pilot_mock`

Pipeline check without an LLM: mock planner (generation track) and injected faults (corruption track); B2 omitted, R is the rule-based reference.

- Benchmark: `scmpa_synthetic_v1` (manifest sha256 `2212ae165f6c2daa`), split **test**, 16 components, seeds [0, 1, 2]
- Planner: `{"provider": "mock"}`; LLM repair (B2): `null`; max repairs 3
- Rule set 1.1, catalogue `scmpa_demo_catalogue_v1`, scmpa 0.1.0, Python 3.12.4
- **All data is synthetic.** These results describe software behaviour on a toy benchmark, not industrial performance.
- R is a deterministic rule-based repair agent included as a reference point. It is not an AI result.

## Track: corruption

Initial plans are reference plans with injected faults, so this track measures repair independently of planner quality. B0 is not applicable.

| System | Cases | Planner failures | Hard-violation rate [95% CI] | Repair success | Coverage | Precedence acc. | Seq. similarity | Human-review recall | Human-review precision | Correct outcome | Invalid plan accepted | Mean latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 + validator | 39 | 0% (0/39) | 100% (39/39) [91%–100%] | 0% (0/39) | 0.93 | 0.77 | 0.95 | – | 0% (0/39) | 0% (0/39) | 0% (0/39) | 0.0 |
| R rule-based repair (non-AI reference) | 39 | 0% (0/39) | 0% (0/39) [0%–9%] | 100% (39/39) | 1.00 | 1.00 | 0.96 | – | – | 100% (39/39) | 0% (0/39) | 0.0 |

Spread across seeds (SD of the per-seed hard-violation rate): B1 0.00, R 0.00

Repair rounds among repaired cases (mean / median): R 1.00 / 1

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
| R | valid | 39 |

## Track: generation

| System | Cases | Planner failures | Hard-violation rate [95% CI] | Repair success | Coverage | Precedence acc. | Seq. similarity | Human-review recall | Human-review precision | Correct outcome | Invalid plan accepted | Mean latency (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 LLM-only (unchecked) | 48 | 0% (0/48) | 19% (9/48) [10%–32%] | 0% (0/9) | 0.94 | 1.00 | 1.00 | 0% (0/9) | – | 81% (39/48) | 19% (9/48) | 0.0 |
| B1 + validator | 48 | 0% (0/48) | 19% (9/48) [10%–32%] | 0% (0/9) | 0.94 | 1.00 | 1.00 | 100% (9/9) | 100% (9/9) | 100% (48/48) | 0% (0/48) | 0.0 |
| R rule-based repair (non-AI reference) | 48 | 0% (0/48) | 19% (9/48) [10%–32%] | 0% (0/9) | 0.94 | 1.00 | 1.00 | 100% (9/9) | 100% (9/9) | 100% (48/48) | 0% (0/48) | 0.0 |

Spread across seeds (SD of the per-seed hard-violation rate): B0 0.00, B1 0.00, R 0.00

Initial hard violations by rule, over 48 initial plans:

| Rule | Violations | Plans affected |
|---|---|---|
| R6_FEATURE_COVERAGE | 18 | 9 |

Stop reasons:

| System | Stop reason | Count |
|---|---|---|
| B1 | non_repairable_violation | 9 |
| B1 | valid | 39 |
| R | non_repairable_violation | 9 |
| R | valid | 39 |

## How to read this

- **Hard-violation rate**: share of cases whose final plan breaks at least one hard rule. A planner failure counts as invalid.
- **Repair success**: share of initially invalid cases that end valid. This includes infeasible components, which cannot become valid by design.
- **Correct outcome**: a feasible component ends with a valid plan, or an infeasible component is routed to human review.
- **Sequence similarity** compares the plan with one generated reference plan. Other valid orders exist, so this is descriptive only.
- The validator can mark a plan valid that is wrong in ways it does not model (tool size, access, setups). See `docs/assumptions_and_limits.md`.
