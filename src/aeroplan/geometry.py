"""Shape helpers between the ADH geometry classes and the tool shapes (flow5 wings and bodies, meshes).

ADH forms used (upstream airframe_geometry.py):
  - `LiftingSurface`: leading_edge_spline and trailing_edge_spline (one point per section, design frame, m) and
    airfoil_sections (one `Airfoil` per section, in the order of `muas.planform.sections`). An airfoil spline holds
    the normalised foil contour: x = x/c, y = 0, z = z/c (Selig order: upper surface from the trailing edge to the
    leading edge, then the lower surface back to the trailing edge), degree 1.
  - `Body`: reference_axis (the body axis, design frame) and cross_sections. A cross section holds one flow5 frame:
    station = (x - x_nose) / length, upper_curve = the frame points from the top to the widest point, lower_curve =
    the widest point to the bottom. A frame that is one point (nose, tail) splits after its second point (right half, design frame, m).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

import numpy as np

from .adapters.flow5_geometry import Section, Wing
from .visual import PIVOT, _wing_to_design, lifting_surface


def _pt(p) -> Dict[str, float]:
    return {"x": float(p[0]), "y": float(p[1]), "z": float(p[2])}


def _arr(points: List[Dict[str, float]]) -> np.ndarray:
    return np.array([[p["x"], p["y"], p["z"]] for p in points], float)


def planform_wing(planform: Dict[str, Any]) -> Wing:
    """The flow5 wing of a `muas.planform`."""
    secs = tuple(Section(s["y"], s["chord"], s["x_offset"], s["dihedral_deg"], s["twist_deg"], s["foil"])
                 for s in planform["sections"])
    return Wing(planform["surface_name"], planform["kind"], tuple(planform["position"]["xyz"]), planform.get("rx_deg", 0.0),
                planform.get("ry_deg", 0.0), planform.get("symmetric", True), planform.get("two_sided", True), secs)


def _edges(wing: Wing) -> Tuple[np.ndarray, np.ndarray]:
    """Leading and trailing edge of each section, design frame (twist about the quarter chord, dihedral outboard)."""
    secs = wing.sections
    sy = np.array([s.y for s in secs])
    zd = np.concatenate([[0.0], np.cumsum(np.diff(sy) * np.tan(np.radians([s.dihedral_deg for s in secs[:-1]])))])
    le, te = [], []
    for s, z in zip(secs, zd):
        tw = math.radians(s.twist_deg)
        q = s.x_offset + PIVOT * s.chord
        le.append([q - PIVOT * s.chord * math.cos(tw), s.y, z + PIVOT * s.chord * math.sin(tw)])
        te.append([q + (1 - PIVOT) * s.chord * math.cos(tw), s.y, z - (1 - PIVOT) * s.chord * math.sin(tw)])
    return _wing_to_design(np.array(le), wing), _wing_to_design(np.array(te), wing)


def section_points(wing: Wing, foils: Dict[str, np.ndarray]) -> List[np.ndarray]:
    """The foil of each section in the design frame (the ADH airfoil sections placed by the planform rules)."""
    secs = wing.sections
    sy = np.array([s.y for s in secs])
    zd = np.concatenate([[0.0], np.cumsum(np.diff(sy) * np.tan(np.radians([s.dihedral_deg for s in secs[:-1]])))])
    out = []
    for s, z in zip(secs, zd):
        f = np.asarray(foils[s.foil], float)
        tw, c = math.radians(s.twist_deg), s.chord
        px, pz = (f[:, 0] - PIVOT) * c, f[:, 1] * c
        local = np.column_stack([s.x_offset + PIVOT * c + px * math.cos(tw) + pz * math.sin(tw), np.full(len(f), s.y),
                                 z - px * math.sin(tw) + pz * math.cos(tw)])
        out.append(_wing_to_design(local, wing))
    return out


def lifting_surface_adh(wing: Wing, foils: Dict[str, np.ndarray]) -> Dict[str, Any]:
    """The ADH `LiftingSurface` of a flow5 wing and its foils."""
    le, te = _edges(wing)
    deg = min(3, len(le) - 1)
    return {"leading_edge_spline": {"points": [_pt(p) for p in le], "degree": deg},
            "trailing_edge_spline": {"points": [_pt(p) for p in te], "degree": deg},
            "airfoil_sections": [{"spline": {"points": [_pt((x, 0.0, z)) for x, z in foils[s.foil]], "degree": 1}}
                                 for s in wing.sections]}


def foils_of(item: Dict[str, Any]) -> Dict[str, np.ndarray]:
    """Foil name -> normalised contour (n, 2) of an item with `muas.planform` and `geometry.lifting_surface`."""
    secs = item["muas"]["planform"]["sections"]
    afs = item["geometry"]["lifting_surface"]["airfoil_sections"]
    if len(secs) != len(afs):
        raise ValueError(f"{item['muas']['instance']}: {len(secs)} planform sections but {len(afs)} airfoil sections")
    out: Dict[str, np.ndarray] = {}
    for s, a in zip(secs, afs):
        c = _arr(a["spline"]["points"])[:, [0, 2]]
        if s["foil"] in out and not np.array_equal(out[s["foil"]], c):
            raise ValueError(f"{item['muas']['instance']}: foil {s['foil']} has two different contours")
        out[s["foil"]] = c
    return out


def planform_reference(planform: Dict[str, Any]) -> Dict[str, float]:
    """Planform area, span and mean aerodynamic chord of a symmetric surface (flat, sections along the span)."""
    y = np.array([s["y"] for s in planform["sections"]])
    c = np.array([s["chord"] for s in planform["sections"]])
    dy = np.diff(y)
    half = float(np.sum(dy * (c[:-1] + c[1:]) / 2))
    c2 = float(np.sum(dy * (c[:-1] ** 2 + c[:-1] * c[1:] + c[1:] ** 2) / 3))
    return {"area_m2": 2 * half, "span_m": 2 * float(y[-1]), "mac_m": c2 / half}


def surface_mesh(item: Dict[str, Any], x_over_c_max=1.0) -> np.ndarray:
    """Triangles of the right half of a lifting surface item (planform + foils)."""
    return lifting_surface(planform_wing(item["muas"]["planform"]), foils_of(item), x_over_c_max)


# ---------------------------------------------------------------------------------------------------------- bodies
def body_adh(frames: List[np.ndarray]) -> Dict[str, Any]:
    """The ADH `Body` of flow5 frames (each frame: the right-half points from the top to the bottom, design frame)."""
    xs = [float(f[0, 0]) for f in frames]
    x0, length = xs[0], xs[-1] - xs[0]
    if length <= 0:
        raise ValueError("body frames must run from the nose to the tail")
    secs = []
    for f in frames:
        k = min(max(int(np.argmax(f[:, 1])), 1), len(f) - 2)  # each ADH curve needs 2 points (a nose frame is one point)
        secs.append({"station": (float(f[0, 0]) - x0) / length,
                     "upper_curve": {"points": [_pt(p) for p in f[: k + 1]], "degree": 1},
                     "lower_curve": {"points": [_pt(p) for p in f[k:]], "degree": 1}})
    axis = [_pt((x, 0.0, float(np.mean(f[:, 2])))) for x, f in zip(xs, frames)]
    return {"reference_axis": {"points": axis, "degree": 1}, "cross_sections": secs}


def body_frames(body: Dict[str, Any]) -> List[np.ndarray]:
    """The frames of an ADH `Body` written by `body_adh`."""
    return [np.vstack([_arr(s["upper_curve"]["points"]), _arr(s["lower_curve"]["points"])[1:]])
            for s in body["cross_sections"]]


def body_mesh(body: Dict[str, Any]) -> np.ndarray:
    """A closed mesh of a body: each frame mirrored to a full ring, lofted from nose to tail."""
    from .visual import _loft

    rings = []
    for f in body_frames(body):
        mirror = f[::-1][1:-1] * np.array([1.0, -1.0, 1.0])
        rings.append(np.vstack([f, mirror]))
    n = {len(r) for r in rings}
    if len(n) != 1:
        raise ValueError("body frames need the same number of points to loft")
    return _loft(np.array(rings))


def distance_to_mesh(points: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """The distance from each point to the nearest point of a triangle mesh (closest point on each triangle)."""
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    ab, ac = b - a, c - a
    n = np.cross(ab, ac)
    nn = np.einsum("ij,ij->i", n, n)
    ok = nn > 1e-30
    a, b, c, ab, ac, n, nn = a[ok], b[ok], c[ok], ab[ok], ac[ok], n[ok], nn[ok]
    out = np.empty(len(points))
    for k, p in enumerate(np.asarray(points, float)):
        ap = p - a
        # inside the triangle: the distance to the plane
        t = np.einsum("ij,ij->i", ap, n) / nn
        q = p - t[:, None] * n
        v0, v1, v2 = ab, ac, q - a
        d00, d01, d11 = (np.einsum("ij,ij->i", v0, v0), np.einsum("ij,ij->i", v0, v1), np.einsum("ij,ij->i", v1, v1))
        d20, d21 = np.einsum("ij,ij->i", v2, v0), np.einsum("ij,ij->i", v2, v1)
        den = np.maximum(d00 * d11 - d01 * d01, 1e-300)
        v = (d11 * d20 - d01 * d21) / den
        w = (d00 * d21 - d01 * d20) / den
        inside = (v >= 0) & (w >= 0) & (v + w <= 1)
        best = np.min(np.abs(t[inside]) * np.sqrt(nn[inside])) if inside.any() else np.inf
        # else the nearest edge
        for e0, e1 in ((a, b), (b, c), (c, a)):
            d = e1 - e0
            s = np.clip(np.einsum("ij,ij->i", p - e0, d) / np.maximum(np.einsum("ij,ij->i", d, d), 1e-30), 0.0, 1.0)
            best = min(best, float(np.min(np.linalg.norm(e0 + s[:, None] * d - p, axis=1))))
        out[k] = best
    return out
