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

## Run 3: `llm_test_full_qwen3.5-9b` (rule set v1.2, comparison model)

This uses the same test split, seeds, prompts, rule set and loop as Run 2. The planner and repair model is Ollama `qwen3.5:9b` (thinking off), and qwen generates its own initial plans. It ran on the `gpu-stud` partition.

| | gemma3:4b (Run 2, v1.2) | qwen3.5:9b (Run 3) |
|---|---|---|
| Generation: B0 hard-violation rate | 79% [66–88%] | **54%** [40–67%] |
| Generation: B0 coverage | 0.67 | 0.96 |
| Generation: B2 correct outcome | 56% (27/48) | **100%** (48/48) |
| Generation: B2 feasible plans repaired | 8 / 29 | **17 / 17** |
| Corruption: B2 repair success | 62–74% (two runs) | **97%** (38/39) |
| Repair calls needing a schema retry | 16 / 124 | 0 / 66 |
| Median planner call | 3.4 s (Run 1 node) | 17.6 s |
| Median repair call | 21.1 s | 18.4 s |

- **The planner is better from the start.** qwen's initial plans are invalid half as often as gemma's, and they rarely leave a feature uncovered: only 6 of 48 plans have R6 violations. Its errors are mostly wrong tool (R5) or wrong machine (R3), which are the easiest to repair. 6 components are valid under every seed (gemma: 1).
- **qwen's repair loop matches the rule-based ceiling.** B2 and R agree on every one of the 48 generation cases. All 17 invalid feasible plans were repaired, mostly in 1 round (mean 1.12), and all 9 infeasible cases went to human review. Against B1, that is 17 wins and 0 losses over 8 components (p < 0.001).
- **Corruption is a paired comparison across models.** The inputs are identical to the gemma runs, which I verified for all 39 cases. qwen repaired 10–15 cases that gemma did not, and gemma repaired 1 that qwen did not (p = 0.012 against Run 1, p < 0.001 against Run 2, spread over 7–10 components). The only qwen failure (syn_023 s1, precedence cycle plus unknown tool) stopped on a repeated plan, which is ordering again.
- **The edits are minimal.** qwen's repairs change a median of 2 operations and keep 79% of operations unchanged, the same as gemma. It needs fewer rounds and never produced unusable output.
- **Caveats:**
  - The generation track is *not* paired across models: each model repairs its own plans, and qwen's are easier to repair. Corruption is the fair model comparison.
  - This is a single run. Run 2 showed that B2 outcomes can flip in about a quarter of cases between runs. qwen's per-seed SD is 0.00–0.04 and its results sit at the ceiling, so the noise is probably smaller here, but that is not yet measured.
  - Latency was measured on a different partition from the gemma runs, so the latencies are not comparable.

## M6: sequence optimization (B3, H3)

The CP-SAT optimizer (`scmpa.optimization`) was applied offline to every accepted plan of Runs 2 and 3 (`python -m scmpa.evaluation.optimize_results`). The objective is 10 × machine changes + 1 × tool changes between consecutive operations. The hard constraints are the declared precedence and eligible resources. Full tables are in each experiment's `optimization.md`.

Mode `order+resources` (reorder and reassign eligible machine/tool pairs), default weights:

| Set | Plans | Improved | Valid after | Machine changes | Tool changes | Median cost reduction |
|---|---|---|---|---|---|---|
| qwen B3, generation | 39 | 35 | 39/39 | 2.31 → 1.00 | 5.97 → 3.59 | 48% |
| qwen B3, corruption | 38 | 36 | 38/38 | 3.11 → 1.08 | 5.32 → 3.47 | 64% |
| gemma B3, generation | 18 | 13 | 18/18 | 2.06 → 1.00 | 4.28 → 3.50 | 42% |
| gemma B3, corruption | 24 | 18 | 24/24 | 2.67 → 1.17 | 4.75 → 3.38 | 56% |
| reference plans (test split) | 13 | 12 | 13/13 | 3.00 → 1.08 | 5.23 → 3.46 | 64% |

- **Hard constraints held everywhere.** All 2,664 optimizer runs across both experiments, both modes and every weight setting ended with a valid plan, re-checked by the validator. 2,657 of 2,664 were proven optimal. The other 7 hit the deterministic time limit with a feasible, improved plan.
- **The gain is large:** at the median, the change cost is cut by about half. Machine changes fall to about 1 per plan, which is close to the floor, because most parts need two machines. Reordering alone gets most of the gain (median 26–48%); reassignment adds the rest.
- **LLM plans are not sequenced for changes.** qwen's initially valid plans start at a cost of 30.0 and end at 14.0. gemma's few initially valid plans were already well grouped: median 4%, and only 5 of 10 improved.
- **The weights do not matter on this benchmark, in either mode.** For all 151 accepted LLM plans (99 qwen, 52 gemma), the optimal machine and tool counts are identical at 1:1, 1:10, 10:1 and 100:1, both with reassignment and in reorder-only mode. Two reasons:
  - Eligibility depends only on operation type, and tools are shared across machines. So with reassignment, operations of one type can almost always share a machine, and grouping by machine also groups by tool. In a check on 60 generated parts, a trade-off appeared in 1 with reassignment but in 14 when random valid machine assignments were kept.
  - Both LLMs assign each operation type to one machine consistently, so even their fixed assignments leave no conflict.
  - The optimizer does honour the weights when a conflict exists: a hand-built case gives (1 machine, 3 tool changes) at 100:1 and (2, 2) at 1:100, confirmed by brute force (`test_weights_decide_a_genuine_tradeoff_in_order_only_mode`). Benchmark v2's specialised machines are designed to create such conflicts in LLM plans.
- **The result is deterministic.** Each solve uses a deterministic time limit, one worker and a fixed seed. Repeated runs give identical plans, and the reference-plan rows match exactly across both experiment folders.
- **Limits:** this measures change counts, not time. Durations are fixed, setups within a machine are not modelled, and a reassigned tool may differ in unmodelled size (see `assumptions_and_limits.md`).

## Validator audit: false failures and audit trail (spec 8.3)

**False failures** (valid alternatives the rules reject) were checked by classifying every violation in the 96 initial generated plans of Runs 2 and 3, by rule and by (operation, tool or feature) pair.

| Class | Cases | Verdict |
|---|---|---|
| Wrong or missing tool or machine (tap work with a drill, operations on machines without the capability), mostly on the infeasible parts | most R3/R5 | genuine |
| Hole that gets spot drilling (and possibly tapping or reaming) but no drilling | 69 holes (gemma), 9 (qwen) | genuine: the hole is never drilled |
| Plan's own precedence edges contradict its sequence, or a component constraint is broken | 13 | genuine |
| Face milling a pocket or a hole | 4 | genuine |
| **Optional spot-drilling step without a spot drill or capable machine** | 10 of qwen's 26 invalid plans fail *only* for this | **correct under the rules, but minor.** The step cannot be done as written. The repair removes it, and the rest of the plan was fine. |
| **Spot drill used to chamfer** (gemma syn_009 ×2), **chamfering a threaded-hole entry** (qwen syn_011), **spot drilling or pre-drilling a pocket entry** (qwen syn_018 ×2) | 5 violations, 4 plans | **false failures.** All are common shop practice. The catalogue's operation-to-feature map is narrower than reality. Only 1 plan (qwen syn_018 s0) was rejected for this reason alone. |

- **Consequence for H1:** the strict rule set inflates qwen's raw invalid rate. Excluding the 10 plans that fail only on an optional spot step, qwen's LLM-only invalid rate is 33% (16/48) rather than 54%. gemma has no such plans.
- **The cost of the false failures was small:** a needless edit (the repair removed the realistic step, see `examples.md` case 4), never a wrong routing to human review.
- **Fixing it** would mean a catalogue notion of auxiliary operations (chamfering any hole edge, entry holes for pockets). That is a rule-set change for a v1.3, to be decided on the dev split, not here.
- The documented simplification "face milling only with face mills" caused **no** rejections in either run.

**Audit trail (H4).** A repair agent's change notes were compared with the computed diff of the plan it returned. gemma claimed changes but returned an unchanged plan in **24 of 121** repair calls (20%); qwen did so in **1 of 66**. All 25 cases were caught by repeated-plan detection and are visible in the diff. Without the structured comparison, a reader of the model's text would have accepted these claims. See `examples.md` case 2.

### Hypotheses after Runs 1–3 and M6

- **H1 (constraint feedback lowers violations):** supported. Invalid plans accepted fall to 0% with either model (qwen's raw 54% includes 10 plans that fail only on an optional spot step; see the audit above). The hard-violation rate falls from 79% to 62–69% with gemma and from 54% to 19% with qwen. The 19% left are exactly the infeasible cases.
- **H2 (the bounded loop repairs a measurable share):** supported, and strongly model-dependent. On injected faults, gemma repairs 62–74% and qwen 97%. On generated plans, gemma repairs 8 of 29 and qwen 17 of 17. Neither model ever made a correct validator-only outcome wrong, and with best-candidate selection no run ends worse than it started.
- **H3 (sequencing optimizer):** supported for the declared metrics. The optimizer roughly halves the machine- and tool-change cost of accepted plans and never breaks a hard constraint (0 of 2,664 runs across both experiments, all modes and all weights). The improvement is non-negative by construction. The measured effect is its size, and it is about counts, not time. The weighting is untested on benchmark v1, because neither model's plans contain a conflict; it is verified on a constructed case and was then measured on benchmark v2 (Run 5).
- **H4 (auditability):** supported with a concrete measure. The model's own change notes were false (claimed changes, none made) in 20% of gemma's repair calls and 2% of qwen's. The computed diff and repeated-plan detection exposed every case. Every repair also has a stop reason, and both models' diffs show small, targeted edits (median 1–2 operations). Representative traces are in `examples.md`.

## Run 4: qwen run-to-run noise (`llm_test_full_qwen3.5-9b_rep2`)

This run replays Run 3's initial plans: the initial violation counts match in all 87 cases. Only the B2 repair calls are new.

| B2 + LLM repair (qwen) | Run 3 | Run 4 | Flips |
|---|---|---|---|
| Generation: correct outcome | 100% (48/48) | 98% (47/48) | 1 (syn_003 s2: max repairs reached in Run 4) |
| Corruption: repair success | 97% (38/39) | 97% (38/39) | 2, one each way (syn_023 s1 failed only in Run 3, syn_013 s1 only in Run 4) |

- **qwen's repair loop is stable.** 3 of 87 outcomes flipped between runs, against 11 of 39 for gemma on the corruption track alone (Runs 1–2). Together the two runs give a pooled corruption repair rate of 97% (76/78).
- So the noise found in Run 2 belongs to the weaker model, not to the loop. A model that repairs at the ceiling has little room to flip.

## Prompt v2 on the dev split (`dev_gemma3-4b_prompt-v1` vs `-v2`)

Planner prompt v2 (preparatory operations, tool look-up, self-check) was compared with v1 on the dev split, gemma3:4b, 8 parts × 3 seeds, B0/B1/R. Both runs use the same seeds and settings.

| gemma3:4b, dev | Prompt v1 | Prompt v2 |
|---|---|---|
| B0 hard-violation rate | 62% (15/24) | 58% (14/24) |
| Feasible parts with a valid initial plan | 9 / 18 | 10 / 18 |
| Mean initial hard violations | 2.29 | 1.75 |
| Mean coverage | 0.82 | 0.86 |
| Paired (v1 only / v2 only valid) | 2 / 3, p = 1.0 | |

- **No measurable effect.** The 5 discordant cases sit in two parts that moved in opposite directions: syn_007 became valid under all three seeds with v2, and syn_010 lost 2 of 3. Fewer violations per plan (R5 27 → 19, R6 20 → 17) do not turn into more valid plans.
- **Decision: the test-split run (`llm_test_full_gemma3-4b_prompt-v2`) is not run.** On this evidence it would spend test data on an effect the dev split cannot distinguish from noise. Prompt v1 stays the default. gemma's coverage gap is a model limit that the prompt does not fix; the validator and repair loop are what handle it.

## Run 5: benchmark v2 (`llm_test_full_*_bench-v2`)

Benchmark v2 has specialised machines with partial overlap, 6–10 features and denser precedence (test split, 16 parts × 3 seeds, prompt v1). Only the benchmark changes versus Runs 2 and 3. The corruption inputs are identical for both models (paired).

| | gemma v1 | gemma **v2** | qwen v1 | qwen **v2** |
|---|---|---|---|---|
| Generation: B0 hard-violation rate | 79% | 83% (40/48) | 54% | 65% (31/48) |
| Generation: mean initial hard violations (feasible parts) | 3.77 | 4.44 | 1.00 | 2.79 |
| Generation: B0 coverage | 0.67 | 0.75 | 0.96 | 0.97 |
| Generation: B2 correct outcome | 56% | 58% (28/48) | 100% | 94% (45/48) |
| Generation: B2 feasible plans repaired | 8 / 29 | 11 / 31 | 17 / 17 | 19 / 22 |
| Corruption: B2 repair success | 62–74% | 51% (20/39) | 97% | 95% (37/39) |
| Generation: R correct outcome | 100% | 100% | 100% | 100% |

- **The harder benchmark hurts the planners, especially qwen.** qwen's initial plans now carry almost 3× as many violations (1.0 → 2.8 per feasible plan). They are almost all wrong-machine (R3: 42 violations in 19 plans) and wrong-tool (R5) errors, which is what the specialised machines were built to provoke. Its coverage stays at 0.97.
- **The repair loop still closes most of the gap with qwen.** It repairs 19 of 22 invalid feasible plans and 37 of 39 corrupted ones. The 3 generation failures and both corruption failures involve precedence (R9) again.
- **gemma's repair is weaker on larger parts.** Its corruption repair success falls to 51%, below its 62–74% range on benchmark v1. 15 of its 19 failures stop on a repeated plan, and coverage (R6) is still the most common remaining violation.
- **The validator and loop remain safe.** No invalid plan is accepted by any checked system, and the rule-based reference R reaches 100% correct outcomes on both tracks.
- **Paired model comparisons:**
  - Corruption: qwen repaired 18 cases that gemma did not, and gemma 1 that qwen did not (p < 0.001, 10 components).
  - Generation: qwen's B2 was correct in 17 cases where gemma's was not, and never the reverse (p < 0.001).
  - Within each model, B2 beats B1 with no losses: gemma 11 / 0 (7 components, p = 0.001), qwen 19 / 0 (12 components, p < 0.001).

### Optimizer on benchmark v2 (B3)

Same procedure as M6 (`optimize_results` on both experiments). Full tables are in each folder's `optimization.md`.

| Set (`order+resources`, default weights) | Plans | Valid after | Machine changes | Tool changes | Median cost reduction |
|---|---|---|---|---|---|
| qwen B3, generation | 36 | 36/36 | 5.08 → 1.75 | 9.64 → 4.61 | 64% |
| qwen B3, corruption | 37 | 37/37 | 6.35 → 1.59 | 8.81 → 4.11 | 70% |
| gemma B3, generation | 19 | 19/19 | 4.21 → 1.74 | 6.74 → 5.05 | 47% |
| gemma B3, corruption | 20 | 20/20 | 6.35 → 1.60 | 9.10 → 4.35 | 70% |
| reference plans (test split) | 13 | 13/13 | 6.46 → 1.62 | 9.00 → 4.15 | 69% |

- **Hard constraints held again:** 0 invalid plans in 2,552 optimizer runs. 2,478 were proven optimal; the other 74 stopped at the deterministic time limit with a feasible, improved plan. The parts are larger (6–10 features), which explains the extra time limits and the ~40 min run.
- **The gain is larger than on benchmark v1:** median 47–70%, against about 42–64%. Larger plans with more machines leave more changes to remove.
- **Weight trade-offs now appear, but only with fixed assignments.** In reorder-only mode, 17 of 137 accepted LLM plans (qwen 15/90, gemma 2/47) have a different optimum under different weights; on benchmark v1 it was 0 of 151. The weights move the result in the expected direction: for qwen, 1:10 gives 2.59 machine and 4.99 tool changes, and 10:1 gives 2.38 and 5.17. With reassignment, only 1 of 137 plans has a trade-off, because the optimizer can still regroup operations by machine.
- So the weighting matters when the shop fixes the machine for each operation, and hardly at all when the optimizer may choose. That confirms the earlier explanation on real model output rather than only on a constructed case.

### Hypotheses after Runs 4–5

- **H1, H2:** still supported on the harder benchmark. No invalid plan is accepted, and repair beats validation-only for both models with no losses. The size of the repair effect depends strongly on the model (qwen 19/22 vs gemma 11/31 repaired generated plans).
- **H3:** supported, and the weighting is now tested on LLM plans: trade-offs exist in 12% of plans when assignments are fixed and the weights steer the result as intended.
- **Noise:** qwen's B2 results reproduce (3/87 flips); gemma's do not (11/39).

## Pending

- Optional: rule set v1.3 with auxiliary operations (chamfering any hole edge, entry holes for pockets), decided on the dev split; see the validator audit.
