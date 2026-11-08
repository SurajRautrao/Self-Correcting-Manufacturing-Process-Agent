# Optimization of accepted plans: `llm_test_full_gemma3-4b_v1.2`

Deterministic CP-SAT sequence optimizer (`scmpa.optimization`), applied after repair to every accepted plan. Objective: 10 × machine changes + 1 × tool changes between consecutive operations. Hard constraints: declared plan and component precedence, and eligible machine/tool pairs. Every result is re-checked by the validator. Total duration is a sum of fixed estimates and cannot change. B3 = B2 + optimizer; REF+opt = the benchmark's reference plans of this split (context, not a system).

Improvement is non-negative by construction, because the input plan is kept when nothing better exists. The questions are how large the improvement is and whether validity is preserved.

| Track | System | Mode | Plans | Improved | Valid after | Proven optimal | Machine changes | Tool changes | Cost | Median cost reduction | Ops moved | Ops reassigned |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| corruption | B3 | order | 24 | 15 | 24/24 | 24/24 | 2.67 → 1.58 | 4.75 → 3.38 | 31.4 → 19.2 | 26% | 2.8 | 0.0 |
| corruption | B3 | order+resources | 24 | 18 | 24/24 | 24/24 | 2.67 → 1.17 | 4.75 → 3.38 | 31.4 → 15.0 | 56% | 2.5 | 1.5 |
| corruption | R+opt | order | 39 | 33 | 39/39 | 39/39 | 3.00 → 1.46 | 5.23 → 3.46 | 35.2 → 18.1 | 48% | 4.0 | 0.0 |
| corruption | R+opt | order+resources | 39 | 36 | 39/39 | 39/39 | 3.00 → 1.08 | 5.23 → 3.46 | 35.2 → 14.2 | 60% | 3.6 | 1.7 |
| generation | B1+opt | order | 10 | 5 | 10/10 | 10/10 | 1.60 → 1.20 | 4.60 → 4.10 | 20.6 → 16.1 | 4% | 1.0 | 0.0 |
| generation | B1+opt | order+resources | 10 | 5 | 10/10 | 10/10 | 1.60 → 1.20 | 4.60 → 4.10 | 20.6 → 16.1 | 4% | 1.0 | 0.0 |
| generation | B3 | order | 18 | 10 | 18/18 | 18/18 | 2.06 → 1.17 | 4.28 → 3.83 | 24.8 → 15.5 | 8% | 1.9 | 0.0 |
| generation | B3 | order+resources | 18 | 13 | 18/18 | 18/18 | 2.06 → 1.00 | 4.28 → 3.50 | 24.8 → 13.5 | 42% | 1.7 | 0.6 |
| generation | R+opt | order | 39 | 28 | 39/39 | 39/39 | 2.38 → 1.46 | 5.23 → 4.08 | 29.1 → 18.7 | 41% | 3.6 | 0.0 |
| generation | R+opt | order+resources | 39 | 31 | 39/39 | 38/39 | 2.38 → 1.28 | 5.23 → 4.08 | 29.1 → 16.9 | 46% | 2.8 | 0.8 |
| reference | REF+opt | order | 13 | 11 | 13/13 | 13/13 | 3.00 → 1.46 | 5.23 → 3.46 | 35.2 → 18.1 | 47% | 4.1 | 0.0 |
| reference | REF+opt | order+resources | 13 | 12 | 13/13 | 13/13 | 3.00 → 1.08 | 5.23 → 3.46 | 35.2 → 14.2 | 64% | 3.7 | 1.6 |

## Weight sensitivity (order+resources, all accepted LLM-system plans)

| Machine : tool weight | Machine changes after | Tool changes after | Plans improved |
|---|---|---|---|
| (input plans) | 2.25 | 4.56 | – |
| 1 : 1 | 1.12 | 3.56 | 36/52 |
| 1 : 10 | 1.12 | 3.56 | 36/52 |
| 10 : 1 | 1.12 | 3.56 | 36/52 |
| 100 : 1 | 1.12 | 3.56 | 36/52 |

Plans invalid after optimization: **0** of 715 optimizer runs.
Solver statuses: {'FEASIBLE': 4, 'OPTIMAL': 711}; tie-break statuses: {'FEASIBLE': 38, 'OPTIMAL': 677}.
