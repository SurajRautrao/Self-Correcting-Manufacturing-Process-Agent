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

## Run 2: `llm_test_full_gemma3-4b_v1.2` (rule set v1.2, with B2)

This run replays Run 1's initial plans, so B0, B1 and R match the re-score above exactly. Only the B2 repair calls are new.

| B2 + LLM repair | Run 1 (v1.1) | Run 2 (v1.2) |
|---|---|---|
| Generation: correct outcome | 50% (24/48) | 56% (27/48) |
| Generation: valid after repair (feasible) | 5 | 8 |
| Generation: final plan worse than the initial one | 4 | 0 |
| Generation: paired vs B1 (wins / losses) | 5 / 0, p = 0.06 | 8 / 0, p = 0.008 |
| Corruption: repair success | 74% (29/39) | 62% (24/39) |
| Median repair-call latency | 3.8 s | 21.1 s (slower hardware, see below) |

- **The v1.2 fix is a real effect.** In Run 1, syn_006 and syn_019 (6 cases) went to human review without a repair attempt. In Run 2, B2 repaired all 6 and they ended valid. syn_003 (3 cases) is now attempted but still fails (repeated plan).
- **Best-candidate selection works:** no B2 case ends worse than it started.
- **B2 beats B1 consistently, but on few parts.** Case-level significance (p = 0.008) overstates the evidence. All 8 wins come from 3 components (syn_006, syn_009, syn_019), so the effective support is 3 parts.
- **Run-to-run noise is large.** The corruption track's inputs and validator findings are identical in both runs (39/39), and so are the prompts. Yet 11 of 39 B2 outcomes flipped: 8 valid only in Run 1 and 3 valid only in Run 2 (McNemar p = 0.23, not significant). The drop from 74% to 62% is therefore noise, not an effect of v1.2. The 3 generation cases lost in Run 2 (syn_009 s2, syn_022 s1/s2) are noise too. They include 1 new `repair_output_invalid`: gemma produced a duplicate operation ID twice.
  - **Consequence:** one B2 run cannot resolve differences of about ±5 cases. Report B2 as the range over runs: corruption 62–74%, pooled 68% (53/78).
  - Seeds at temperature 0.7 do not capture this variation. The seed varies the plan, while this noise comes from re-running the same repair prompt, here on different hardware.
- **Latency is not comparable between the runs.** Output speed fell from about 200 to about 36 tokens/s with a similar number of tokens, which points to a slower or shared GPU, or a model partly offloaded to the CPU. Check the `ollama ps` line in the job log. Validity results do not depend on speed.
- **Coverage is gemma's main weakness under v1.2.** R6 now hits 35 of 48 initial plans (92 violations). gemma often gives a hole only a spot drill.

### Hypotheses after Runs 1–2

- **H1 (constraint feedback lowers violations):** supported for detection: invalid plans accepted fall from 79% to 0%. For the violation rate it is moderate: 79% falls to 62–69% for B2, while R, the ceiling of what the feedback allows, reaches 19%.
- **H2 (the bounded loop repairs a measurable share):** supported. B2 repairs 62–74% of injected faults and 8 of 29 invalid feasible generated plans (v1.2). It never ends worse than it started, and it never made a correct B1 outcome wrong.
- **H3 (sequencing optimizer):** not tested (M6).
- **H4 (auditability):** qualitative. Every repair has a computed diff and a stop reason. Repeated plans (15 generation cases in Run 2) and invalid repair outputs are visible as such.

## Pending

- `llm_test_full_qwen3.5-9b`: the comparison model, run under v1.2. It also gives a third estimate of B2 noise if it is run twice.
- H3 (sequencing optimizer, M6) has not been tested.
