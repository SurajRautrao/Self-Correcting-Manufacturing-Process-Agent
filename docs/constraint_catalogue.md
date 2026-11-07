# Constraint catalogue (rule set v1.1)

The validator lives in `src/scmpa/validation/`. It is pure Python: no LLM, no network and no randomness. A plan is **valid iff no rule reports a `hard` violation**. Warnings never affect validity. Each violation records `rule_id`, `severity`, `operation_id` and/or `feature_id`, `evidence`, a `repair_hint` and a `repairable` flag.

| Rule | Checks | Severity | Not repairable when |
|---|---|---|---|
| `R1_OPERATION_TYPE` | Operation type is in the catalogue | hard | — |
| `R2_MACHINE_EXISTS` | `machine_id` is an available machine | hard | — |
| `R3_MACHINE_CAPABILITY` | Machine lists the operation type as a capability | hard | no available machine has the capability **and** the operation is needed for coverage |
| `R4_TOOL_EXISTS` | `tool_id` is an available tool | hard | — |
| `R5_TOOL_COMPATIBILITY` | Tool type is allowed for the operation (catalogue `tool_compatibility`) | hard | no available tool has a compatible type **and** the operation is needed for coverage |
| `R6_FEATURE_COVERAGE` | (a) Operation type suits each feature it targets. (b) Every required feature is covered | hard | no machine/tool pair can perform a missing operation |
| `R7_FEATURE_REFERENCE` | Every target feature exists in the component | hard | — |
| `R8_PRECEDENCE_VALIDITY` | Precedence edges reference existing operations; the edge graph is acyclic | hard | — |
| `R9_PRECEDENCE_ORDER` | The sequence respects plan edges **and** component `precedence_constraints` | hard | — |
| `R10_DUPLICATE_OPERATION` | Same operation type repeated on the same feature | **warning** (configurable) | — |
| `R11_DURATION` | Duration is positive and finite (always hard) and ≤ `max_duration_min` | hard / bound: **warning** (configurable) | — |
| `R12_COMPLETENESS` | `component_id` matches; there is at least one operation; each operation has targets; the explanation is non-empty | hard | — |

## Semantics worth knowing

- **Sequence:** the order of `plan.operations` is the execution order.
- **No cascades:** a rule skips inputs that a more basic rule has already rejected. R3 and R5 are not evaluated when R1, R2 or R4 has already failed for that operation. R6(a) skips unknown types and features. R9 skips edges that R8 rejected. This keeps the violation list focused for the repair agent.
- **Coverage (R6):**
  - An operation *contributes* to a feature if it targets that feature and its type is in the catalogue's suitable list for the feature type. Machine and tool errors do not cancel a contribution, because R2–R5 report those separately.
  - A feature with `required_operation_types` needs **all** of them. Any other required feature needs **any one** suitable operation.
  - Optional features (`required: false`) may be omitted.
- **Component precedence (R9):** a constraint `before → after` is checked for every pair of matching operations. If one operation matches both sides (for example, a single operation faces F1 *and* machines F2 when F1 must precede F2), that is also a violation.
- **Cycles (R8):** one cycle is reported per validation. Revalidation after repair reports the next cycle, if any.
- **Removable operations (v1.1):** sometimes no available resource can perform an operation, but removing it would not uncover any required feature. A spot-drilling step with no spot drill on hand is the typical case. R3/R5 then report `repairable: true` with `operation_removable: true` and the hint "remove it". In v1.0 such plans went straight to human review. This was found in the first LLM pilot, where the model added realistic but unavailable spot-drilling steps.
- **`repairable: false`** means no change using the available resources can fix the violation. The repair loop (M3) will route such cases to human review instead of spending its iteration budget on them.

## Configuration (`ValidationConfig`)

| Field | Default | Meaning |
|---|---|---|
| `duplicate_severity` | `"warning"` | R10 severity |
| `allowed_duplicate_operation_types` | `[]` | Operation types exempt from R10 (e.g. roughing and finishing passes) |
| `max_duration_min` | `240.0` | R11 upper demo bound per operation, in minutes |
| `duration_bound_severity` | `"warning"` | R11 severity when the bound is exceeded |

## Known gaps (deliberate in v1.0)

- The validator cannot detect a plan that passes every rule but is wrong in reality ("false passes"). Examples: wrong tool diameter, or an inaccessible feature. These aspects are not modelled; see `assumptions_and_limits.md`.
- Precedence knowledge is only as good as each component's declared constraints. A missing constraint means the validator accepts any order for those features.
