# Optimization of accepted plans: `llm_test_full_qwen3.5-9b_bench-v2`

Deterministic CP-SAT sequence optimizer (`scmpa.optimization`), applied after repair to every accepted plan. Objective: 10 × machine changes + 1 × tool changes between consecutive operations. Hard constraints: declared plan and component precedence, and eligible machine/tool pairs. Every result is re-checked by the validator. Total duration is a sum of fixed estimates and cannot change. B3 = B2 + optimizer; REF+opt = the benchmark's reference plans of this split (context, not a system).

Improvement is non-negative by construction, because the input plan is kept when nothing better exists. The questions are how large the improvement is and whether validity is preserved.

| Track | System | Mode | Plans | Improved | Valid after | Proven optimal | Machine changes | Tool changes | Cost | Median cost reduction | Ops moved | Ops reassigned |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| corruption | B3 | order | 37 | 37 | 37/37 | 37/37 | 6.35 → 2.38 | 8.81 → 4.14 | 72.3 → 27.9 | 59% | 7.8 | 0.0 |
| corruption | B3 | order+resources | 37 | 37 | 37/37 | 37/37 | 6.35 → 1.59 | 8.81 → 4.11 | 72.3 → 20.1 | 70% | 7.1 | 3.2 |
| corruption | R+opt | order | 39 | 39 | 39/39 | 39/39 | 6.49 → 2.31 | 9.05 → 4.15 | 73.9 → 27.2 | 59% | 7.8 | 0.0 |
| corruption | R+opt | order+resources | 39 | 39 | 39/39 | 39/39 | 6.49 → 1.62 | 9.05 → 4.15 | 73.9 → 20.3 | 69% | 7.3 | 3.2 |
| generation | B1+opt | order | 17 | 17 | 17/17 | 17/17 | 4.18 → 2.29 | 8.94 → 5.59 | 50.7 → 28.5 | 40% | 7.4 | 0.0 |
| generation | B1+opt | order+resources | 17 | 17 | 17/17 | 17/17 | 4.18 → 1.65 | 8.94 → 4.65 | 50.7 → 21.1 | 59% | 7.2 | 3.5 |
| generation | B3 | order | 36 | 35 | 36/36 | 32/36 | 5.08 → 2.42 | 9.64 → 6.03 | 60.5 → 30.2 | 47% | 8.1 | 0.0 |
| generation | B3 | order+resources | 36 | 36 | 36/36 | 34/36 | 5.08 → 1.75 | 9.64 → 4.61 | 60.5 → 22.1 | 64% | 8.1 | 3.9 |
| generation | R+opt | order | 39 | 38 | 39/39 | 37/39 | 5.41 → 2.41 | 9.90 → 5.85 | 64.0 → 29.9 | 49% | 8.4 | 0.0 |
| generation | R+opt | order+resources | 39 | 39 | 39/39 | 37/39 | 5.41 → 1.74 | 9.90 → 4.56 | 64.0 → 22.0 | 64% | 8.1 | 3.9 |
| reference | REF+opt | order | 13 | 13 | 13/13 | 13/13 | 6.46 → 2.31 | 9.00 → 4.15 | 73.6 → 27.2 | 59% | 7.8 | 0.0 |
| reference | REF+opt | order+resources | 13 | 13 | 13/13 | 13/13 | 6.46 → 1.62 | 9.00 → 4.15 | 73.6 → 20.3 | 69% | 7.3 | 3.2 |

## Weight sensitivity (all accepted LLM-system plans: B1+opt and B3)

A plan has a *trade-off* if its optimal (machine changes, tool changes) differs between weight settings.

| Mode | Machine : tool weight | Machine changes after | Tool changes after | Plans improved |
|---|---|---|---|---|
| order | (input plans) | 5.43 | 9.17 | – |
| order | 1 : 1 | 2.47 | 5.10 | 89/90 |
| order | 1 : 10 | 2.59 | 4.99 | 89/90 |
| order | 10 : 1 | 2.38 | 5.17 | 89/90 |
| order | 100 : 1 | 2.39 | 5.18 | 89/90 |
| order | plans with a trade-off | 15/90 | | |
| order+resources | (input plans) | 5.43 | 9.17 | – |
| order+resources | 1 : 1 | 1.68 | 4.41 | 90/90 |
| order+resources | 1 : 10 | 1.67 | 4.41 | 90/90 |
| order+resources | 10 : 1 | 1.67 | 4.41 | 90/90 |
| order+resources | 100 : 1 | 1.67 | 4.41 | 90/90 |
| order+resources | plans with a trade-off | 1/90 | | |

Plans invalid after optimization: **0** of 1448 optimizer runs.
Solver statuses: {'FEASIBLE': 49, 'OPTIMAL': 1399}; tie-break statuses: {'FEASIBLE': 952, 'OPTIMAL': 496}.
