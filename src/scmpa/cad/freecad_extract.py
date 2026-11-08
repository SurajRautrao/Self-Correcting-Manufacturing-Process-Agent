"""Geometric feature extraction from a STEP file with FreeCAD (Milestone 6).

THIS FILE RUNS INSIDE FreeCAD's OWN PYTHON (3.11 for FreeCAD 1.x), not in the SCMPA
environment. It imports only the standard library, FreeCAD and Part, and writes JSON.
SCMPA calls it through :func:`scmpa.cad.extract_features`.

    "C:/Program Files/FreeCAD 1.1/bin/python.exe" freecad_extract.py part.step out.json

Detected from the B-rep alone (no text, no feature tree):

* **Holes:** concave cylindrical faces whose combined angular span closes a full circle.
  Coaxial cylinders of different radii are grouped into one hole; the smallest is the
  hole and larger ones are recorded as a counterbore. Through or blind is decided by
  probing the solid just beyond each end of the hole, past a possible drill-point cone.
* **Floors** (planar faces aligned with an axis of the solid's bounding box, lying strictly
  inside it and facing open space), classified by how many sides of the solid's bounding
  box the floor reaches:
    - none: ``pocket``, or ``slot`` if elongated (aspect ratio >= 2) with round ends;
    - one side: ``pocket`` (an open pocket);
    - two opposite sides only: ``slot`` (through slot);
    - otherwise: ``step`` (shoulder/step; no SCMPA equivalent).

Not detected: threads (rarely present in B-rep), chamfers, fillets, turned features,
tolerances. Features are given per solid relative to that solid's bounding box.
"""

from __future__ import annotations

import json
import math
import sys

import FreeCAD  # noqa: F401  (provided by FreeCAD's python)
import Part

EXTRACTOR_VERSION = "1.0"
TOL = 1e-3
AXES = {"X": FreeCAD.Vector(1, 0, 0), "Y": FreeCAD.Vector(0, 1, 0), "Z": FreeCAD.Vector(0, 0, 1)}


def _r(x: float) -> float:
    return round(float(x), 3)


def _axis_name(v) -> str | None:
    for name, a in AXES.items():
        d = v.dot(a)
        if abs(abs(d) - 1) < 1e-6:
            return ("+" if d > 0 else "-") + name
    return None


def _bb(solid, name: str) -> tuple[float, float]:
    b = solid.BoundBox
    return {"X": (b.XMin, b.XMax), "Y": (b.YMin, b.YMax), "Z": (b.ZMin, b.ZMax)}[name]


def _is_concave_cylinder(solid, face) -> bool:
    """A point just inside the cylinder (towards its axis) lies in empty space for a hole wall."""
    cyl = face.Surface
    u0, u1, v0, v1 = face.ParameterRange
    p = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
    axis = cyl.Axis.normalize()
    centre = cyl.Center
    to_p = p - centre
    radial = to_p - axis * to_p.dot(axis)
    if radial.Length < TOL:
        return False
    eps = min(0.05, cyl.Radius * 0.05)
    probe = p - radial.normalize() * eps
    return not solid.isInside(probe, 1e-6, True)


def _extent_along(face, axis) -> tuple[float, float]:
    pts = [v for e in face.Edges for v in e.discretize(12)]
    proj = [p.dot(axis) for p in pts]
    return min(proj), max(proj)


def _line_key(cyl) -> tuple:
    """Group coaxial cylinders: axis direction (sign-normalised) and the axis' foot point."""
    a = cyl.Axis.normalize()
    if a.x < -1e-9 or (abs(a.x) < 1e-9 and (a.y < -1e-9 or (abs(a.y) < 1e-9 and a.z < 0))):
        a = -a
    c = cyl.Center
    foot = c - a * c.dot(a)
    return (round(a.x, 4), round(a.y, 4), round(a.z, 4), round(foot.x, 2), round(foot.y, 2), round(foot.z, 2))


def holes_in(solid, si: int) -> tuple[list[dict], list[int]]:
    groups: dict[tuple, list] = {}
    for fi, f in enumerate(solid.Faces):
        if type(f.Surface).__name__ == "Cylinder" and _is_concave_cylinder(solid, f):
            groups.setdefault(_line_key(f.Surface), []).append((fi, f))
    holes, used = [], []
    for key, faces in groups.items():
        by_r: dict[float, list] = {}
        for fi, f in faces:
            by_r.setdefault(round(f.Surface.Radius, 3), []).append((fi, f))
        full = {r: fs for r, fs in by_r.items() if sum(f.ParameterRange[1] - f.ParameterRange[0] for _, f in fs) >= 2 * math.pi - 1e-3}
        if not full:
            continue  # partial arcs: pocket corners or slot ends, not holes
        r = min(full)
        axis = FreeCAD.Vector(*key[:3])
        lo = min(_extent_along(f, axis)[0] for _, f in full[r])
        hi = max(_extent_along(f, axis)[1] for _, f in full[r])
        foot = FreeCAD.Vector(*key[3:])
        reach = r + 1.0  # past a drill-point cone (depth about 0.6 r)
        open_lo = not solid.isInside(foot + axis * (lo - reach), 1e-6, True)
        open_hi = not solid.isInside(foot + axis * (hi + reach), 1e-6, True)
        through = open_lo and open_hi
        counterbores = sorted(2 * x for x in full if x > r)
        holes.append({
            "type": "through_hole" if through else "blind_hole",
            "diameter_mm": _r(2 * r), "depth_mm": _r(hi - lo), "through": through,
            "axis": [round(axis.x, 4), round(axis.y, 4), round(axis.z, 4)],
            "counterbore_diameters_mm": [_r(c) for c in counterbores],
            "solid": si, "faces": sorted(fi for fs in full.values() for fi, _ in fs),
        })
        used += [fi for fi, _ in faces]
    return holes, used


def _point_on(face):
    """A point inside the face (its centre of mass may fall outside a non-convex face)."""
    if face.isInside(face.CenterOfMass, 1e-6, True):
        return face.CenterOfMass
    u0, u1, v0, v1 = face.ParameterRange
    for i in range(1, 10):
        for j in range(1, 10):
            p = face.valueAt(u0 + (u1 - u0) * i / 10, v0 + (v1 - v0) * j / 10)
            if face.isInside(p, 1e-6, True):
                return p
    return None


def _clear_ray(solid, start, n, length: float) -> bool:
    steps = max(10, int(length / 0.5))
    return all(not solid.isInside(start + n * (0.05 + (length - 0.05) * k / steps), 1e-6, True) for k in range(steps + 1))


def _merge_steps(solid, feats: list[dict]) -> list[dict]:
    """A step is open in two directions, so its floor and its wall both qualify: keep one per connected step.

    Adjacent step faces (sharing an edge) are merged; the face whose approach direction comes first
    in +Z, -Z, +X, -X, +Y, -Y is kept (a stated preference, not a machining rule).
    """
    order = ["+Z", "-Z", "+X", "-X", "+Y", "-Y"]
    steps = sorted((f for f in feats if f["type"] == "step"), key=lambda f: order.index(f["direction"]))
    kept: list[dict] = []
    for f in steps:
        face = solid.Faces[f["faces"][0]]
        twin = next((k for k in kept if any(e.isSame(e2) for e in face.Edges for e2 in solid.Faces[k["faces"][0]].Edges)), None)
        if twin is None:
            kept.append(f)
        else:
            twin["faces"].append(f["faces"][0])
            twin.setdefault("also_open_towards", []).append(f["direction"])
    return [f for f in feats if f["type"] != "step"] + kept


def floors_in(solid, si: int, hole_faces: set[int]) -> list[dict]:
    out = []
    for fi, f in enumerate(solid.Faces):
        if type(f.Surface).__name__ != "Plane":
            continue
        u0, u1, v0, v1 = f.ParameterRange
        n = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        name = _axis_name(n)
        if name is None:
            continue
        axis = name[1]
        lo, hi = _bb(solid, axis)
        pos = f.CenterOfMass.dot(AXES[axis])
        if not (lo + TOL < pos < hi - TOL):
            continue  # on the bounding box: an outer face
        if all(type(e.Curve).__name__ == "Circle" for e in f.Edges):
            continue  # flat bottom of a blind hole
        depth = (hi - pos) if name[0] == "+" else (pos - lo)
        # A floor sees open space all the way out of the part along its normal (the tool's approach).
        # A pocket or slot wall does not: its line of sight hits the opposite wall.
        start = _point_on(f)
        if start is None or not _clear_ray(solid, start, n, depth + 1.0):
            continue
        others = [a for a in "XYZ" if a != axis]
        fb = f.BoundBox
        touches = []
        for a in others:
            flo, fhi = {"X": (fb.XMin, fb.XMax), "Y": (fb.YMin, fb.YMax), "Z": (fb.ZMin, fb.ZMax)}[a]
            blo, bhi = _bb(solid, a)
            if abs(flo - blo) < 0.01:
                touches.append("-" + a)
            if abs(fhi - bhi) < 0.01:
                touches.append("+" + a)
        ext = sorted([{"X": fb.XLength, "Y": fb.YLength, "Z": fb.ZLength}[a] for a in others])
        width, length = ext[0], ext[1]
        round_ends = any(type(e.Curve).__name__ == "Circle" and abs(e.Curve.Radius - width / 2) < 0.05 for e in f.Edges)
        if not touches:
            kind = "slot" if (length >= 2 * width and round_ends) else "pocket"
        elif len(touches) == 1:
            kind = "pocket"  # open pocket (open on one side), as FabriCAD's "Rechteckige Tasche" at an edge
        elif len(touches) == 2 and touches[0][1] == touches[1][1]:
            kind = "slot"  # open at both ends only: a through slot
        else:
            kind = "step"
        out.append({
            "type": kind, "direction": name, "depth_mm": _r(depth), "length_mm": _r(length), "width_mm": _r(width),
            "open_sides": touches, "solid": si, "faces": [fi],
        })
    return _merge_steps(solid, out)


def extract(path: str) -> dict:
    shape = Part.Shape()
    shape.read(path)
    features, unclassified = [], 0
    for si, solid in enumerate(shape.Solids):
        holes, used = holes_in(solid, si)
        floors = floors_in(solid, si, set(used))
        features += holes + floors
        unclassified += sum(1 for f in solid.Faces if type(f.Surface).__name__ not in ("Plane", "Cylinder"))
    b = shape.BoundBox
    return {
        "extractor": "scmpa.cad.freecad_extract", "extractor_version": EXTRACTOR_VERSION,
        "freecad_version": ".".join(FreeCAD.Version()[:3]), "source_file": path, "units": "mm",
        "solids": len(shape.Solids), "faces": len(shape.Faces),
        "bounding_box_mm": [_r(b.XLength), _r(b.YLength), _r(b.ZLength)],
        "features": features, "non_planar_non_cylindrical_faces": unclassified,
    }


if __name__ == "__main__":
    result = extract(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
