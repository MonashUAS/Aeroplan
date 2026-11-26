"""Shape helpers between the ADH geometry classes and the tool shapes (flow5 wings and bodies, meshes).

ADH forms used (upstream airframe_geometry.py):
  - `LiftingSurface`: leading_edge_spline and trailing_edge_spline (one point per section, design frame FRD, m) and
    airfoil_sections (one `Airfoil` per section, root first, named by `muas.lifting_surface.foils`). An airfoil spline
    holds the normalised foil contour: x = x/c, y = 0, z = z/c (Selig order: upper surface from the trailing edge to the
    leading edge, then the lower surface back to the trailing edge), degree 1. It is the only stored shape of a
    lifting surface (ADR 0027). The planform (the tool section form, flow5 convention, degrees) is made from it in
    memory: `planform_of`. A spoke stores a planform with `set_planform`.
  - `Body`: reference_axis (the body axis, design frame) and cross_sections. A cross section holds one flow5 frame:
    station = (x_nose - x) / length (x falls from the nose to the tail), upper_curve = the frame points from the top to the widest point, lower_curve =
    the widest point to the bottom. A frame that is one point (nose, tail) splits after its second point (right half, design frame, m).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

import numpy as np

from .frame import flip_array
from .visual import PIVOT, _wing_to_design, lifting_surface
from .wing import Section, Wing


def _pt(p) -> Dict[str, float]:
    return {"x": float(p[0]), "y": float(p[1]), "z": float(p[2])}


def _arr(points: List[Dict[str, float]]) -> np.ndarray:
    return np.array([[p["x"], p["y"], p["z"]] for p in points], float)


def planform_wing(planform: Dict[str, Any]) -> Wing:
    """The flow5 wing of a planform (`planform_of`)."""
    secs = tuple(Section(s["y"], s["chord"], s["x_offset"], s["dihedral_deg"], s["twist_deg"], s["foil"])
                 for s in planform["sections"])
    return Wing(planform["surface_name"], planform["kind"], tuple(planform["position"]["xyz"]), planform.get("rx_deg", 0.0),
                planform.get("ry_deg", 0.0), planform.get("symmetric", True), planform.get("two_sided", True), secs)


def _edges(wing: Wing) -> Tuple[np.ndarray, np.ndarray]:
    """Leading and trailing edge of each section, design frame (twist about the quarter chord, dihedral outboard)."""
    secs = wing.sections
    zd = np.array(wing.section_z())
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
    zd = np.array(wing.section_z())
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
    """Foil name -> normalised contour (n, 2) of an item with `muas.lifting_surface` and `geometry.lifting_surface`."""
    names = item["muas"]["lifting_surface"]["foils"]
    afs = item["geometry"]["lifting_surface"]["airfoil_sections"]
    if len(names) != len(afs):
        raise ValueError(f"{item['muas']['instance']}: {len(names)} foil names but {len(afs)} airfoil sections")
    out: Dict[str, np.ndarray] = {}
    for name, a in zip(names, afs):
        c = _arr(a["spline"]["points"])[:, [0, 2]]
        if name in out and not np.array_equal(out[name], c):
            raise ValueError(f"{item['muas']['instance']}: foil {name} has two different contours")
        out[name] = c
    return out


def _design_to_wing(points: np.ndarray, position, rx_deg: float, ry_deg: float) -> np.ndarray:
    """The reverse of visual._wing_to_design: design frame (FRD) to the local section frame (x aft, y right, z up)."""
    p = flip_array(np.asarray(points, float) - np.array(position, float))
    c, s = math.cos(math.radians(ry_deg)), math.sin(math.radians(ry_deg))
    p = np.column_stack([p[:, 0] * c - p[:, 2] * s, p[:, 1], p[:, 0] * s + p[:, 2] * c])
    rx = -math.radians(rx_deg)
    rot_x = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    return (rot_x.T @ p.T).T


def has_planform(item: Dict[str, Any]) -> bool:
    """True when the item is a lifting surface with a section frame (`muas.lifting_surface`)."""
    return bool((item.get("muas") or {}).get("lifting_surface")) and "lifting_surface" in (item.get("geometry") or {})


def planform_of(item: Dict[str, Any]) -> Dict[str, Any]:
    """The planform of a lifting surface item: the tool section form (flow5 convention, lengths in m, angles in deg),
    made from the ADH `geometry.lifting_surface` and the section frame of `muas.lifting_surface`. The reverse of
    `_edges`: the chord and the twist come from the leading edge to trailing edge vector, the x offset and the dihedral
    from the quarter-chord line. The tip section has no outboard panel: it gets the dihedral of the last panel."""
    ext = item["muas"]["lifting_surface"]
    ls = item["geometry"]["lifting_surface"]
    pos, rx, ry = list(ext["position"]["xyz"]), math.degrees(ext.get("rx", 0.0)), math.degrees(ext.get("ry", 0.0))
    le = _design_to_wing(_arr(ls["leading_edge_spline"]["points"]), pos, rx, ry)
    te = _design_to_wing(_arr(ls["trailing_edge_spline"]["points"]), pos, rx, ry)
    if not len(le) == len(te) == len(ext["foils"]):
        raise ValueError(f"{item['muas']['instance']}: {len(le)} leading edge points, {len(te)} trailing edge points "
                         f"and {len(ext['foils'])} foil names")
    d = te - le
    chord = np.hypot(d[:, 0], d[:, 2])
    tw = np.arctan2(-d[:, 2], d[:, 0])
    x_off = le[:, 0] + PIVOT * chord * np.cos(tw) - PIVOT * chord
    zd = le[:, 2] - PIVOT * chord * np.sin(tw)
    dih = np.degrees(np.arctan2(np.diff(zd), np.diff(le[:, 1])))
    dih = np.append(dih, dih[-1])
    pf = {"surface_name": ext["surface_name"], "kind": ext["kind"], "position": {"xyz": pos}, "rx_deg": rx, "ry_deg": ry,
          "symmetric": ext.get("symmetric", True), "two_sided": ext.get("two_sided", True),
          "sections": [{"y": float(le[i, 1]), "chord": float(chord[i]), "x_offset": float(x_off[i]),
                        "dihedral_deg": float(dih[i]), "twist_deg": math.degrees(tw[i]), "foil": ext["foils"][i]}
                       for i in range(len(le))],
          "source": ext["source"], "placeholder": ext.get("placeholder", False)}
    if ext.get("structural_mass"):
        pf["structural_mass"] = ext["structural_mass"]
    return pf


def set_planform(item: Dict[str, Any], planform: Dict[str, Any], foils: Dict[str, np.ndarray]) -> None:
    """Store a planform (the tool section form) on a lifting surface item: the shape as the ADH
    `geometry.lifting_surface`, the section frame and the tool facts as `muas.lifting_surface`."""
    ys = [s["y"] for s in planform["sections"]]
    if len(ys) < 2 or any(b <= a for a, b in zip(ys, ys[1:])):
        raise ValueError(f"{planform['surface_name']}: a planform needs 2 sections or more, and y must rise from root to tip")
    item.setdefault("geometry", {})["lifting_surface"] = lifting_surface_adh(planform_wing(planform), foils)
    ext = {"surface_name": planform["surface_name"], "kind": planform["kind"],
           "position": {"frame": "design", "xyz": [float(v) for v in planform["position"]["xyz"]], "units": "m"},
           "rx": math.radians(planform.get("rx_deg", 0.0)), "ry": math.radians(planform.get("ry_deg", 0.0)),
           "symmetric": planform.get("symmetric", True), "two_sided": planform.get("two_sided", True),
           "foils": [s["foil"] for s in planform["sections"]], "source": planform["source"],
           "placeholder": planform.get("placeholder", False)}
    if planform.get("structural_mass"):
        ext["structural_mass"] = planform["structural_mass"]
    item["muas"]["lifting_surface"] = ext


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
    return lifting_surface(planform_wing(planform_of(item)), foils_of(item), x_over_c_max)


# ---------------------------------------------------------------------------------------------------------- bodies
def body_adh(frames: List[np.ndarray]) -> Dict[str, Any]:
    """The ADH `Body` of flow5 frames (each frame: the right-half points from the top to the bottom, design frame)."""
    xs = [float(f[0, 0]) for f in frames]
    x0, length = xs[0], xs[0] - xs[-1]
    if length <= 0:
        raise ValueError("body frames must run from the nose to the tail (x falls, FRD)")
    secs = []
    for f in frames:
        k = min(max(int(np.argmax(f[:, 1])), 1), len(f) - 2)  # each ADH curve needs 2 points (a nose frame is one point)
        secs.append({"station": (x0 - float(f[0, 0])) / length,
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
