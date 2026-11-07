# Data card

## Summary

| Dataset | Location | Source type | Size | License |
|---|---|---|---|---|
| Operation/tool catalogue v1 | `data/catalogue/catalogue_v1.json` | authored for SCMPA | 9 operation types, 7 tool types, 8 feature types | MIT (this repo) |
| Hand-written examples | `data/examples/` | synthetic | 3 components + 3 reference plans | MIT (this repo) |
| Synthetic benchmark v1 | `data/synthetic/benchmark_v1/` | synthetic | 24 components (19 feasible, 5 infeasible), 19 reference plans | MIT (this repo) |

**No real or derived industrial data is included.** FabriCAD (spec section 7.1) has not been used yet. If an importer is added later, its records will be marked `derived` and its license recorded here before any data is redistributed.

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
