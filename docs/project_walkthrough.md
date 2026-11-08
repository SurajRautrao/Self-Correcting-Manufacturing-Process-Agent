# Project walkthrough: every step, in order

This document explains how SCMPA was built and evaluated, step by step, from an empty folder to the `v1.0` release. For each step it says **what** was done, **why**, **what came out**, and **what was corrected later**. The other documents go deeper on one topic each; this one connects them. The results themselves are summarised in the [final report](report.md) and given in full in [`results.md`](results.md).

**Contents**
- [Glossary](#glossary)
- [Phase A: building the system (M0–M5)](#phase-a-building-the-system-m0m5)
- [Phase B: moving to the GPU cluster](#phase-b-moving-to-the-gpu-cluster)
- [Phase C: the main experiments (Runs 1–3)](#phase-c-the-main-experiments-runs-13)
- [Phase D: extensions (M6)](#phase-d-extensions-m6)
- [Phase E: follow-up experiments (Runs 4–6)](#phase-e-follow-up-experiments-runs-46)
- [Phase F: write-up and release](#phase-f-write-up-and-release)
- [Corrections made along the way](#corrections-made-along-the-way)
- [Where everything lives](#where-everything-lives)
- [Timeline of commits](#timeline-of-commits)

## Glossary

| Term | Meaning in this project |
|---|---|
| **Component** (part) | A simplified workpiece: a list of typed *features* (holes, pockets, slots, …) plus the *machines* and *tools* available for it, and its *precedence constraints*. Stored as JSON. |
| **Process plan** | An ordered list of *operations*. Each operation has a type (drilling, tapping, …), the features it works on, a machine, a tool and a duration estimate. The list order is the execution order. |
| **Catalogue** | One shared JSON file that says which operations suit which feature types and which tool types each operation may use. |
| **Precedence constraint** | "Operation A must come before operation B", for example drilling before tapping. Given per component, each with a written reason, never as a universal rule. |
| **Validator** | Twelve deterministic Python rules (R1–R12) that decide whether a plan is valid. It is the only authority on validity. |
| **Hard violation / warning** | A broken hard rule makes the plan invalid; a warning never does. |
| **Repairable** | A flag on each violation. `false` means no change with the available machines and tools can fix it, so the case goes to a person. |
| **Repair loop** | Generate → validate → diagnose → repair → revalidate, at most 3 repairs. |
| **Human review** | Where a case ends when it cannot or should not be repaired automatically. |
| **B0, B1, B2, B3, R** | The systems compared. B0: LLM plan accepted unchecked. B1: validated, invalid plans go to review. B2: LLM repair loop. B3: B2 plus the optimizer. R: deterministic rule-based repair, a reference point and not an AI result. |
| **Generation / corruption track** | Generation: the LLM plans from scratch. Corruption: correct reference plans get 2 injected faults, so repair is measured independently of planning, on identical inputs for every model. |
| **Seed** | The random seed for the LLM at temperature 0.7. Each part is planned with seeds 0, 1 and 2. |
| **Dev / test split** | Dev (8 parts) is for developing prompts and rules; test (16 parts) is only for reported results. |
| **Rule set version** | The validator's version (1.0 → 1.1 → 1.2). Every result records which version produced it. |
| **Replay** | Re-running an experiment from cached LLM plans instead of calling the model again (`initial_plans_from`). |
| **Paired comparison / McNemar test** | Two systems are compared case by case on the same inputs; the exact McNemar test asks whether the cases where only one succeeds are lopsided. |
| **Wilson interval** | The 95% confidence interval used for rates. |

## Phase A: building the system (M0–M5)

The brief (`self_correcting_manufacturing_process_agent_project_brief.pdf`, kept local) defines milestones M0–M6 and asks for nothing to be built ahead of a tested validator. The work followed that order. Throughout, Claude never committed or pushed; the author did both.

### Step 1. Read the brief and set up

- Read the 19-page brief in full and summarised its constraints: no G-code, no safety claims, no universal operation order, a validator that runs without an LLM, a provider-neutral LLM interface, and a mock planner.
- The machine's default Python was 3.10 (the project needs ≥ 3.11), so the virtual environment `.venv` was built with Python 3.12.
- The author's name, Suraj Balaji Rautrao, went into `LICENSE` and `pyproject.toml`. The brief stays local (git-ignored).

### Step 2. M0: repository, schemas, example data

- **What:** `pyproject.toml`, README, MIT licence, `.gitignore`; Pydantic schemas in `src/scmpa/schemas/` for the catalogue, components, plans and validation results; a loader in `src/scmpa/io.py`; three hand-written example parts with reference plans in `data/examples/`; `docs/assumptions_and_limits.md`.
- **Why:** every later step depends on strict, versioned data. Unknown fields are rejected, so typos fail loudly.
- **Design choices:**
  - A *component* file is fully checked on input (unknown types, duplicate IDs, dangling references, cyclic precedence are rejected with a list of every problem).
  - A *plan* is checked only for structure on input. An unknown tool ID or a negative duration still loads, so the validator can report it as a repairable violation instead of a parse error.
  - A part whose required feature cannot be made is *accepted* on input: it is a test case for the human-review path.
- Details: [`architecture.md`](architecture.md), README "Data model".

### Step 3. M1: the deterministic validator

- **What:** rules R1–R12 in `src/scmpa/validation/rules/` and `validate_plan()`. Each violation carries the rule ID, the operation or feature, evidence, a repair hint and the `repairable` flag.
- **Tests:** 119 tests pass offline. Every rule has passing cases (all reference plans) and targeted failing cases; an alternative valid order is accepted; results are identical across runs; one fault does not set off unrelated rules ("no cascades").
- **Checking that the tests can fail:** with R5 switched off, 3 tests failed; with R9 off, 4 failed.
- Details: [`constraint_catalogue.md`](constraint_catalogue.md).

### Step 4. M2: planners and the LLM interface

- **What:**
  - `src/scmpa/llm/`: a provider-neutral `LLMClient`, an `OllamaClient` (standard library only; it sends the plan's JSON schema so the model must answer in that shape) and a `ScriptedLLMClient` for tests. Ollama was chosen as the provider.
  - `src/scmpa/planning/`: `LLMPlanner`, versioned prompt files with content hashes, a normalizer that may only make documented, logged shape fixes (never IDs or values), and `MockPlanner`, which builds the obvious plan and can inject 10 kinds of known fault, each tied to the rule that should catch it.
- **A rule that keeps the baseline fair:** the planner retries only on schema or parse errors, and a retry never mentions validator findings. So B0 is a true "LLM only" baseline.
- **Result:** 166 tests. A live check with `qwen3.5:9b` produced valid plans for all three example parts on the first try (4–5 minutes per call on CPU).

### Step 5. M3: the bounded repair loop

- **What:** `workflow.solve()` (`src/scmpa/workflow/orchestration.py`), `LLMRepairAgent` and `RuleBasedRepairAgent` (`src/scmpa/repair/`), and `scripts/run_demo.py`.
- **Seven ways a run ends:** accepted; repair budget used up; a repeated plan (compared by a hash that ignores wording); a non-repairable violation (straight to review, no repairs spent); the repair agent asks for review; unusable planner output; unusable repair output. The loop always terminates.
- **The run record** keeps every candidate plan, its validation, each repair call with its claimed changes, the computed operation-level diff, raw model output, latency and tokens. This is what later made auditing possible (H4).
- **Result:** 272 tests. A live `qwen3.5:9b` repair fixed a plate plan with two injected faults (wrong tool, tapping before drilling) in one round, changing only the two affected operations.

### Step 6. M4: benchmark, experiment runner, metrics

- **What:**
  - **Benchmark v1** (`data/synthetic/benchmark_v1/`): 24 generated parts, 5 infeasible by design, split by part into dev (8) and test (16). A unit test regenerates it byte for byte.
  - **Runner** (`python -m scmpa.evaluation.run_experiments --config …`): plans once per (part, seed) and runs every system on that same plan; two tracks; every LLM call cached, so interrupted runs resume; it refuses to resume if the config, rule set or benchmark changed.
  - **Metrics and reports:** hard-violation rate with Wilson intervals, repair success, coverage, precedence accuracy, human-review recall and precision, correct outcome, invalid plans accepted, latency, tokens; `summary.md`, CSV/JSONL tables and a chart per experiment.
  - Docs: [`DATA_CARD.md`](DATA_CARD.md), [`evaluation.md`](evaluation.md).
- **Mock pilot:** a pipeline check only. Infeasible parts were caught with 100% recall and precision; R fixed 39 of 39 corrupted plans.
- **The first LLM pilot found a validator flaw (rule set v1.1).** `qwen3.5:9b` added realistic spot-drilling steps that the parts had no spot drill for. The validator called these non-repairable and sent makeable parts to review, although the steps were optional and could simply be removed. Fix: a violation is non-repairable only if the operation is actually needed; otherwise the hint is "remove it". Re-checked on the cached plans without new LLM calls.
- **Model switch:** `qwen3.5:9b` needed about 6.4 GB and 4–6 minutes per call on the laptop CPU, and the pilot was stopped by low memory. The author chose to switch the main model to `gemma3:4b` (half the memory, about twice as fast) and keep qwen as a later comparison.
- **gemma dev pilot (4 parts, 1 seed):** ran in 52 minutes. One case (syn_007) showed the model claiming changes it had not made, caught by repeated-plan detection: the first concrete evidence for H4.

### Step 7. M5: the demo app

- **What:** a Streamlit app (`src/scmpa/app/streamlit_app.py`) with three views: run the workflow on a part (mock or Ollama planner, optional injected faults, choice of repair agent), inspect any saved run record step by step, and browse experiment results.
- **Why:** to make the loop visible: each iteration's plan, the validator's findings with hints, and the computed diff of each repair.

## Phase B: moving to the GPU cluster

### Step 8. Slurm job for the university cluster

- **Why:** the full test run would take about 11 hours on the laptop CPU and was at risk of being stopped for memory.
- **What:** `scripts/hpc/slurm_experiment.sh`, modelled on a sample script the author provided. It loads a Python module (`PY_MODULE=python/3.11.11-wun5tnb`), builds a venv, starts Ollama from an Apptainer image on a per-job port, pulls every model named in the config, checks the model is on the GPU, runs the experiment and prints the summary. It is resumable: resubmit the same command after a time-out.
- **Fixes during setup:** the batch shell had no `module` command until its init script was sourced; `logs/` had to exist before submission and was added to `.gitignore`; the partition was changed to `gpu-stud`.
- **Getting results back:** the author pushed from the cluster over SSH. Results folders are git-ignored by default, so each was added with `git add -f reports/experiments/<id>`.

## Phase C: the main experiments (Runs 1–3)

### Step 9. Run 1: gemma3:4b on the test split (rule set v1.1)

- 16 test parts × 3 seeds = 48 generation cases, plus 39 corruption cases.
- **Results:** the LLM alone produced invalid plans in 79% of cases; the validator took accepted invalid plans to 0; LLM repair helped a little (5 wins, 0 losses against B1, p = 0.06, all from 2 parts); 4 repairs ended *worse* than they started.
- **Two validator flaws found on the test split:**
  1. **Spot drilling counted as making a hole:** 8 plans with an only-spot-drilled hole passed (false passes), and 9 feasible cases were sent to review without a repair attempt.
  2. **Removability ignored still-required steps:** a required tapping step on an undrilled hole could count as "removable".
- **How this was handled honestly:** Run 1 was kept and reported as is, the flaws documented, the fix developed and checked on dev, and the test split re-scored under a new experiment ID, labelled post hoc. Both runs are reported side by side.

### Step 10. Rule set v1.2, best-candidate selection and replay

- **Rule set v1.2:** the catalogue gained `preparatory_operation_types: ["spot_drilling"]` (a preparatory operation contributes to a hole but never completes it), and removability compares each feature's missing operation types before and after removal. The rule-based repair agent was updated to match, which also fixed a crash it hit on syn_011.
- **Best candidate:** when a run ends in human review, the reviewer now gets the candidate with the fewest hard violations, not the last one.
- **Replay infrastructure:** `initial_plans_from` replays an earlier experiment's cached plans, after checking that the benchmark, planner and faults match. The stale-cache guard also checks the catalogue's hash.
- **Re-scores without any LLM:** `rescore_test_gemma3-4b_v1.2` raised R's correct outcome from 81% to 100% and its human-review precision from 50% to 100%; `rescore_dev_gemma3-4b_v1.2` changed nothing on dev (no regressions).
- Two chart and statistics fixes: the Wilson interval is clamped to contain the rate, and error bars can no longer be negative.

### Step 11. Run 2: gemma3:4b under v1.2, with LLM repair

- Replays Run 1's plans, so only the B2 repair calls are new.
- **Results:** B2 correct outcome 56%; 8 wins and 0 losses against B1 (p = 0.008, but from only 3 parts); no case ended worse than it started.
- **Run-to-run noise:** on the corruption track, inputs and prompts were identical to Run 1, yet 11 of 39 outcomes flipped. So gemma's repair rate is reported as a range (62–74%), and single-run differences of about ±5 cases mean nothing.

### Step 12. Run 3: qwen3.5:9b as the comparison model

- Same split, seeds, prompts, rule set and loop; qwen generates its own plans.
- **Results:** LLM-alone invalid rate 54%; B2 matched the rule-based ceiling on all 48 generation cases (17 of 17 invalid feasible plans repaired); 97% of injected faults repaired. On the paired corruption inputs qwen beat gemma clearly (p ≤ 0.012).

## Phase D: extensions (M6)

### Step 13. The sequence optimizer (B3, hypothesis H3)

- **What:** `src/scmpa/optimization/` uses OR-Tools CP-SAT to reorder a *valid* plan, and optionally reassign each operation to another eligible machine/tool pair, to minimise `10 × machine changes + 1 × tool changes`, with all precedence as hard constraints. It refuses invalid plans (optimization is not repair) and its output is revalidated.
- **Making it fast and repeatable:** the first version was slow and sometimes returned unproven results. Fixes: solve in two phases (cost first, then the plan closest to the input at that cost); simpler change constraints; lower bounds from the smallest set of machines or tools that covers all operations; deterministic time limits, one worker and a fixed seed.
- **Evaluation:** `python -m scmpa.evaluation.optimize_results <experiment>` optimizes every accepted plan in both modes and at four weight settings. On Runs 2–3 the change cost roughly halved and no plan broke a constraint. The weights made no difference on benchmark v1, and the reason was analysed: with shared tools and type-based eligibility, grouping by machine also groups tools. A hand-built case confirmed the optimizer does follow the weights when a real conflict exists (checked by brute force).
- The demo app gained an "Optimize sequence" button.

### Step 14. Worked examples, false-failure audit and the audit-trail measure

- [`examples.md`](examples.md) is generated by `scripts/make_examples.py` from stored run records: a spot-drill-only hole repaired under v1.2, a repair claiming changes it did not make, an infeasible part routed to review, a false failure, and the optimizer on a valid plan.
- **False-failure audit:** every violation in the 96 initial plans of Runs 2–3 was classified. Most were genuine; 5 violations in 4 plans rejected common shop practice (for example, a spot drill used to chamfer). 10 of qwen's invalid plans failed only on an optional spot-drilling step.
- **H4 measured:** gemma's change notes claimed changes it had not made in 24 of 121 repair calls (20%), qwen in 1 of 66. The computed diff exposed every case.

### Step 15. Prompt v2 and benchmark v2 (prepared, run later)

- **Prompt v2** (`planner_system_v2.md`): explicit rules on preparatory operations, tool look-up, leaving out optional steps that cannot be done, and a self-check. Selected by `"prompt_version": "v2"`. Planned for the dev split first, per protocol.
- **Benchmark v2** (`data/synthetic/benchmark_v2/`, generator profile `v2`, seed 2027): specialised machines with partial overlap, 6–10 features, denser precedence. Designed to provoke wrong-machine errors and real machine-versus-tool trade-offs. Benchmark v1 still regenerates byte for byte.

### Step 16. FabriCAD: investigation and importer

- The brief names FabriCAD as the first external data source. Its licence (CC BY-NC 4.0) is incompatible with redistribution in an MIT repository, so nothing from it is committed; imported data goes to the git-ignored `data/external/`.
- The 30 public preview samples were inspected field by field. FabriCAD is itself synthetic, describes features in German free text, and has no precedence graph or capability lists.
- **Importer** (`python -m scmpa.importers.fabricad`): maps holes, threaded and fitted holes, pockets and slots, and lists everything it omits (steps, grooves, turning, welding, grinding). Taps and reamers, which FabriCAD never lists, are added and labelled as assumptions. Result: 30/30 samples imported, 166 features mapped, 117 omitted. Details: [`fabricad.md`](fabricad.md).

### Step 17. FreeCAD: feature extraction from STEP geometry

- After the author installed FreeCAD 1.1, `src/scmpa/cad/` was built. FreeCAD ships its own Python, so the geometric code runs as a subprocess and returns JSON; `to_component` turns that into an SCMPA component marked as CAD-derived.
- **Rules:** holes are concave full-circle cylinders (coaxial ones grouped into counterbores, through or blind found by probing); pockets, slots and steps are axis-aligned floors with a clear approach direction, classified by how many sides are open.
- **Test part:** `scripts/freecad/make_cad_fixture.py` models a block with 7 known features; the extractor finds all 7 with correct dimensions, and the resulting component runs through the workflow.
- **Iterations needed:** walls were first detected as floors (fixed by the clear-line-of-sight check); steps were found twice (merged); the first test part had overlapping features (redesigned); after inspecting FabriCAD, floors open on one side were reclassified from step to pocket.
- **Cross-check on FabriCAD** (`scripts/freecad/evaluate_on_fabricad.py`): holes 96% recall and 92% precision; pockets, slots and steps lower. Reported as in-sample, because one rule was adjusted on this data. Details: [`cad_extraction.md`](cad_extraction.md).

## Phase E: follow-up experiments (Runs 4–6)

### Step 18. Runs 4–5 on the cluster

Five jobs were submitted together:

| Job | Question | Outcome |
|---|---|---|
| `dev_gemma3-4b_prompt-v1` and `-v2` | Does prompt v2 help, on dev? | No measurable effect (15 vs 14 invalid of 24, p = 1.0). **Decision:** the planned test-split run was not made; prompt v1 stays. |
| `llm_test_full_qwen3.5-9b_rep2` | How noisy is qwen's repair? | 3 of 87 outcomes flipped (gemma: 11 of 39). qwen's results reproduce. |
| `llm_test_full_gemma3-4b_bench-v2`, `llm_test_full_qwen3.5-9b_bench-v2` | How do the models cope with harder parts? | Both planners got worse (qwen's violations per plan nearly tripled); qwen's repair still fixed 19 of 22 broken plans and 95% of injected faults, gemma's fell to 51%. |

- The optimizer was then run locally on the benchmark v2 results. Machine-versus-tool trade-offs appeared for the first time in model output, but only when each operation's machine and tool stay fixed.

### Step 19. Run 6: gemma3:27b, to separate model size from model family

- **Why:** gemma3:4b and qwen3.5:9b differ in both size and family. A bigger gemma changes only the size.
- **How:** a new config on benchmark v2; a 1-part smoke run first, to check that the GPU had enough memory and that `ollama ps` reported the model fully on the GPU; then the full run.
- **Results:** the best planner of the three (38% invalid alone; every feature covered), repair on par with qwen (3 discordant cases, p = 1.0), and 47 of 48 correct outcomes with the loop. Conclusion: gemma3:4b's weakness was mainly size.
- **A correction to the trade-off counts:** some apparent trade-offs came from solves that hit their time limit rather than from real conflicts. The optimizer report now counts only trade-offs proven optimal at every weight, and the earlier numbers were corrected (for example qwen 15 → 10).

## Phase F: write-up and release

### Step 20. Final report

- [`report.md`](report.md) brings everything into one document: question and hypotheses, system, setup, results (benchmark v1, validator flaws, noise, benchmark v2 and model size, optimizer, auditability, CAD, the negative prompt result), discussion per hypothesis, limitations, future work, and an experiment index.

### Step 21. Reproducibility check and CI

- **What:** `scripts/check_reproducible.py` rebuilds every committed result without an LLM or GPU: it regenerates both benchmarks, rebuilds every results table and `examples.md`, replays B0, B1 and R from the cached plans, and re-validates every stored B2 final plan. `.github/workflows/ci.yml` runs it and the tests on Python 3.11 and 3.12.
- **What it found:**
  1. **Float rounding:** `summary.json` totals differed between Python 3.11 (cluster) and 3.12 (laptop), because 3.12 changed how `sum()` adds floats. Fixed with an exact, rounded sum.
  2. **A real optimizer defect:** when several plans tie on both objectives, which one was returned depended on Python's per-process hash randomisation (the precedence pairs were added in set order). Fixed by sorting them, with a regression test that fails without the fix. All optimizer results were regenerated; no proven cost and no headline number changed.
  3. **Cross-platform ties:** CI on Linux returned a different, equally good plan in the `examples.md` optimizer case. The check now requires only the same cost, solver status and validity for that case, and prints a diff on any mismatch. The docs now say the optimizer is repeatable on one platform and OR-Tools version.
- **Demo:** the app gained a "From CAD (STEP)" source, so the whole story runs in one place: geometry → features → plan → violations → repair → optimizer.
- **Release:** both CI jobs passed and the author tagged `v1.0`. Final state: 486 tests pass, and the reproducibility check passes.

## Corrections made along the way

Each of these was found by the project's own checks, documented, and fixed without overwriting the original record.

| Found in | Problem | Fix |
|---|---|---|
| First LLM pilot | Optional, unperformable steps made cases non-repairable | Rule set v1.1: "remove it" when the operation is not needed |
| Run 1 (test split) | Spot drilling counted as making a hole; removability ignored required steps | Rule set v1.2; Run 1 kept, re-score and Run 2 reported beside it |
| Run 1 | Repairs could end worse than they started | Best-candidate final plan |
| Re-score | Rule-based repair crashed on syn_011 | Removability fix, and R skips unproducible types |
| Charts | Negative error bars | Wilson interval clamped |
| Run 2 | Single-run differences looked like effects | Noise measured; gemma's B2 reported as a range |
| Validator audit | 5 realistic steps rejected | Documented; rule set v1.3 proposed |
| Run 6 | Time-limited solves counted as trade-offs | Only proven trade-offs counted |
| Reproducibility check | Float sums differ across Python versions | Exact, rounded sums |
| Reproducibility check | Optimizer ties depended on the hash seed | Sorted constraints, regression test, results regenerated |
| CI on Linux | Equally good plans differ across platforms | Check compares cost and validity there; claim narrowed |

## Where everything lives

| You want to … | Look at |
|---|---|
| Understand the results | [`report.md`](report.md), then [`results.md`](results.md) |
| See real traces | [`examples.md`](examples.md) |
| Know what the rules check | [`constraint_catalogue.md`](constraint_catalogue.md) |
| Know what is *not* modelled | [`assumptions_and_limits.md`](assumptions_and_limits.md) |
| Understand the code structure | [`architecture.md`](architecture.md) |
| Know how experiments work | [`evaluation.md`](evaluation.md), configs in `configs/experiments/` |
| Know where the data comes from | [`DATA_CARD.md`](DATA_CARD.md), [`fabricad.md`](fabricad.md) |
| Use the CAD extractor | [`cad_extraction.md`](cad_extraction.md) |
| Re-check every result | `python scripts/check_reproducible.py` |
| Run on the cluster | `scripts/hpc/slurm_experiment.sh` (options in its header) |
| Try it interactively | `streamlit run src/scmpa/app/streamlit_app.py` |

## Timeline of commits

| Date | Commit | Steps |
|---|---|---|
| 2026-11-07 | `e60365f` | 1–7: M0–M5 |
| 2026-11-07 | `494ad00`, `0f2e1e8` | 8: Slurm script |
| 2026-11-07 | `42cc5c0` | 9: Run 1 results |
| 2026-11-07 | `d7a4d01` | 10: rule set v1.2 |
| 2026-11-08 | `e85464b`, `0599f58` | 11: Run 2 |
| 2026-11-08 | `34168fa`, `455237e`, `c58c92b` | 12: Run 3 |
| 2026-11-08 | `31c0568` | 13: optimizer |
| 2026-11-08 | `611eca2` | 14–16: examples, audit, prompt v2, benchmark v2, FabriCAD |
| 2026-11-08 | `7342324` | 17: FreeCAD extraction |
| 2026-11-08 | `31a254c`, `50d43e6` | 18: Runs 4–5 |
| 2026-11-08 | `cd9aacc`, `a6803dc`, `2b36b5a` | 19: Run 6 |
| 2026-11-08 | `0cb8996` | 20: final report |
| 2026-11-08 | `81a316e`, `a2119b0` | 21: reproducibility, CI; tag `v1.0` |
