# Results

All data is synthetic (see [`DATA_CARD.md`](DATA_CARD.md)). These numbers describe software behaviour on a toy benchmark, not industrial performance. R is a deterministic rule-based reference, **not** an AI result.

## Run 1: `llm_test_full_gemma3-4b` (rule set v1.1)

Test split: 16 components × 3 seeds (temperature 0.7) = 48 generation cases, of which 9 (3 components) are infeasible by design. There are 39 corruption cases with 2 injected faults each. Planner and repair model: Ollama `gemma3:4b`, at most 3 repairs. There were no planner failures. The full tables are in `reports/experiments/llm_test_full_gemma3-4b/summary.md`.

### Generation track

| System | Hard-violation rate [95% CI] | Correct outcome | Invalid plan accepted | Mean latency |
|---|---|---|---|---|
| B0 LLM only | 79% [66–88%] | 21% | 79% (38/48) | 3.5 s |
| B1 + validator | 79% [66–88%] | 40% | 0% | 3.5 s |
| B2 + LLM repair | 69% [55–80%] | 50% | 0% | 7.7 s |
| R rule-based | 38% [25–52%] | 81% as reported; 67% after removing 7 false passes (see below) | 0% | 3.5 s |

- **The LLM alone is unreliable:** 10/48 plans were valid. The common errors were missing operations (R6), wrong tool (R5) and wrong machine (R3).
- **Detection is the main safety gain.** The validator alone (B1) takes invalid plans accepted from 38 to 0, and it routed all 9 infeasible cases to human review.
- **LLM repair is a small gain.** Paired against B1, B2 was right where B1 was wrong in 5 cases and never the reverse (exact McNemar p = 0.06). All 5 come from 2 components (syn_009 ×3, syn_022 ×2).
- **Most repair attempts failed:** B2 actually attempted 20 cases and made 5 valid. 12 ended with fewer violations, and 4 ended with *more* than they started with. In v1.1 the loop returned the last candidate, not the best.
- **Cost:** B2 roughly doubles latency and uses about 2.6× the tokens.

### Corruption track

| System | Repair success | Remaining violations |
|---|---|---|
| B2 + LLM repair | 74% (29/39) | 14 × R9 order, 5 × R6 coverage, 1 × R8 cycle |
| R rule-based | 100% (39/39) | none (it is written for exactly these fault kinds: a ceiling, not a fair opponent) |

The LLM fixes unknown tools (5/5) and unknown operation types (7/7) reliably. It struggles with missing operations (3/6), unknown features (4/8) and precedence cycles (4/7). Most failures are ordering: when it adds an operation, it often places it before the operations it depends on.

### Seed variability

Temperature 0.7 still gives strongly correlated outcomes: most components fail in the same way under all three seeds. So the effective sample size is closer to 16 components than to 48 cases.

### Validator flaws found in this run

1. **Spot drilling counted as making a hole.** The catalogue lists spot drilling as suitable for holes, and v1.1 let any suitable operation cover a feature. As a result:
   - **False passes:** 8 accepted plans had a hole that was only spot drilled (7 R generation cases on syn_001, syn_013 and syn_018, and 1 B2 corruption case).
   - **False escalations:** in 9 feasible cases (syn_003, syn_006, syn_019, all seeds), gemma used spot drilling as the only operation on a hole, and those parts have no spot-drilling tool or machine. Removing the step would "uncover" the hole, so R3/R5 were marked non-repairable and the case went to human review without a repair attempt. B2 and R were both affected.
2. **Removability ignored still-required steps.** This was found while re-scoring. v1.1 called an operation removable if removing it uncovered no *currently covered* feature. The tapping step of a threaded hole that was already missing its drilling therefore counted as "removable", although tapping is still required there.

Both flaws were found on the **test** split. Run 1 therefore stays the primary record, and the fixes are reported next to it, never in place of it.

## Rule set v1.2 and loop change

- Catalogue `preparatory_operation_types: ["spot_drilling"]`: preparatory operations contribute to a feature but never complete it on their own (R6).
- R3/R5 removability compares each target feature's *missing operation types* before and after removal.
- When a run ends in human review, the reviewer now gets the candidate with the fewest hard violations (`RunRecord.final_iteration`), not the last one.
- The LLM prompts are unchanged. The catalogue view in the prompts lists explicit fields and does not include the new one, so B2 sees the change only through the validator's findings.

## Re-score: `rescore_test_gemma3-4b_v1.2` (no LLM)

This run uses the same 48 + 39 initial plans as Run 1, replayed with `initial_plans_from`, so it has no new planner calls. Only B0, B1 and R are included.

| Generation | v1.1 | v1.2 |
|---|---|---|
| B0/B1 hard-violation rate | 79% | 79% (none of the 10 valid plans had a spot-only hole) |
| B0/B1 mean coverage | 0.81 | 0.67 (spot-only holes are no longer counted) |
| R correct outcome | 81% (incl. 7 false passes) | **100%** (39/39 feasible valid, 9/9 infeasible routed) |
| R human-review precision | 50% (9/18) | **100%** (9/9) |

Corruption is unchanged: R 39/39, B1 0/39. On the dev split (`rescore_dev_gemma3-4b_v1.2`), all numbers match the dev pilot, so the fix caused no regressions there. No accepted v1.2 plan has a required hole that only gets spot drilling.

## Pending

- `llm_test_full_gemma3-4b_v1.2`: B2 under v1.2 on the replayed plans. It needs a GPU (Slurm).
- `llm_test_full_qwen3.5-9b`: the comparison model, run under v1.2.
- H3 (sequencing optimizer, M6) has not been tested.
