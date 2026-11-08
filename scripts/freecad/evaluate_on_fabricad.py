"""Evaluate the FreeCAD feature extractor against FabriCAD's feature labels.

    python scripts/freecad/evaluate_on_fabricad.py <fabricad_root> [--out data/external/fabricad/cad_eval.md]

For each FabriCAD sample with a final STEP model, it runs scmpa.cad.extract_features on the geometry and
compares the result with the sample's own feature list (interim/substeps/features.csv):

* counts per category: hole (drilling step), pocket ("Tasche"), slot ("Langloch"/"Schlitz"),
  step (other milling features except O-ring grooves);
* hole diameters: each labelled hole "Bohrung Ø d" is matched to an unused extracted hole of the
  same diameter (±0.05 mm).

FabriCAD's labels serve as ground truth here. FabriCAD data is CC BY-NC 4.0: run this on a local copy and
keep the output under data/external/ (git-ignored).
"""

from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from scmpa.cad import extract_features  # noqa: E402

CATS = ("hole", "pocket", "slot", "step")


def labels(sample: Path) -> tuple[collections.Counter, list[float]]:
    with (sample / "plan.csv").open(encoding="utf-8") as fh:
        steps = {r["Nr."]: r["Schritt"] for r in csv.DictReader(fh, delimiter=";")}
    counts, diameters = collections.Counter(), []
    with (sample / "interim" / "substeps" / "features.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            text, step = r["Kurztext"], steps.get(r["Arbeitsschritt"], "")
            if step == "bohren":
                counts["hole"] += 1
                if m := re.search(r"Ø\s*([\d.]+)", text):
                    diameters.append(float(m[1]))
            elif step == "fräsen":
                if "Tasche" in text:
                    counts["pocket"] += 1
                elif "Langloch" in text or "Schlitz" in text:
                    counts["slot"] += 1
                elif "Nut" not in text:
                    counts["step"] += 1
    return counts, diameters


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--out", default=str(ROOT / "data" / "external" / "fabricad" / "cad_eval.md"))
    args = ap.parse_args()
    samples = sorted(p.parent for p in Path(args.root).rglob("geometry_*.STEP") if (p.parent / "plan.csv").exists())
    tot = collections.Counter()
    exact = collections.Counter()
    dia_total = dia_matched = 0
    rows = []
    for s in samples:
        truth, dias = labels(s)
        ext = extract_features(next(s.glob("geometry_*.STEP")))
        found = collections.Counter({"through_hole": "hole", "blind_hole": "hole"}.get(f["type"], f["type"]) for f in ext["features"])
        pool = [f["diameter_mm"] for f in ext["features"] if f["type"] in ("through_hole", "blind_hole")]
        for d in dias:
            hit = next((i for i, x in enumerate(pool) if abs(x - d) <= 0.05), None)
            dia_total += 1
            if hit is not None:
                dia_matched += 1
                pool.pop(hit)
        for c in CATS:
            tot[c, "truth"] += truth[c]
            tot[c, "found"] += found[c]
            tot[c, "matched"] += min(truth[c], found[c])
            exact[c] += truth[c] == found[c]
        rows.append((s.name, ext["solids"], {c: truth[c] for c in CATS}, {c: found[c] for c in CATS}))
        print(f"{s.name}: truth {dict(truth)} found {dict(found)}", flush=True)
    lines = ["# FreeCAD extractor vs FabriCAD labels", "",
             f"{len(samples)} samples. Count-based matching: matched = min(labelled, extracted) per sample and category.", "",
             "| Category | Labelled | Extracted | Matched | Recall | Precision | Samples with exact count |", "|---|---|---|---|---|---|---|"]
    for c in CATS:
        t, f, m = tot[c, "truth"], tot[c, "found"], tot[c, "matched"]
        lines.append(f"| {c} | {t} | {f} | {m} | {m / t:.0%} | {m / f:.0%} | {exact[c]}/{len(samples)} |" if t and f else f"| {c} | {t} | {f} | {m} | – | – | {exact[c]}/{len(samples)} |")
    lines += ["", f"Hole diameters: {dia_matched}/{dia_total} labelled holes matched an extracted hole of the same diameter (±0.05 mm).", "",
              "| Sample | Solids | Labelled | Extracted |", "|---|---|---|---|"] + [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
