# Optimization of accepted plans: `llm_test_full_qwen3.5-9b`

Deterministic CP-SAT sequence optimizer (`scmpa.optimization`), applied after repair to every accepted plan. Objective: 10 × machine changes + 1 × tool changes between consecutive operations. Hard constraints: declared plan and component precedence, and eligible machine/tool pairs. Every result is re-checked by the validator. Total duration is a sum of fixed estimates and cannot change. B3 = B2 + optimizer; REF+opt = the benchmark's reference plans of this split (context, not a system).

Improvement is non-negative by construction, because the input plan is kept when nothing better exists. The questions are how large the improvement is and whether validity is preserved.

| Track | System | Mode | Plans | Improved | Valid after | Proven optimal | Machine changes | Tool changes | Cost | Median cost reduction | Ops moved | Ops reassigned |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| corruption | B3 | order | 38 | 33 | 38/38 | 38/38 | 3.11 → 1.47 | 5.32 → 3.50 | 36.4 → 18.2 | 47% | 4.2 | 0.0 |
| corruption | B3 | order+resources | 38 | 36 | 38/38 | 38/38 | 3.11 → 1.08 | 5.32 → 3.47 | 36.4 → 14.3 | 64% | 3.7 | 1.6 |
| corruption | R+opt | order | 39 | 33 | 39/39 | 39/39 | 3.00 → 1.46 | 5.23 → 3.46 | 35.2 → 18.1 | 48% | 4.0 | 0.0 |
| corruption | R+opt | order+resources | 39 | 36 | 39/39 | 39/39 | 3.00 → 1.08 | 5.23 → 3.46 | 35.2 → 14.2 | 60% | 3.6 | 1.7 |
| generation | B1+opt | order | 22 | 17 | 22/22 | 22/22 | 2.41 → 1.36 | 5.95 → 4.09 | 30.0 → 17.7 | 44% | 4.0 | 0.0 |
| generation | B1+opt | order+resources | 22 | 20 | 22/22 | 22/22 | 2.41 → 1.05 | 5.95 → 3.55 | 30.0 → 14.0 | 48% | 3.3 | 2.0 |
| generation | B3 | order | 39 | 31 | 39/39 | 39/39 | 2.31 → 1.26 | 5.97 → 4.00 | 29.1 → 16.6 | 44% | 4.4 | 0.0 |
| generation | B3 | order+resources | 39 | 35 | 39/39 | 39/39 | 2.31 → 1.00 | 5.97 → 3.59 | 29.1 → 13.6 | 48% | 3.8 | 1.5 |
| generation | R+opt | order | 39 | 31 | 39/39 | 39/39 | 2.31 → 1.23 | 5.92 → 4.03 | 29.0 → 16.3 | 44% | 4.4 | 0.0 |
| generation | R+opt | order+resources | 39 | 35 | 39/39 | 39/39 | 2.31 → 1.00 | 5.92 → 3.59 | 29.0 → 13.6 | 48% | 3.8 | 1.5 |
| reference | REF+opt | order | 13 | 11 | 13/13 | 13/13 | 3.00 → 1.46 | 5.23 → 3.46 | 35.2 → 18.1 | 47% | 4.1 | 0.0 |
| reference | REF+opt | order+resources | 13 | 12 | 13/13 | 13/13 | 3.00 → 1.08 | 5.23 → 3.46 | 35.2 → 14.2 | 64% | 3.7 | 1.6 |

## Weight sensitivity (all accepted LLM-system plans: B1+opt and B3)

A plan has a *trade-off* if its optimal (machine changes, tool changes) differs between weight settings.

| Mode | Machine : tool weight | Machine changes after | Tool changes after | Plans improved |
|---|---|---|---|---|
| order | (input plans) | 2.64 | 5.72 | – |
| order | 1 : 1 | 1.36 | 3.83 | 81/99 |
| order | 1 : 10 | 1.36 | 3.83 | 81/99 |
| order | 10 : 1 | 1.36 | 3.83 | 81/99 |
| order | 100 : 1 | 1.36 | 3.83 | 81/99 |
| order | plans with a trade-off | 0/99 | | |
| order+resources | (input plans) | 2.64 | 5.72 | – |
| order+resources | 1 : 1 | 1.04 | 3.54 | 91/99 |
| order+resources | 1 : 10 | 1.04 | 3.54 | 91/99 |
| order+resources | 10 : 1 | 1.04 | 3.54 | 91/99 |
| order+resources | 100 : 1 | 1.04 | 3.54 | 91/99 |
| order+resources | plans with a trade-off | 0/99 | | |

Plans invalid after optimization: **0** of 1520 optimizer runs.
Solver statuses: {'FEASIBLE': 2, 'OPTIMAL': 1518}; tie-break statuses: {'FEASIBLE': 192, 'OPTIMAL': 1328}.
