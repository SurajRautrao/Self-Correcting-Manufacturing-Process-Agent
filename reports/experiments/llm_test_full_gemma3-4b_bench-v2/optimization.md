# Optimization of accepted plans: `llm_test_full_gemma3-4b_bench-v2`

Deterministic CP-SAT sequence optimizer (`scmpa.optimization`), applied after repair to every accepted plan. Objective: 10 × machine changes + 1 × tool changes between consecutive operations. Hard constraints: declared plan and component precedence, and eligible machine/tool pairs. Every result is re-checked by the validator. Total duration is a sum of fixed estimates and cannot change. B3 = B2 + optimizer; REF+opt = the benchmark's reference plans of this split (context, not a system).

Improvement is non-negative by construction, because the input plan is kept when nothing better exists. The questions are how large the improvement is and whether validity is preserved.

| Track | System | Mode | Plans | Improved | Valid after | Proven optimal | Machine changes | Tool changes | Cost | Median cost reduction | Ops moved | Ops reassigned |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| corruption | B3 | order | 20 | 20 | 20/20 | 20/20 | 6.35 → 2.40 | 9.10 → 4.50 | 72.6 → 28.5 | 58% | 8.0 | 0.0 |
| corruption | B3 | order+resources | 20 | 20 | 20/20 | 19/20 | 6.35 → 1.60 | 9.10 → 4.35 | 72.6 → 20.4 | 70% | 6.8 | 2.7 |
| corruption | R+opt | order | 39 | 39 | 39/39 | 39/39 | 6.49 → 2.31 | 9.05 → 4.15 | 73.9 → 27.2 | 59% | 7.9 | 0.0 |
| corruption | R+opt | order+resources | 39 | 39 | 39/39 | 39/39 | 6.49 → 1.62 | 9.05 → 4.15 | 73.9 → 20.3 | 69% | 7.4 | 3.2 |
| generation | B1+opt | order | 8 | 8 | 8/8 | 8/8 | 3.75 → 2.12 | 7.00 → 4.00 | 44.5 → 25.2 | 39% | 5.0 | 0.0 |
| generation | B1+opt | order+resources | 8 | 8 | 8/8 | 8/8 | 3.75 → 1.12 | 7.00 → 4.00 | 44.5 → 15.2 | 65% | 4.9 | 3.2 |
| generation | B3 | order | 19 | 14 | 19/19 | 19/19 | 4.21 → 3.00 | 6.74 → 5.11 | 48.8 → 35.1 | 38% | 3.7 | 0.0 |
| generation | B3 | order+resources | 19 | 18 | 19/19 | 19/19 | 4.21 → 1.74 | 6.74 → 5.05 | 48.8 → 22.4 | 47% | 3.1 | 3.1 |
| generation | R+opt | order | 39 | 33 | 39/39 | 37/39 | 5.95 → 2.97 | 8.64 → 5.28 | 68.1 → 35.0 | 48% | 7.3 | 0.0 |
| generation | R+opt | order+resources | 39 | 39 | 39/39 | 36/39 | 5.95 → 1.97 | 8.64 → 5.08 | 68.1 → 24.8 | 65% | 6.4 | 3.5 |
| reference | REF+opt | order | 13 | 13 | 13/13 | 13/13 | 6.46 → 2.31 | 9.00 → 4.15 | 73.6 → 27.2 | 59% | 7.8 | 0.0 |
| reference | REF+opt | order+resources | 13 | 13 | 13/13 | 13/13 | 6.46 → 1.62 | 9.00 → 4.15 | 73.6 → 20.3 | 69% | 7.2 | 3.2 |

## Weight sensitivity (all accepted LLM-system plans: B1+opt and B3)

A plan has a *trade-off* if its optimal (machine changes, tool changes) differs between weight settings. Only those solved to proven optimality at every weight are genuine; the rest may differ because a solve hit its time limit. B1+opt and B3 share the plans that were valid without repair, so such a plan is counted once per system.

| Mode | Machine : tool weight | Machine changes after | Tool changes after | Plans improved |
|---|---|---|---|---|
| order | (input plans) | 5.04 | 7.79 | – |
| order | 1 : 1 | 2.62 | 4.64 | 42/47 |
| order | 1 : 10 | 2.64 | 4.62 | 42/47 |
| order | 10 : 1 | 2.60 | 4.66 | 42/47 |
| order | 100 : 1 | 2.60 | 4.66 | 42/47 |
| order | plans with a trade-off | 2/47 | | |
| order | … of which proven optimal at every weight | 2/47 | | |
| order+resources | (input plans) | 5.04 | 7.79 | – |
| order+resources | 1 : 1 | 1.57 | 4.57 | 46/47 |
| order+resources | 1 : 10 | 1.57 | 4.57 | 46/47 |
| order+resources | 10 : 1 | 1.57 | 4.57 | 46/47 |
| order+resources | 100 : 1 | 1.57 | 4.57 | 46/47 |
| order+resources | plans with a trade-off | 0/47 | | |
| order+resources | … of which proven optimal at every weight | 0/47 | | |

Plans invalid after optimization: **0** of 1104 optimizer runs.
Solver statuses: {'FEASIBLE': 25, 'OPTIMAL': 1079}; tie-break statuses: {'FEASIBLE': 548, 'OPTIMAL': 556}.
