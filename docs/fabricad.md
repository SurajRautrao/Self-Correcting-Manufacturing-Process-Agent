# FabriCAD: investigation and importer (M6)

Spec section 7.1 names FabriCAD as the first candidate data source and asks to inspect its structure, fields and license before writing an importer, without assuming every sample has what SCMPA needs. This file records what was found and what the importer does.

## Source

- **Project:** FabriCAD, CIMTT / Institut für Produktionstechnik, FH Kiel. Repository: https://github.com/CIMTT-Kiel/FabriCAD. Project page: https://cimtt-kiel.github.io/FabriCAD.
- **Paper (cite when using the data):** M. Kruse, D. Böhnke, F. Heinze, J. Borowski, *FabriCAD: Large-Scale Synthetic Dataset for Automated Manufacturing Process Planning with a Transformer-based Baseline Framework CadToSeq*, Procedia CIRP (CIRP ICME 2026), in press.
- **License:**
  - **data:** CC BY-NC 4.0 (`LICENSE-DATA`): non-commercial research and teaching, citation mandatory.
  - **code:** MIT.
  - Full releases (10k / 50k / 100k / 1k-detailed) are provided on request. The repository holds 30 preview samples.
- **Nature:** FabriCAD is itself **synthetic**. Its sequences come from Markov chains fitted to 50,000 real metalworking plans, and its geometry is generated. Records imported into SCMPA are therefore `derived` from synthetic data. They are not real industrial data.

## Inspected format

The format was inspected on the 30 public preview samples, CSV tables only (STEP geometry was not downloaded). Each sample folder holds:

| File | Content used |
|---|---|
| `plan.csv` | One row per process step: `Schritt` (German process name), `Arbeitsplatz` (workstation, e.g. `Drill_Press_02`, `CNC_Mill_06`), `Dauer[min]` |
| `plan_metadata.csv` | Stock dimensions (`Abmaße`), material (`Baustahl`, `Aluminiumlegierungen`) |
| `interim/substeps/features.csv` | One row per feature: `Arbeitsschritt` (step no.), `Subschritt`, `Kurztext` (German free text with dimensions), `Dauer[min]`, `Werkzeug[mm](D)` (tool and diameter, e.g. `Spiralbohrer (10.0)`) |

Across the preview samples:
- **Process steps:** delivery, turning, drilling, milling, welding, grinding, testing and inspection, in 11 distinct sequences.
- **Size:** 3–16 features per part.
- **Tools:** twist drills, roughing end mills and turning tools. **No taps or reamers are listed**, even for threaded or fitted holes.
- **What is missing:** feature types are only free text, and there is no precedence graph, no machine capability list and no alternative plans.

## Mapping to SCMPA

Only drilling (`bohren`) and milling (`fräsen`) features have SCMPA equivalents. Everything else is **omitted and listed** in the component's assumptions and in `import_report.json`, never forced into a type.

| FabriCAD feature text | SCMPA feature | Notes |
|---|---|---|
| `Bohrung Ø.. x ..` (± `Senkung`) | `blind_hole` | Through or blind is not stated. The counterbore or countersink is not modelled. |
| `Bohrung … mit M.. Gewinde` | `threaded_hole`, requires drilling + tapping | Diameter is the thread size |
| `Bohrung … mit Passung H7` | `blind_hole`, requires drilling + reaming | Only for fit grades ≤ 8. A loose fit such as H12 is just drilled. |
| `Rechteckige Tasche …`, `Tasche …` | `pocket` | |
| `Langloch Ø.. x ..` | `slot` | |
| steps and shoulders (`Stufe`, `Absatz`), O-ring grooves (`O-Ring-Nut`) | omitted | No SCMPA feature type |
| turning, welding, grinding features | omitted | Outside SCMPA's prismatic milling/drilling scope |

**Resources:**
- Each workstation used by a mapped step becomes a machine with an SCMPA capability template. A drill press gets spot drilling, drilling, tapping and reaming; a CNC mill gets the milling operations plus drilling and chamfering. **These capabilities are assumptions**, because FabriCAD lists none.
- Each listed tool becomes a tool (`Spiralbohrer` → drill, `Schruppfräser` → end mill).
- One tap per thread size and one reamer per fit are **assumed and labelled `ASSUMED`**, because FabriCAD lists none. Without them, every threaded part would be infeasible as an artefact of the format.

**Precedence:**
- Only drill before tap, and drill before ream, on the same hole, with a rationale.
- FabriCAD's process-step order is Markov-chain generated, so it is **not** turned into constraints: SCMPA encodes no universal order (spec 5.2).

**FabriCAD's own plan** becomes an SCMPA reference plan. It follows FabriCAD's step order and then the feature order within each step, with FabriCAD's per-feature durations. Tapping and reaming steps use the assumed tools and placeholder durations.

## What the importer gives on the 30 preview samples

| | |
|---|---|
| Samples imported | 30 / 30 (each has at least one mappable feature) |
| Features mapped | 166: 60 threaded holes, 54 holes, 34 pockets, 18 slots |
| Features omitted | 117: 36 steps or shoulders, 34 turning, 32 welding, 8 O-ring grooves, 7 grinding |
| FabriCAD-derived plans valid under SCMPA rules | 30 / 30 |
| Mock planner + 2 injected faults + rule-based repair | 43 / 43 accepted |
| Optimizer on FabriCAD's sequences | 25 of 30 improved, mean change cost 12.7 → 5.6, all still valid |

**How to read this:**
- **Plan validity is not an independent result:** the derived plans are valid largely because the importer builds the resources from what the plan uses. The check confirms that the mapping is internally consistent.
- **Part of the optimizer gain is an artefact:** FabriCAD folds threading into its drilling step, so the importer's added tapping steps alternate drill and tap tools, which the optimizer then groups.
- **Coverage is partial:** about 41% of FabriCAD's features (117 of 283) have no SCMPA equivalent, so an imported component describes only the drilled and milled part of the workpiece.

## Conclusion

FabriCAD is useful to SCMPA as a source of **externally generated feature sets** to exercise the planner, validator, repair loop and optimizer on parts it did not design. It is **not** a source of ground-truth process plans for SCMPA's rule set, for four reasons:
- Its plans are coarse and step-level.
- Threading is folded into drilling.
- It has no precedence knowledge or capability data.
- Its own content is synthetic.

A FabriCAD-based benchmark would need the full release (on request), a decision on the unmapped feature types (for example an SCMPA `step` feature milled by contour milling), and a feasibility labelling scheme that does not depend on the assumed taps and reamers.

## Use

```bash
git clone https://github.com/CIMTT-Kiel/FabriCAD ../FabriCAD        # respect CC BY-NC 4.0; cite the paper
python -m scmpa.importers.fabricad ../FabriCAD/data/preview --out data/external/fabricad
```

The output has `components/`, `reference_plans/` and `import_report.json`. The folder `data/external/` is git-ignored: do not commit FabriCAD-derived files to this MIT repository.
