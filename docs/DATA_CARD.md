# Data card

## Summary

| Dataset | Location | Source type | Size | License |
|---|---|---|---|---|
| Operation/tool catalogue v1 | `data/catalogue/catalogue_v1.json` | authored for SCMPA | 9 operation types, 7 tool types, 8 feature types | MIT (this repo) |
| Hand-written examples | `data/examples/` | synthetic | 3 components + 3 reference plans | MIT (this repo) |
| Synthetic benchmark v1 | `data/synthetic/benchmark_v1/` | synthetic | 24 components (19 feasible, 5 infeasible), 19 reference plans | MIT (this repo) |
| Synthetic benchmark v2 | `data/synthetic/benchmark_v2/` | synthetic | 24 components (19 feasible, 5 infeasible), 19 reference plans | MIT (this repo) |
| FabriCAD-format test fixture | `tests/fixtures/fabricad/` | synthetic, hand-written in FabriCAD's file format (no FabriCAD data) | 2 samples | MIT (this repo) |
| FabriCAD (external, **not included**) | imported locally into `data/external/fabricad/` (git-ignored) | derived (FabriCAD is itself synthetic) | 30 public preview samples inspected | CC BY-NC 4.0, citation required |

**No real or derived industrial data is included.** FabriCAD data can be imported locally with `python -m scmpa.importers.fabricad`. Its records are marked `derived` and carry the CC BY-NC 4.0 license. Because that license is incompatible with redistribution in this MIT repository, the output goes to a git-ignored folder. See [`fabricad.md`](fabricad.md).

## Synthetic benchmark v1

- **Generator:** `src/scmpa/evaluation/synthetic.py` v1.0. Command: `python scripts/make_synthetic_data.py --seed 2026 --n 24 --infeasible-fraction 0.2`. A unit test checks that the committed files match this command exactly.
- **Per component:**
  - **Features:** a datum face F1 plus 3–7 features (pockets, slots, through, blind, threaded and reamed holes, outer contours, chamfers), with random dimensions in mm. About half the chamfers are optional.
  - **Machines and tools:**
    - 1–3 machines are drawn from 4 templates, then topped up until every needed operation has a capable machine.
    - Each needed operation type gets one compatible tool. There may also be a second drill and 0–2 distractor tools.
  - **Precedence:** generated *demo assumptions*, each with a rationale:
    - F1 before a feature, with probability 0.7;
    - drill before tap or ream (always);
    - pocket before a blind hole in its floor, with probability 0.5;
    - contour before an edge chamfer.
- **Labels:**
  - `expected_outcome` is `feasible` or `needs_human_review`.
  - 20% of components are made infeasible: one required operation (never face milling) loses either every capable machine or every compatible tool. The reason is recorded in `infeasible_reason`.
- **Reference plans:** built by the deterministic mock planner and checked by the validator. Each is **one valid plan among possibly many** and has **not** been reviewed by an expert.
- **Split:** by `component_id`, stratified by expected outcome. Dev has 8 components (2 infeasible) and test has 16 (3 infeasible). The test split is not to be used for tuning prompts or rules.
- **Fields used:** all fields of the `Component` schema; see the README data-model table.
- **Missing values:** dimensions are optional per feature type. Durations in reference plans are placeholders.

## Intended use

- Testing and comparing constraint checking, plan repair and human-review routing **under the declared simplified rule set**.
- Reproducible software evaluation and portfolio demonstration.

## Not intended for

- Estimating real-world planning quality, machining time, cost or manufacturability.
- Training or benchmarking models for industrial use.

## Known limitations and biases

- **The generator's structure is regular,** so an LLM may find these parts easier or harder than real parts in ways that are not measured.
- **Feasibility is defined only by the rule set.** Tool size, access, setups, fixturing, tolerances and material are not modelled. A "valid" plan can still be physically wrong.
- **Precedence assumptions are generated, not engineered.** Real ordering depends on datums, geometry and setups.
- **Infeasibility comes from a single mechanism** (a missing capability or tool). Other real causes of infeasibility are not represented.
- **The reference plans come from one deterministic heuristic,** so sequence-similarity scores are biased toward its style.

## Synthetic benchmark v2

- **Generator:** the same module with `profile="v2"` (generator version 2.0). Command: `python scripts/make_synthetic_data.py --profile v2 --seed 2027 --out data/synthetic/benchmark_v2`. A unit test checks that the committed files match this command exactly. Component IDs are `synv2_001` … `synv2_024`.
- **Differences from v1:**
  - **More features:** 6–10 per part plus the datum face, so 7–11 in all and 8–16 operations per reference plan.
  - **Specialised machines** with partly overlapping capabilities. There are four templates: a milling centre without drilling, a drill-tap unit, a horizontal boring mill (drilling, reaming, pocket milling, face milling) and a slotting/chamfering cell. Each part has 2–4 machines.
  - **More distractor tools:** 1–3 per part.
  - **Denser precedence:** datum first with probability 0.9, and pocket floor before hole with probability 0.8. That gives about 10 constraints per part, against about 5 in v1.
- **Purpose:** harder parts to separate the models, and parts where machine changes and tool changes can conflict for the optimizer.
  - A check found that the two objectives conflict mainly when the plan's machine assignments are kept: 14 of 60 generated parts with random valid assignments.
  - When the optimizer may also reassign operations to machines, conflicts are rare (1 of 60), because SCMPA ties eligibility to operation type and lets every tool work on every machine.
- **Labels, split and reference plans:** the same policy as v1. Dev has 8 components (2 infeasible) and test has 16 (3 infeasible).

