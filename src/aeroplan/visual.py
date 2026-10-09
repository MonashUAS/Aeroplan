"""Visual parts: CAD meshes in the design frame, for the glTF view of a `.muas` package (aeroplan.gltf).

Each part has a mesh, a transform into the design frame (`axes`, `origin_m`), an optional `hinge` (two points,
metres, design frame) and a `material`. A movable part (elevator, rudder, aileron_l, aileron_r) turns about its
hinge. The part `propeller` turns about the thrust axis through the hub.

AeroPlan writes each hinge into the glTF node extras, so the reader does not guess it. The hinge is a line through the front
edge of the movable mesh: the vertices in the front 10 % of its x extent, fitted with a least-squares line. It points
along +y (or +z for the rudder), so a positive turn about it moves the trailing edge down (or to the right).
Method: hand copy of Aerolink `visual/cad.front_edge_axis`.

Parts that the CAD does not hold come from other sources and say so in `source`:
  - `fin`: the flow5 Fin wing of the analysed plane XML, with its foil, cut at the rudder hinge.
  - `boom`: a tube from the aft end of the fuselage mesh to the elevator root quarter chord. Its diameter is a
    hand-config placeholder. The rule is the one of Aerolink 6f7edb7 `visual/airframe.py`.
"""
from __future__ import annotations

import math
import struct
from typing import Dict, Optional, Tuple

import numpy as np

from .adapters.flow5_geometry import Wing

UNIT_SCALE = {"m": 1.0, "mm": 1e-3, "cm": 1e-2, "in": 0.0254}
MOVABLE = ("elevator", "rudder", "aileron_l", "aileron_r")
PIVOT = 0.25                       # flow5 sections twist about the quarter chord
_STL = np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")])


def read_stl(data: bytes, name: str) -> np.ndarray:
    """Triangles (T, 3, 3) of a binary or ASCII STL, in file units."""
    count = int.from_bytes(data[80:84], "little") if len(data) >= 84 else -1
    if len(data) == 84 + 50 * count:
        return np.frombuffer(data, _STL, count=count, offset=84)["v"].astype(float)
    import re

    pts = re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)
    if not pts or len(pts) % 3:
        raise ValueError(f"{name} is not a readable STL file")
    return np.array([[float(c) for c in p] for p in pts]).reshape(-1, 3, 3)


def write_stl(tri: np.ndarray, header: str) -> bytes:
    """A binary STL of triangles (T, 3, 3) in metres. Deterministic bytes. Only for the OpenVSP reference mesh: the
    package uses glTF."""
    tri = np.asarray(tri, float)
    out = bytearray(header.encode("ascii", "replace")[:80].ljust(80, b" ")) + struct.pack("<I", len(tri))
    for t in tri:
        n = np.cross(t[1] - t[0], t[2] - t[0])
        ln = np.linalg.norm(n)
        n = n / ln if ln > 0 else n
        out += struct.pack("<12fH", *n, *t.ravel(), 0)
    return bytes(out)


def to_design(tri: np.ndarray, units: str, transform: Optional[dict]) -> np.ndarray:
    """Scale to metres, map the axes, subtract origin_m. Same rule as the Aerolink reader."""
    pts = tri.reshape(-1, 3) * UNIT_SCALE[units]
    t = transform or {}
    cols = []
    for a in t.get("axes", ["x", "y", "z"]):
        cols.append((-1.0 if a.startswith("-") else 1.0) * pts[:, "xyz".index(a.lstrip("-"))])
    pts = np.column_stack(cols) - np.array(t.get("origin_m", [0.0, 0.0, 0.0]), float)
    return pts.reshape(-1, 3, 3)


def front_edge_axis(tri: np.ndarray, vertical: bool, band: float = 0.1) -> Tuple[np.ndarray, np.ndarray]:
    """Hinge axis of a control surface: a line through the front edge (the lowest 10 % of x)."""
    v = np.unique(np.round(tri.reshape(-1, 3), 6), axis=0)
    sel = v[v[:, 0] <= v[:, 0].min() + band * np.ptp(v[:, 0])]
    c = sel.mean(axis=0)
    d = np.linalg.svd(sel - c)[2][0]
    d = d if d[2 if vertical else 1] > 0 else -d
    t = (sel - c) @ d
    return c + t.min() * d, c + t.max() * d


def bounds(tri: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    p = tri.reshape(-1, 3)
    return p.min(axis=0), p.max(axis=0)


# ---------------------------------------------------------------------------------------------------------- generated parts
def _foil_surfaces(foil: np.ndarray, xs: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Upper and lower ordinates of a Selig-ordered foil at the chord fractions xs."""
    i = int(np.argmin(foil[:, 0]))
    up, lo = foil[: i + 1][::-1], foil[i:]
    return np.interp(xs, up[:, 0], up[:, 1]), np.interp(xs, lo[:, 0], lo[:, 1])


def _wing_to_design(points: np.ndarray, wing: Wing) -> np.ndarray:
    """Local wing coordinates to the design frame: Rx (about -x), then Ry (nose up), then the root position."""
    rx, ry = -math.radians(wing.rx_deg), math.radians(wing.ry_deg)
    rot_x = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    p = (rot_x @ points.T).T
    c, s = math.cos(ry), math.sin(ry)
    p = np.column_stack([p[:, 0] * c + p[:, 2] * s, p[:, 1], -p[:, 0] * s + p[:, 2] * c])
    return p + np.array(wing.position)


def lifting_surface(wing: Wing, foils: Dict[str, np.ndarray], x_over_c_max=1.0, n_chord: int = 24,
                    n_span: int = 8, x_over_c_min: float = 0.0, y_range=None) -> np.ndarray:
    """A closed solid of the right half of a flow5 wing, from `x_over_c_min` to `x_over_c_max` of the chord.

    `x_over_c_max` is a number, or a function f(y, le_x, chord) of the local span station, the design-frame x of the
    leading edge and the chord (a cut along a hinge line). `y_range` (lo, hi) limits the span (a control surface).
    """
    xs1 = (1 - np.cos(np.linspace(0, np.pi, n_chord))) / 2
    secs = wing.sections
    sy = np.array([s.y for s in secs])
    zd = np.concatenate([[0.0], np.cumsum(np.diff(sy) * np.tan(np.radians([s.dihedral_deg for s in secs[:-1]])))])
    lo, hi = y_range if y_range is not None else (sy[0], sy[-1])
    ys = np.unique(np.concatenate([np.linspace(max(a, lo), min(b, hi), n_span)
                                   for a, b in zip(sy[:-1], sy[1:]) if min(b, hi) > max(a, lo)]))
    rings = []
    for y in ys:
        k = int(min(max(np.searchsorted(sy, y, side="right") - 1, 0), len(secs) - 2))
        t = (y - sy[k]) / (sy[k + 1] - sy[k])
        a, b = secs[k], secs[k + 1]
        chord, xo = a.chord + t * (b.chord - a.chord), a.x_offset + t * (b.x_offset - a.x_offset)
        le_x = float(_wing_to_design(np.array([[xo, y, 0.0]]), wing)[0, 0])
        cut = x_over_c_max(y, le_x, chord) if callable(x_over_c_max) else x_over_c_max
        if not x_over_c_min < cut <= 1:
            raise ValueError(f"wing {wing.name}: the cut at y {y:.3f} m is {cut:.3f} of the chord")
        xs = x_over_c_min + xs1 * (cut - x_over_c_min)
        tw = math.radians(a.twist_deg + t * (b.twist_deg - a.twist_deg))
        ua, la = _foil_surfaces(foils[a.foil], xs)
        ub, lb = _foil_surfaces(foils[b.foil], xs)
        up, lo = ua + t * (ub - ua), la + t * (lb - la)
        rx = np.concatenate([xs[::-1], xs[1:]])
        rz = np.concatenate([up[::-1], lo[1:]])
        px, pz = (rx - PIVOT) * chord, rz * chord
        pts = np.column_stack([xo + PIVOT * chord + px * math.cos(tw) + pz * math.sin(tw), np.full_like(px, y),
                               zd[k] + t * (zd[k + 1] - zd[k]) - px * math.sin(tw) + pz * math.cos(tw)])
        rings.append(_wing_to_design(pts, wing))
    return _loft(np.array(rings))


def mirror_y(tri: np.ndarray) -> np.ndarray:
    """The mirror image of triangles about the y = 0 plane (winding reversed, so the normals point out)."""
    return (np.asarray(tri) * np.array([1.0, -1.0, 1.0]))[:, ::-1]


def _loft(rings: np.ndarray) -> np.ndarray:
    """Triangles of a closed solid through rings (stations, points, 3), with flat end caps."""
    n_st, n_pt = rings.shape[:2]
    tri = []
    for i in range(n_st - 1):
        for j in range(n_pt):
            a, b = rings[i, j], rings[i, (j + 1) % n_pt]
            c, d = rings[i + 1, j], rings[i + 1, (j + 1) % n_pt]
            tri += [(a, b, d), (a, d, c)]
    for ring, flip in ((rings[0], True), (rings[-1], False)):
        c = ring.mean(axis=0)
        for j in range(n_pt):
            a, b = ring[j], ring[(j + 1) % n_pt]
            tri.append((c, b, a) if flip else (c, a, b))
    return np.array(tri)


def tube(p0: np.ndarray, p1: np.ndarray, radius: float, sides: int = 16) -> np.ndarray:
    """A closed round tube from p0 to p1."""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    ax = (p1 - p0) / np.linalg.norm(p1 - p0)
    u = np.cross(ax, [0.0, 0.0, 1.0] if abs(ax[2]) < 0.9 else [0.0, 1.0, 0.0])
    u /= np.linalg.norm(u)
    v = np.cross(ax, u)
    ang = np.linspace(0, 2 * np.pi, sides, endpoint=False)
    ring = np.outer(np.cos(ang), u) + np.outer(np.sin(ang), v)
    return _loft(np.array([p0 + radius * ring, p1 + radius * ring]))
