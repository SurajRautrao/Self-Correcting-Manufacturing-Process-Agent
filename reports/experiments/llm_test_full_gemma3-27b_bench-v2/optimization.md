# Optimization of accepted plans: `llm_test_full_gemma3-27b_bench-v2`

Deterministic CP-SAT sequence optimizer (`scmpa.optimization`), applied after repair to every accepted plan. Objective: 10 × machine changes + 1 × tool changes between consecutive operations. Hard constraints: declared plan and component precedence, and eligible machine/tool pairs. Every result is re-checked by the validator. Total duration is a sum of fixed estimates and cannot change. B3 = B2 + optimizer; REF+opt = the benchmark's reference plans of this split (context, not a system).

Improvement is non-negative by construction, because the input plan is kept when nothing better exists. The questions are how large the improvement is and whether validity is preserved.

| Track | System | Mode | Plans | Improved | Valid after | Proven optimal | Machine changes | Tool changes | Cost | Median cost reduction | Ops moved | Ops reassigned |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| corruption | B3 | order | 36 | 36 | 36/36 | 35/36 | 6.31 → 2.36 | 8.89 → 4.22 | 71.9 → 27.8 | 59% | 7.8 | 0.0 |
| corruption | B3 | order+resources | 36 | 36 | 36/36 | 35/36 | 6.31 → 1.61 | 8.89 → 4.19 | 71.9 → 20.3 | 69% | 7.3 | 3.1 |
| corruption | R+opt | order | 39 | 39 | 39/39 | 39/39 | 6.49 → 2.31 | 9.05 → 4.15 | 73.9 → 27.2 | 59% | 7.8 | 0.0 |
| corruption | R+opt | order+resources | 39 | 39 | 39/39 | 39/39 | 6.49 → 1.62 | 9.05 → 4.15 | 73.9 → 20.3 | 69% | 7.6 | 3.2 |
| generation | B1+opt | order | 30 | 30 | 30/30 | 28/30 | 5.90 → 2.53 | 10.27 → 6.03 | 69.3 → 31.4 | 47% | 9.0 | 0.0 |
| generation | B1+opt | order+resources | 30 | 30 | 30/30 | 27/30 | 5.90 → 1.67 | 10.27 → 4.67 | 69.3 → 21.3 | 65% | 8.0 | 3.7 |
| generation | B3 | order | 38 | 38 | 38/38 | 36/38 | 6.37 → 2.63 | 10.18 → 5.95 | 73.9 → 32.3 | 49% | 9.3 | 0.0 |
| generation | B3 | order+resources | 38 | 38 | 38/38 | 35/38 | 6.37 → 1.74 | 10.18 → 4.55 | 73.9 → 21.9 | 67% | 8.1 | 4.0 |
| generation | R+opt | order | 39 | 39 | 39/39 | 37/39 | 6.33 → 2.64 | 10.18 → 5.97 | 73.5 → 32.4 | 48% | 9.3 | 0.0 |
| generation | R+opt | order+resources | 39 | 39 | 39/39 | 36/39 | 6.33 → 1.74 | 10.18 → 4.54 | 73.5 → 22.0 | 66% | 8.0 | 4.0 |
| reference | REF+opt | order | 13 | 13 | 13/13 | 13/13 | 6.46 → 2.31 | 9.00 → 4.15 | 73.6 → 27.2 | 59% | 7.7 | 0.0 |
| reference | REF+opt | order+resources | 13 | 13 | 13/13 | 13/13 | 6.46 → 1.62 | 9.00 → 4.15 | 73.6 → 20.3 | 69% | 7.4 | 3.2 |

## Weight sensitivity (all accepted LLM-system plans: B1+opt and B3)

A plan has a *trade-off* if its optimal (machine changes, tool changes) differs between weight settings. Only those solved to proven optimality at every weight are genuine; the rest may differ because a solve hit its time limit. B1+opt and B3 share the plans that were valid without repair, so such a plan is counted once per system.

| Mode | Machine : tool weight | Machine changes after | Tool changes after | Plans improved |
|---|---|---|---|---|
| order | (input plans) | 6.21 | 9.76 | – |
| order | 1 : 1 | 2.53 | 5.36 | 104/104 |
| order | 1 : 10 | 2.67 | 5.22 | 104/104 |
| order | 10 : 1 | 2.51 | 5.38 | 104/104 |
| order | 100 : 1 | 2.51 | 5.38 | 104/104 |
| order | plans with a trade-off | 16/104 | | |
| order | … of which proven optimal at every weight | 11/104 | | |
| order+resources | (input plans) | 6.21 | 9.76 | – |
| order+resources | 1 : 1 | 1.73 | 4.44 | 104/104 |
| order+resources | 1 : 10 | 1.73 | 4.44 | 104/104 |
| order+resources | 10 : 1 | 1.67 | 4.46 | 104/104 |
| order+resources | 100 : 1 | 1.67 | 4.62 | 104/104 |
| order+resources | plans with a trade-off | 10/104 | | |
| order+resources | … of which proven optimal at every weight | 2/104 | | |

Plans invalid after optimization: **0** of 1560 optimizer runs.
Solver statuses: {'FEASIBLE': 71, 'OPTIMAL': 1489}; tie-break statuses: {'FEASIBLE': 1028, 'OPTIMAL': 532}.
