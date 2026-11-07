# Data

| Path | Contents | Provenance |
|---|---|---|
| `catalogue/catalogue_v1.json` | Operation, tool and feature vocabulary and compatibility maps | Authored for SCMPA; a pedagogical rule set |
| `examples/components/` | 3 toy component specifications | `synthetic` (hand-written) |
| `examples/reference_plans/` | One illustrative valid plan per component | `synthetic`, not expert-reviewed |
| `synthetic/benchmark_v1/` | 24 generated components, reference plans, `manifest.json` | `synthetic` (seeded generator) |

Every component carries a `provenance` block (`source_type`: `real` / `derived` / `synthetic`). It is required by the schema, so a record cannot be mislabelled by omission.

`synthetic/benchmark_v1/` holds the generated benchmark: 24 components, a manifest with split and expected outcomes, and reference plans. It was produced by `scripts/make_synthetic_data.py` (seed 2026). See [`docs/DATA_CARD.md`](../docs/DATA_CARD.md).
