"""Triangles of a faceted STEP file (for example a Creo shrinkwrap), with no CAD kernel.

A faceted file holds only flat faces: ADVANCED_FACE on a PLANE with one EDGE_LOOP of straight edges, or a
FACE_OUTER_BOUND with a POLY_LOOP. An edge that is a single-span B-spline (a Bezier curve, which Creo writes on
some flat faces) is sampled at 8 segments. Each face becomes a fan of triangles. The length unit of the file (INCH, FOOT,
or an SI metre with a prefix) converts the points to metres. The frame stays the frame of the file. A curved face
or a face with a hole is refused: such a file needs a CAD export as STL.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

_ENTITY = re.compile(r"#(\d+)\s*=\s*(.*)", re.S)
_REF = re.compile(r"#(\d+)")
_CONVERSION = {"INCH": 0.0254, "FOOT": 0.3048, "MILLIMETRE": 0.001, "MILLIMETER": 0.001}
_PREFIX = {".MILLI.": 1e-3, ".CENTI.": 1e-2, ".DECI.": 1e-1, "$": 1.0, ".KILO.": 1e3, ".MICRO.": 1e-6}


class StepMeshError(ValueError):
    pass


def _entities(text: str) -> Dict[int, str]:
    data = text[text.index("DATA;") + 5:]
    data = data[: data.rindex("ENDSEC;")]
    out = {}
    for stmt in data.replace("\r", "").replace("\n", "").split(";"):
        m = _ENTITY.match(stmt.strip())
        if m:
            out[int(m.group(1))] = m.group(2).strip()
    return out


def _type(body: str) -> str:
    return body[: body.index("(")].strip() if not body.startswith("(") else "COMPLEX"


def _args(body: str) -> str:
    return body[body.index("(") + 1: body.rindex(")")]


def length_unit(ents: Dict[int, str]) -> Tuple[str, float]:
    """(name, metres per unit) of the length unit."""
    for body in ents.values():
        if "LENGTH_UNIT" in body and "CONVERSION_BASED_UNIT" in body:
            name = re.search(r"CONVERSION_BASED_UNIT\s*\(\s*'([^']*)'", body).group(1).upper()
            if name not in _CONVERSION:
                raise StepMeshError(f"unknown STEP length unit {name}")
            return name, _CONVERSION[name]
    for body in ents.values():
        if "LENGTH_UNIT" in body and "SI_UNIT" in body:
            m = re.search(r"SI_UNIT\s*\(\s*([^,]+),\s*\.METRE\.\s*\)", body)
            if m and m.group(1).strip() in _PREFIX:
                prefix = m.group(1).strip()
                return f"{prefix.strip('.$').lower()}metre", _PREFIX[prefix]
    raise StepMeshError("the STEP file has no length unit")


def read_step_faceted(path: Path) -> Tuple[np.ndarray, str]:
    """(triangles (n, 3, 3) in metres, unit name) of a faceted STEP file."""
    ents = _entities(Path(path).read_text(encoding="utf-8", errors="replace"))
    unit, scale = length_unit(ents)

    def point(i: int) -> np.ndarray:
        body = ents[i]
        if _type(body) == "VERTEX_POINT":
            return point(int(_REF.findall(body)[-1]))
        nums = re.findall(r"\(([^()]*)\)", body)[-1]
        return np.array([float(v) for v in nums.split(",")], float)

    def loop_points(i: int) -> List[np.ndarray]:
        body = ents[i]
        kind = _type(body)
        if kind == "POLY_LOOP":
            return [point(int(r)) for r in _REF.findall(body)]
        if kind != "EDGE_LOOP":
            raise StepMeshError(f"#{i}: a {kind} bound is not faceted")
        pts = []
        for r in _REF.findall(body):
            oe = ents[int(r)]
            refs = _REF.findall(oe)
            ec = ents[int(refs[-1])]
            v = _REF.findall(ec)
            curve = ents[int(v[2])]
            same = oe.rstrip(")").rstrip().endswith(".T.") == ec.rstrip(")").rstrip().endswith(".T.")
            a, b = point(int(v[0])), point(int(v[1]))
            seg = [a] + _bezier(curve, a, b) if _type(curve) == "B_SPLINE_CURVE_WITH_KNOTS" else [a]
            if _type(curve) not in ("LINE", "POLYLINE", "B_SPLINE_CURVE_WITH_KNOTS"):
                raise StepMeshError(f"#{r}: a {_type(curve)} edge is not faceted")
            pts += seg if same else ([b] + _bezier(curve, b, a) if len(seg) > 1 else [b])
        return pts

    def _bezier(curve: str, start: np.ndarray, end: np.ndarray, n: int = 8) -> List[np.ndarray]:
        """Interior points of a single-span B-spline edge (a Bezier curve) from start to end."""
        deg = int(_args(curve).split(",")[1])
        ctrl = [point(int(r)) for r in _REF.findall(curve)]
        if len(ctrl) != deg + 1:
            raise StepMeshError("a B-spline edge with more than one span is not supported")
        c = np.array(ctrl)
        if np.linalg.norm(c[0] - start) > np.linalg.norm(c[-1] - start):
            c = c[::-1]
        out = []
        for t in np.linspace(0.0, 1.0, n + 1)[1:-1]:
            q = c.copy()
            for k in range(1, len(q)):
                q = (1 - t) * q[:-1] + t * q[1:]
            out.append(q[0])
        return out

    tris = []
    for i, body in ents.items():
        kind = _type(body)
        if kind not in ("ADVANCED_FACE", "FACE_SURFACE"):
            continue
        refs = _REF.findall(body)
        surf = ents[int(refs[-1])]
        if _type(surf) != "PLANE":
            raise StepMeshError(f"#{i}: a face on a {_type(surf)} is not faceted")
        bounds = refs[:-1]
        if len(bounds) != 1:
            raise StepMeshError(f"#{i}: a face with {len(bounds)} bounds (a hole) is not supported")
        fb = ents[int(bounds[0])]
        poly = loop_points(int(_REF.findall(fb)[0]))
        if fb.rstrip(")").rstrip().endswith(".F."):
            poly = poly[::-1]
        if body.rstrip(")").rstrip().endswith(".F."):
            poly = poly[::-1]
        for k in range(1, len(poly) - 1):
            tris.append([poly[0], poly[k], poly[k + 1]])
    if not tris:
        raise StepMeshError(f"{Path(path).name} holds no faces")
    return np.array(tris, float) * scale, unit
