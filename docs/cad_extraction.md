# CAD feature extraction with FreeCAD (M6)

`scmpa.cad` reads a STEP file with FreeCAD, finds machining features in the B-rep geometry and turns them into an SCMPA component. It is a separate module, as the spec asks, and its output is marked as CAD-derived.

```bash
# FreeCAD >= 1.0 must be installed (or set SCMPA_FREECAD_DIR to its folder)
python -m scmpa.cad part.step                                               # raw extraction (JSON)
python -m scmpa.cad part.step --resources resources.json --out part.json   # SCMPA component
```

## How it works

FreeCAD ships its own Python (3.11 for FreeCAD 1.x), which is not SCMPA's environment. The geometric code (`src/scmpa/cad/freecad_extract.py`) therefore runs in FreeCAD's Python as a subprocess, using only the standard library, `FreeCAD` and `Part`, and it returns JSON. `scmpa.cad.to_component` maps that JSON to SCMPA features.

| Detected | Rule (geometry only: no feature tree, no text) |
|---|---|
| **Hole** (`through_hole`, `blind_hole`) | Concave cylindrical faces (a probe just inside the cylinder lands in empty space) whose angular spans add up to a full circle. Coaxial cylinders are grouped: the smallest radius is the hole, larger ones are counterbores. **Through or blind:** probe the solid one radius plus 1 mm beyond each end, which clears a drill-point cone. |
| **Pocket** | A planar face aligned with an axis of the solid's bounding box, strictly inside it, with a clear line of sight out of the part along its normal (the tool's approach). It reaches no side of the bounding box (closed pocket), or exactly one side (open pocket). |
| **Slot** | Such a floor that is closed, at least twice as long as wide, with round ends; or one open at two opposite sides only (through slot). |
| **Step** | Such a floor open on two or more non-opposite sides. A step is open in two directions, so its floor and its wall both qualify: adjacent step faces are merged into one step, keeping the +Z, −Z, +X, −X, +Y, −Y approach in that order of preference. SCMPA has no step type, so steps are reported and left out of the component. |

**Not extracted:**
- threads (rarely present in B-rep geometry), tolerances, chamfers and fillets;
- turned features, and features on non-axis-aligned faces.

**Limits of the approach:**
- Features are measured against each solid's own bounding box; a part made of several solids (FabriCAD's welded parts) is analysed solid by solid.
- No precedence is derived from geometry, and the machines and tools must be supplied.

**Provenance:**
- Every feature's description starts with `CAD:` and names its solid and face indices, so CAD-derived features stay distinct from hand-written or synthetic ones (spec M6).
- The component's provenance is `derived` from the STEP file and extractor version.
- `run_experiments`, the validator and the optimizer then treat the component like any other.

## Verification

**1. A modelled part with known features.** `scripts/freecad/make_cad_fixture.py` builds `tests/fixtures/cad/demo_block.step`, authored for SCMPA under MIT. It is a 100 × 80 × 30 mm block with seven features:
- a through hole Ø8;
- a blind hole Ø6 × 12 with a drill-point cone;
- a through hole Ø6 with a Ø11 counterbore;
- a 30 × 20 × 8 pocket with corner radius 3;
- a round-ended slot 40 × 10 × 5;
- a through slot 8 × 6;
- an edge step 10 × 10.

The extractor finds all seven, with correct types and dimensions (`tests/unit/test_cad.py`). The resulting component (6 features; the step is left out) is planned, repaired and accepted by the workflow.

**2. FabriCAD's 30 preview parts against their own labels** (`scripts/freecad/evaluate_on_fabricad.py`, run on a local copy; FabriCAD data is CC BY-NC 4.0 and is not committed). FabriCAD's feature list serves as ground truth, and matching is count-based per part and category:

| Category | Labelled | Extracted | Matched | Recall | Precision | Parts with exact count |
|---|---|---|---|---|---|---|
| hole | 114 | 118 | 109 | 96% | 92% | 17/30 |
| pocket | 34 | 47 | 30 | 88% | 64% | 17/30 |
| slot | 25 | 18 | 17 | 68% | 94% | 22/30 |
| step | 29 | 47 | 27 | 93% | 57% | 17/30 |

Hole diameters: 107 of 114 labelled holes match an extracted hole of the same diameter (±0.05 mm).

**How to read this:**
- **Holes are reliable.**
- **Pockets and steps are over-detected.** Known sources:
  - FabriCAD's welded add-on parts are separate solids, and an angle's inside corner looks like a step (11 of the 47 steps).
  - Chamfered shoulders (`abgeschrägter Absatz`) and stepped pocket floors produce several floors for one labelled feature.
  - Taxonomy differs at the edges: FabriCAD calls a pocket open on one side a `Tasche`, and a long open-ended cut a `Schlitz-Stufe`.
- **Slot recall is limited** because some FabriCAD slots open into neighbouring features, so their floors do not match the slot pattern.
- **The rules were adjusted once on this data,** after an inspection: one-side-open floors were moved from "step" to "pocket" to match FabriCAD's taxonomy. The table therefore shows in-sample performance, not a held-out estimate. A fair estimate needs the full FabriCAD release, which is available on request.

## Relation to the FabriCAD importer

The importer (`scmpa.importers.fabricad`) reads FabriCAD's **text** labels. This extractor reads **geometry**. They are independent, which is what makes the cross-check above possible. They could be combined: geometry for positions and dimensions, text for threads and fits, which the geometry does not carry.
