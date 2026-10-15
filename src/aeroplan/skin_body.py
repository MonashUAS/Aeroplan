"""Flow5-style body frames from a closed outer skin mesh (the Creo shrinkwrap of the fuselage).

A frame is the right half of the skin in a plane x = constant, from the top point to the bottom point (design frame,
m). That is the form of `geometry.body_adh`. The slice casts rays from the centre of the pod and keeps the farthest
hit of each ray.

The shrinkwrap also holds the centre panel of the wing. A `cut` removes it: in the stations from x0 to x1, a ray
that hits the skin at |y| above `y_max_m` is a wing hit. The frame takes the point of that ray from a straight line
between the nearest good rays (the pod outline).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

METHOD = "skin_body.slice_frames v2: rays from the pod centre in axis-normalised (y, z), farthest hit, monotone envelope, thin tail end left out"
END_STEP = 0.005     # m: the first and last real frames sit this far inside the ends (the flow5 body has 5 mm)


def _slice_segments(tri: np.ndarray, x: float) -> np.ndarray:
    """Segments (n, 2, 2) in (y, z) of the mesh in the plane x = const."""
    d = tri[:, :, 0] - (x + 1e-9)
    cross = (d.min(axis=1) < 0) & (d.max(axis=1) > 0)
    t, dd = tri[cross], d[cross]
    pts = np.full((len(t), 3, 2), np.nan)
    for e, (i, j) in enumerate(((0, 1), (1, 2), (2, 0))):
        hit = dd[:, i] * dd[:, j] < 0
        w = dd[hit, i] / (dd[hit, i] - dd[hit, j])
        pts[hit, e] = (t[hit, i] + w[:, None] * (t[hit, j] - t[hit, i]))[:, 1:]
    out = np.empty((len(t), 2, 2))
    for k in range(len(t)):
        out[k] = pts[k][~np.isnan(pts[k, :, 0])][:2]
    return out


def _farthest_hits(segs: np.ndarray, centre: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Farthest hit (y, z) of each ray from `centre`; the ray angle is measured from +z toward +y."""
    p, q = segs[:, 0], segs[:, 1]
    e = q - p
    out = np.full((len(theta), 2), np.nan)
    for k, th in enumerate(theta):
        d = np.array([np.sin(th), np.cos(th)])
        den = d[0] * e[:, 1] - d[1] * e[:, 0]
        ok = np.abs(den) > 1e-14
        w = p - centre
        t = np.full(len(p), -1.0)
        s = np.full(len(p), -1.0)
        t[ok] = (w[ok, 0] * e[ok, 1] - w[ok, 1] * e[ok, 0]) / den[ok]
        s[ok] = (w[ok, 0] * d[1] - w[ok, 1] * d[0]) / den[ok]
        good = ok & (t > 0) & (s >= -1e-9) & (s <= 1 + 1e-9)
        if good.any():
            out[k] = centre + t[good].max() * d
    miss = np.isnan(out[:, 0])
    if miss.any():
        # a thin or ragged section (the tail end of a shrinkwrap): take the segment end point nearest in angle
        pts = segs.reshape(-1, 2)
        rel = pts - centre
        ang = np.arctan2(rel[:, 0], rel[:, 1])
        for k in np.flatnonzero(miss):
            diff = np.abs(ang - theta[k])
            near = diff <= diff.min() + 1e-3
            out[k] = pts[near][np.argmax(np.linalg.norm(rel[near], axis=1))]
    return out


def slice_frame(tri: np.ndarray, x: float, n_points: int, cut: Optional[Dict[str, Any]] = None) -> np.ndarray:
    """One frame (n_points, 3): the right half of the skin at x, top to bottom."""
    segs = _slice_segments(tri, x)
    if len(segs) == 0:
        raise ValueError(f"the skin has no section at x = {x:.4f} m")
    in_cut = bool(cut) and cut["x_m"][0] <= x <= cut["x_m"][1]
    y_max = float(cut["y_max_m"]) if in_cut else np.inf
    pts = segs.reshape(-1, 2)
    keep = pts[np.abs(pts[:, 0]) <= y_max]
    zc = 0.5 * (keep[:, 1].min() + keep[:, 1].max())
    # rays in axis-normalised coordinates: a flat section (the tail end of the shrinkwrap) still gets a spread of points
    scale = np.array([max(float(np.abs(keep[:, 0]).max()), 1e-4), max(0.5 * float(np.ptp(keep[:, 1])), 1e-4)])
    origin = np.array([0.0, zc])
    theta = np.linspace(0.0, np.pi, n_points)
    hit = _farthest_hits((segs - origin) / scale, np.zeros(2), theta) * scale + origin
    if np.isnan(hit).any():
        raise ValueError(f"the skin is not closed at x = {x:.4f} m: a ray at {np.degrees(theta[np.isnan(hit[:, 0])])} deg "
                         "has no hit")
    if in_cut:
        bad = np.abs(hit[:, 0]) > y_max
        bad[0] = bad[-1] = False
        if bad.all():
            raise ValueError(f"the cut removes the whole frame at x = {x:.4f} m")
        idx = np.arange(n_points)
        for c in (0, 1):
            hit[bad, c] = np.interp(idx[bad], idx[~bad], hit[~bad, c])
    y, z = _monotone(np.maximum(hit[:, 0], 0.0), hit[:, 1])
    return np.column_stack([np.full(n_points, x), y, z])


def _monotone(y: np.ndarray, z: np.ndarray):
    """A frame of a faired body: y rises to the widest point and falls again, z falls from the top to the bottom.
    A ragged section (the thin tail end of a shrinkwrap) breaks this. The envelope changes only the points that break it."""
    k = int(np.argmax(y))
    y = y.copy()
    y[: k + 1] = np.maximum.accumulate(y[: k + 1])
    y[k:] = np.maximum.accumulate(y[k:][::-1])[::-1]
    return y, np.minimum.accumulate(z)


def _end_x(tri: np.ndarray, x1: float, min_height: float) -> float:
    """The aft x where the section is at least `min_height` tall (1 mm steps from the tail end forward)."""
    x = x1 - 1e-3
    while x > x1 - 0.2:
        segs = _slice_segments(tri, x)
        if len(segs) and float(np.ptp(segs[:, :, 1])) >= min_height:
            return x
        x -= 1e-3
    raise ValueError(f"no section of the last 0.2 m of the skin is {min_height} m tall")


def slice_frames(tri: np.ndarray, n_frames: int, n_points: int, cut: Optional[Dict[str, Any]] = None,
                 min_height: float = 0.0) -> List[np.ndarray]:
    """`n_frames` frames from the nose to the tail. The first and last frame are one point (the centre of the end).
    The stations between them use cosine spacing, so the nose and the tail get more frames. A thin tail end (a sheet
    thinner than `min_height`, which no frame can describe) is left out: the body closes at the aft station that is
    `min_height` tall, plus END_STEP."""
    v = tri.reshape(-1, 3)
    x0, x1 = float(v[:, 0].min()), float(v[:, 0].max())
    if n_frames < 5:
        raise ValueError("a body needs at least 5 frames")
    last = _end_x(tri, x1, min_height) if min_height > 0 else x1 - END_STEP
    a, b = x0 + END_STEP, last
    inner = a + (b - a) * 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, n_frames - 2)))
    frames = [slice_frame(tri, float(x), n_points, cut) for x in inner]
    for x, ref in ((x0, frames[0]), (last + END_STEP if min_height > 0 else x1, frames[-1])):
        z = float(0.5 * (ref[:, 2].min() + ref[:, 2].max()))
        point = np.column_stack([np.full(n_points, x), np.zeros(n_points), np.full(n_points, z)])
        frames.insert(0 if x == x0 else len(frames), point)
    return frames


def mesh_volume(tri: np.ndarray) -> float:
    return float(abs(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum()) / 6.0)


def fit_report(frames: List[np.ndarray], tri: np.ndarray, cut: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """Gap from the skin vertices to the body mesh (largest, RMS), volume of both. Vertices of the wing panel
    (|y| above y_max_m inside the cut stations) and of the tail end aft of the body are left out. Gaps in metres, volumes in m3."""
    from .geometry import distance_to_mesh

    body = _ring_mesh(frames)
    v = np.unique(tri.reshape(-1, 3).round(6), axis=0)
    if cut:
        panel = (v[:, 0] >= cut["x_m"][0]) & (v[:, 0] <= cut["x_m"][1]) & (np.abs(v[:, 1]) > cut["y_max_m"])
        v = v[~panel]
    v = v[v[:, 0] <= frames[-1][0, 0]]     # the thin tail end that the body leaves out
    v = v[np.random.default_rng(0).choice(len(v), min(len(v), 600), replace=False)]
    d = distance_to_mesh(v, body)
    return {"largest_gap_m": float(d.max()), "rms_gap_m": float(np.sqrt(np.mean(d ** 2))),
            "body_volume_m3": mesh_volume(body), "skin_volume_m3": mesh_volume(tri)}


def _ring_mesh(frames: List[np.ndarray]) -> np.ndarray:
    from .visual import _loft

    rings = [np.vstack([f, f[::-1][1:-1] * np.array([1.0, -1.0, 1.0])]) for f in frames]
    return _loft(np.array(rings))


def drop_slivers(tri: np.ndarray, area_tol: float = 1e-5, decimals: int = 7):
    """Repair a closed triangle mesh for the panel solver of VSPAERO, which needs every edge to have 1 or 2 triangles.
    The Creo shrinkwrap holds small flaps of zero-area triangles that touch the surface along an edge (an edge of 4
    triangles). The flaps are the connected parts (joined across edges of exactly 2 triangles) of total area below
    `area_tol` (m2) that have an edge with more than 2 triangles. They are removed. Returns (triangles, number removed)."""
    v = np.asarray(tri, float).reshape(-1, 3)
    ids: Dict[tuple, int] = {}
    idx = np.array([ids.setdefault(tuple(p), len(ids)) for p in v.round(decimals)]).reshape(-1, 3)
    edge_tris: Dict[tuple, list] = {}
    for k, t in enumerate(idx):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            edge_tris.setdefault((min(a, b), max(a, b)), []).append(k)
    parent = list(range(len(idx)))

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for ts in edge_tris.values():
        if len(ts) == 2:
            parent[find(ts[0])] = find(ts[1])
    tri3 = v.reshape(-1, 3, 3)
    area = 0.5 * np.linalg.norm(np.cross(tri3[:, 1] - tri3[:, 0], tri3[:, 2] - tri3[:, 0]), axis=1)
    total: Dict[int, float] = {}
    for k in range(len(idx)):
        total[find(k)] = total.get(find(k), 0.0) + float(area[k])
    touch = {find(k) for ts in edge_tris.values() if len(ts) > 2 for k in ts}
    drop = {c for c in touch if total[c] < area_tol}
    keep = np.array([find(k) not in drop for k in range(len(idx))])
    return tri3[keep], int((~keep).sum())


def split_needles(tri: np.ndarray, collinear_tol: float = 1e-9, decimals: int = 7, max_pass: int = 20):
    """Remove the needle triangles (three collinear points) of a closed mesh and keep it closed. The neighbour across
    the long edge of a needle is split at the middle point. Returns (triangles, number of needles removed)."""
    v = np.asarray(tri, float).reshape(-1, 3)
    ids: Dict[tuple, int] = {}
    tris = [tuple(ids.setdefault(tuple(p), len(ids)) for p in v[3 * k: 3 * k + 3].round(decimals)) for k in range(len(v) // 3)]
    pts = np.array(list(ids), float)
    removed = 0
    for _ in range(max_pass):
        def dist(p, a, b):
            d = pts[b] - pts[a]
            return float(np.linalg.norm(np.cross(pts[p] - pts[a], d)) / max(np.linalg.norm(d), 1e-30))

        needles = []
        for k, t in enumerate(tris):
            if len(set(t)) < 3:
                needles.append((k, None))
                continue
            for i in range(3):
                a, b, c = t[i], t[(i + 1) % 3], t[(i + 2) % 3]      # c is the candidate middle point of the edge (a, b)
                if dist(c, a, b) < collinear_tol and np.dot(pts[c] - pts[a], pts[c] - pts[b]) < 0:
                    needles.append((k, (a, b, c)))
                    break
            else:
                if dist(t[0], t[1], t[2]) < collinear_tol:
                    needles.append((k, None))
        if not needles:
            break
        drop, add = set(), []
        edge_owner: Dict[tuple, list] = {}
        for k, t in enumerate(tris):
            for i in range(3):
                edge_owner.setdefault(frozenset((t[i], t[(i + 1) % 3])), []).append(k)
        needle_ids = {k for k, _ in needles}
        for k, info in needles:
            if k in drop:
                continue
            if info is not None:
                nb = [j for j in edge_owner[frozenset(info[:2])] if j != k]
                if any(j in needle_ids and j < k for j in nb):
                    continue                        # the lower needle goes first (it splits this one), then the next pass
            drop.add(k)
            removed += 1
            if info is None:
                continue
            a, b, c = info
            for j in edge_owner[frozenset((a, b))]:
                if j == k or j in drop:
                    continue
                t = tris[j]
                for i in range(3):
                    if {t[i], t[(i + 1) % 3]} == {a, b}:
                        u, w, p = t[i], t[(i + 1) % 3], t[(i + 2) % 3]      # keeps the orientation of the neighbour
                        add += [(u, c, p), (c, w, p)]
                        drop.add(j)
                        break
        tris = [t for k, t in enumerate(tris) if k not in drop] + add
    return pts[np.array(tris)], removed


def heal_tjunctions(tri: np.ndarray, tol: float = 1e-9, decimals: int = 7, max_pass: int = 20):
    """Close the T-junctions of a mesh: a boundary edge that has other boundary vertices on it gets its triangle split in
    a fan through those vertices, so the edges match. Returns (triangles, number of triangles split)."""
    v = np.asarray(tri, float).reshape(-1, 3)
    ids: Dict[tuple, int] = {}
    tris = [tuple(ids.setdefault(tuple(p), len(ids)) for p in v[3 * k: 3 * k + 3].round(decimals)) for k in range(len(v) // 3)]
    pts = np.array(list(ids), float)
    split = 0
    for _ in range(max_pass):
        count: Dict[frozenset, list] = {}
        for k, t in enumerate(tris):
            for i in range(3):
                count.setdefault(frozenset((t[i], t[(i + 1) % 3])), []).append(k)
        boundary = [e for e, ts in count.items() if len(ts) == 1]
        if not boundary:
            break
        bverts = sorted({a for e in boundary for a in e})
        bpts = pts[bverts]
        drop, add = set(), []
        for e in boundary:
            a, b = tuple(e)
            d = pts[b] - pts[a]
            L2 = float(d @ d)
            s = ((bpts - pts[a]) @ d) / L2
            off = np.linalg.norm(bpts - (pts[a] + s[:, None] * d), axis=1)
            on = [bverts[i] for i in np.flatnonzero((off < tol) & (s > 1e-6) & (s < 1 - 1e-6))]
            if not on:
                continue
            k = count[e][0]
            if k in drop:
                continue
            t = tris[k]
            for i in range(3):
                if {t[i], t[(i + 1) % 3]} == {a, b}:
                    u, w, p = t[i], t[(i + 1) % 3], t[(i + 2) % 3]
                    order = sorted(on, key=lambda q: float((pts[q] - pts[u]) @ (pts[w] - pts[u])))
                    chain = [u] + order + [w]
                    add += [(chain[j], chain[j + 1], p) for j in range(len(chain) - 1)]
                    drop.add(k)
                    split += 1
                    break
        if not drop:
            break
        tris = [t for k, t in enumerate(tris) if k not in drop] + add
    return pts[np.array(tris)], split


def repair_for_panel(tri: np.ndarray):
    """The three repairs that make a CAD shrinkwrap a valid panel mesh for VSPAERO (every edge has 2 triangles): remove the
    zero-area flaps on 4-triangle edges, remove the collinear needle triangles, close the T-junctions that follow.
    Returns (triangles, {"flap_triangles", "needles", "tjunction_splits"})."""
    out, flaps = drop_slivers(tri)
    out, needles = split_needles(out)
    out, splits = heal_tjunctions(out)
    return out, {"flap_triangles": flaps, "needles": needles, "tjunction_splits": splits}

