"""Build the CAD test fixture (run with FreeCAD's python): a block with known features.

    "C:/Program Files/FreeCAD 1.1/bin/python.exe" scripts/freecad/make_cad_fixture.py

Writes tests/fixtures/cad/demo_block.step and demo_block_truth.json. The geometry is authored here for
SCMPA (MIT); the truth file lists exactly what was modelled, for testing the extractor.
"""

import json
import math
import os
import sys

import FreeCAD
import Part

V = FreeCAD.Vector
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tests", "fixtures", "cad")


def drilled(x, y, d, depth, top=30.0):
    """A blind drilled hole from the top face with a 118 degree drill point."""
    r = d / 2
    cyl = Part.makeCylinder(r, depth, V(x, y, top - depth), V(0, 0, 1))
    tip = r / math.tan(math.radians(59))
    cone = Part.makeCone(0, r, tip, V(x, y, top - depth - tip), V(0, 0, 1))
    return cyl.fuse(cone)


def rounded_rect(x0, y0, lx, ly, r, z0, h):
    box = Part.makeBox(lx, ly, h, V(x0, y0, z0))
    return box.makeFillet(r, [e for e in box.Edges if abs(e.tangentAt(e.FirstParameter).z) > 0.99])


block = Part.makeBox(100, 80, 30)
cuts = [  # laid out so that no two features intersect
    Part.makeCylinder(4, 40, V(12, 70, -5)),                       # through hole d8 (30 deep)
    drilled(25, 70, 6, 12),                                         # blind hole d6, depth 12 (+ drill point)
    Part.makeCylinder(3, 40, V(40, 70, -5)).fuse(Part.makeCylinder(5.5, 6, V(40, 70, 24))),  # d6 through + d11 counterbore 6 deep
    rounded_rect(10, 25, 30, 20, 3, 22, 10),                       # pocket 30x20, depth 8, corner radius 3
    Part.makeBox(30, 10, 5, V(55, 30, 25)).fuse(Part.makeCylinder(5, 5, V(55, 35, 25))).fuse(Part.makeCylinder(5, 5, V(85, 35, 25))),  # round-ended slot 40x10, depth 5
    Part.makeBox(100, 8, 6, V(0, 50, 24)),                         # through slot along X: 8 wide, 6 deep
    Part.makeBox(100, 10, 10, V(0, 0, 20)),                        # step along the -Y edge: 10 wide, 10 deep
]
part = block
for c in cuts:
    part = part.cut(c)
part = part.removeSplitter()
os.makedirs(OUT, exist_ok=True)
step = os.path.join(OUT, "demo_block.step")
part.exportStep(step)

truth = {
    "note": "Authored for SCMPA tests (MIT). Block 100 x 80 x 30 mm; all features machined from +Z.",
    "features": [
        {"type": "through_hole", "diameter_mm": 8, "depth_mm": 30},
        {"type": "blind_hole", "diameter_mm": 6, "depth_mm": 12},
        {"type": "through_hole", "diameter_mm": 6, "depth_mm": 24, "counterbore_diameters_mm": [11]},
        {"type": "pocket", "depth_mm": 8, "length_mm": 30, "width_mm": 20},
        {"type": "slot", "depth_mm": 5, "length_mm": 40, "width_mm": 10},
        {"type": "slot", "depth_mm": 6, "length_mm": 100, "width_mm": 8},
        {"type": "step", "depth_mm": 10, "length_mm": 100, "width_mm": 10},
    ],
}
with open(os.path.join(OUT, "demo_block_truth.json"), "w", encoding="utf-8") as fh:
    json.dump(truth, fh, indent=2)
print("wrote", step, "solids", len(part.Solids), "faces", len(part.Faces), file=sys.stderr)
