"""CAD feature extraction with FreeCAD (Milestone 6): STEP geometry -> SCMPA features (derived data).

FreeCAD ships its own Python (3.11 for FreeCAD 1.x), separate from SCMPA's environment, so the
geometric work runs in a subprocess (``freecad_extract.py``) and returns JSON. This module finds
FreeCAD, runs the extractor and turns the result into an SCMPA :class:`Component`.

    python -m scmpa.cad part.step --resources resources.json --out part_component.json

CAD-derived features stay distinguishable from hand-written or synthetic ones: each carries a
``CAD:`` description with its geometric evidence, and the component's provenance is ``derived``
from the STEP file. Machines and tools are not in the geometry and must be supplied.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from scmpa.io import load_catalogue, read_json, validate_component
from scmpa.schemas import Component

SCRIPT = Path(__file__).with_name("freecad_extract.py")
DEFAULT_FREECAD_DIRS = [
    r"C:\Program Files\FreeCAD 1.1", r"C:\Program Files\FreeCAD 1.0", r"C:\Program Files\FreeCAD 1.2",
    "/usr/lib/freecad", "/usr/lib/freecad-python3", "/Applications/FreeCAD.app/Contents/Resources",
]
#: Extracted types SCMPA can plan for; everything else is reported, not forced into a type.
SUPPORTED = {"through_hole", "blind_hole", "pocket", "slot"}


class FreeCADNotFound(RuntimeError):
    pass


def find_freecad() -> tuple[Path, list[str]]:
    """Return (python executable, extra sys.path entries) for FreeCAD; ``$SCMPA_FREECAD_DIR`` overrides."""
    candidates = [os.environ["SCMPA_FREECAD_DIR"]] if os.environ.get("SCMPA_FREECAD_DIR") else DEFAULT_FREECAD_DIRS
    for base in map(Path, candidates):
        for py in (base / "bin" / "python.exe", base / "bin" / "python3", base / "bin" / "python"):
            if py.exists():
                return py, [str(base / "bin"), str(base / "lib")]
    raise FreeCADNotFound("FreeCAD not found; install FreeCAD >= 1.0 or set SCMPA_FREECAD_DIR to its folder")


def extract_features(step_path: str | Path, timeout_s: float = 300) -> dict[str, Any]:
    """Run the FreeCAD extractor on a STEP file and return its JSON result."""
    py, paths = find_freecad()
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "features.json"
        proc = subprocess.run([str(py), str(SCRIPT), str(Path(step_path).resolve()), str(out)],
                              env=env, capture_output=True, text=True, timeout=timeout_s)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"FreeCAD extraction failed for {step_path}: {proc.stderr.strip()[-2000:]}")
        return json.loads(out.read_text(encoding="utf-8"))


def to_component(extraction: dict[str, Any], component_id: str, resources: dict[str, Any], *,
                 material: str = "unspecified", catalogue=None) -> tuple[Component, list[dict[str, Any]]]:
    """Build an SCMPA component from an extraction. Returns (component, unsupported features)."""
    catalogue = catalogue or load_catalogue()
    features, unsupported = [], []
    for x in extraction["features"]:
        if x["type"] not in SUPPORTED:
            unsupported.append(x)
            continue
        fid = f"F{len(features) + 1}"
        dims = {k: x[k] for k in ("diameter_mm", "depth_mm", "width_mm", "length_mm") if x.get(k)}
        evidence = f"solid {x['solid']}, faces {x['faces']}"
        extra = f"; counterbore Ø{x['counterbore_diameters_mm']} not modelled" if x.get("counterbore_diameters_mm") else ""
        approach = f"; approach {x['direction']}" if x.get("direction") else ""
        features.append({"feature_id": fid, "type": x["type"], "required": True,
                         "description": f"CAD: {x['type'].replace('_', ' ')} from geometry ({evidence}{approach}{extra})", **dims})
    if not features:
        raise ValueError("no extracted feature maps to an SCMPA feature type")
    data = {
        "component_id": component_id,
        "description": f"Features extracted from {Path(extraction['source_file']).name} by FreeCAD {extraction['freecad_version']}; "
                       f"bounding box {extraction['bounding_box_mm']} mm.",
        "material": material,
        "features": features,
        "resources": resources,
        "assumptions": [
            "Features were extracted from B-rep geometry by scmpa.cad (rules in docs/cad_extraction.md), not authored by hand.",
            "Threads, tolerances, chamfers, fillets and turned features are not extracted; counterbores are noted, not modelled.",
            "Machines and tools were supplied separately; the geometry contains no resource data.",
            "No precedence constraints are derived from geometry alone.",
            *([f"{len(unsupported)} extracted feature(s) have no SCMPA type and were left out: "
               + ", ".join(sorted({u['type'] for u in unsupported}))] if unsupported else []),
        ],
        "provenance": {"source_type": "derived", "source": f"STEP file {Path(extraction['source_file']).name}, "
                       f"{extraction['extractor']} v{extraction['extractor_version']}"},
    }
    return validate_component(data, catalogue, component_id), unsupported


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", help="STEP file")
    parser.add_argument("--resources", help="JSON with {'machines': [...], 'tools': [...]} (SCMPA Resources)")
    parser.add_argument("--component-id", help="default: the STEP file name")
    parser.add_argument("--material", default="unspecified")
    parser.add_argument("--out", help="write the component (or, without --resources, the raw extraction) here")
    args = parser.parse_args(argv)
    extraction = extract_features(args.step)
    if not args.resources:
        text = json.dumps(extraction, indent=2)
    else:
        cid = args.component_id or Path(args.step).stem.replace(".", "_")
        component, unsupported = to_component(extraction, cid, read_json(args.resources), material=args.material)
        text = component.model_dump_json(indent=2)
        print(f"{len(component.features)} features mapped, {len(unsupported)} left out", file=sys.stderr)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
