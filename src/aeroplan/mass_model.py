"""The mass model: point masses -> mass, CG and inertia. Design frame (x aft, y right, z up), SI.

Only numpy. A point mass has no inertia of its own, so the inertia is the parallel-axis sum.
Product convention of `muas.mass`: Ixy = +sum(m x y).
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

import numpy as np


def _arrays(point_masses: Sequence[Dict[str, Any]]):
    m = np.array([float(p["mass_kg"]) for p in point_masses])
    r = np.array([list(map(float, p["xyz"])) for p in point_masses]).reshape(-1, 3)
    return m, r


def rollup(point_masses: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Mass, CG and inertia about the CG of point masses {mass_kg, xyz}. Axes are parallel to the design frame."""
    m, r = _arrays(point_masses)
    if len(m) == 0 or m.sum() <= 0:
        raise ValueError("the mass model has no mass")
    total = float(m.sum())
    cg = (m[:, None] * r).sum(axis=0) / total
    d = r - cg
    x, y, z = d[:, 0], d[:, 1], d[:, 2]
    inertia = {"ixx": float((m * (y ** 2 + z ** 2)).sum()), "iyy": float((m * (x ** 2 + z ** 2)).sum()),
               "izz": float((m * (x ** 2 + y ** 2)).sum()), "ixy": float((m * x * y).sum()),
               "ixz": float((m * x * z).sum()), "iyz": float((m * y * z).sum())}
    return {"mass_kg": total, "cg": [float(v) for v in cg], "inertia": inertia}


def distribute_on_planform(mass_kg: float, planform: Dict[str, Any], n: int, x_cg: float) -> List[Dict[str, Any]]:
    """Spread a mass over a lifting surface in n strips on each side, in proportion to the strip area, then move
    every strip in x so that the CG of the group is x_cg. Gives {mass_kg, xyz} for each strip."""
    from .geometry import _edges, planform_wing

    wing = planform_wing(planform)
    le, te = _edges(wing)
    # parameter along the sections: the span coordinate of the design-frame edge points
    t_sec = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(le, axis=0), axis=1))])
    edges = np.linspace(0.0, t_sec[-1], n + 1)
    mid_t = 0.5 * (edges[:-1] + edges[1:])
    dt = np.diff(edges)
    interp = lambda a: np.stack([np.interp(mid_t, t_sec, a[:, k]) for k in range(3)], axis=1)
    mid_le, mid_te = interp(le), interp(te)
    chord = np.linalg.norm(mid_te - mid_le, axis=1)
    centre = 0.5 * (mid_le + mid_te)
    area = chord * dt
    mirror = bool(wing.symmetric) and (wing.kind != "FIN" or bool(wing.two_sided))
    pts, w = [centre], [area]
    if mirror:
        flip = centre * np.array([1.0, -1.0, 1.0])
        pts.append(flip)
        w.append(area)
    pts, w = np.concatenate(pts), np.concatenate(w)
    m = mass_kg * w / w.sum()
    pts[:, 0] += x_cg - float((m * pts[:, 0]).sum() / m.sum())
    return [{"mass_kg": float(mi), "xyz": [float(v) for v in p]} for mi, p in zip(m, pts)]
