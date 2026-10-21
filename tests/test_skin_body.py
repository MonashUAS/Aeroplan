"""Body frames from a skin mesh: synthetic ellipsoid (semi-axes a, b, c) with an optional box that stands for a wing."""
import numpy as np
import pytest

from aeroplan.skin_body import fit_report, mesh_volume, slice_frame, slice_frames

A, B, C = 0.6, 0.1, 0.07


def ellipsoid(n_u=60, n_v=40):
    u = np.linspace(0, np.pi, n_u)
    v = np.linspace(0, 2 * np.pi, n_v, endpoint=False)
    p = np.array([[[A * np.cos(a), B * np.sin(a) * np.cos(b), C * np.sin(a) * np.sin(b)] for b in v] for a in u])
    tri = []
    for i in range(n_u - 1):
        for j in range(n_v):
            k = (j + 1) % n_v
            tri.append([p[i, j], p[i + 1, j], p[i + 1, k]])
            tri.append([p[i, j], p[i + 1, k], p[i, k]])
    return np.array(tri)


def box(x0, x1, y0, y1, z0, z1):
    c = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return np.array([t for f in faces for t in ([c[f[0]], c[f[1]], c[f[2]]], [c[f[0]], c[f[2]], c[f[3]]])])


def test_frame_lies_on_the_ellipsoid():
    f = slice_frame(ellipsoid(), 0.2, 37)
    r = np.sqrt(1 - (0.2 / A) ** 2)
    assert f.shape == (37, 3)
    assert np.allclose(f[:, 0], 0.2)
    # every point is on the ellipse (within the facet error)
    assert np.abs((f[:, 1] / (B * r)) ** 2 + (f[:, 2] / (C * r)) ** 2 - 1).max() < 0.02
    assert f[0, 2] < 0 < f[-1, 2]            # top to bottom (z down)
    assert (f[:, 1] >= 0).all()


def test_frames_nose_and_tail_are_points():
    fr = slice_frames(ellipsoid(), 15, 25)
    assert len(fr) == 15 and all(f.shape == (25, 3) for f in fr)
    assert np.ptp(fr[0][:, 1]) == 0 and np.ptp(fr[0][:, 2]) == 0
    assert np.ptp(fr[-1][:, 1]) == 0 and np.ptp(fr[-1][:, 2]) == 0
    xs = [f[0, 0] for f in fr]
    assert xs == sorted(xs, reverse=True) and len(set(xs)) == 15     # nose (highest x) to tail


def test_fit_report_and_volume():
    tri = ellipsoid()
    rep = fit_report(slice_frames(tri, 31, 37), tri)
    assert rep["rms_gap_m"] < 1e-3
    assert rep["skin_volume_m3"] == pytest.approx(4 / 3 * np.pi * A * B * C, rel=0.02)
    assert rep["body_volume_m3"] == pytest.approx(rep["skin_volume_m3"], rel=0.05)


def test_cut_removes_a_wing_panel():
    tri = np.concatenate([ellipsoid(), box(0.0, 0.3, -0.4, 0.4, -0.01, 0.02)])
    cut = {"x_m": [-0.05, 0.35], "y_max_m": 0.11}
    plain = slice_frame(tri, 0.15, 37)
    cleaned = slice_frame(tri, 0.15, 37, cut)
    assert plain[:, 1].max() > 0.3                       # the panel is in the frame without a cut
    assert cleaned[:, 1].max() <= 0.11 + 1e-9            # and out of it with the cut
    assert np.allclose(cleaned[0], slice_frame(ellipsoid(), 0.15, 37)[0], atol=2e-3)   # the top point stays the pod


def test_open_skin_is_refused():
    with pytest.raises(ValueError, match="no section"):
        slice_frame(ellipsoid(), 2.0, 25)


def _edge_counts(tri):
    from collections import Counter
    v = tri.reshape(-1, 3).round(7)
    ids = {}
    idx = np.array([ids.setdefault(tuple(p), len(ids)) for p in v]).reshape(-1, 3)
    return Counter(Counter(tuple(sorted(e)) for k in idx for e in ((k[0], k[1]), (k[1], k[2]), (k[2], k[0]))).values())


def test_flaps_on_four_triangle_edges_are_removed():
    from aeroplan.skin_body import drop_slivers

    tri = ellipsoid()
    a, b = tri[len(tri) // 2, 0], tri[len(tri) // 2, 1]                         # a flap: two zero-area triangles that share an edge of the surface
    flap = np.array([[a, b, (a + b) / 2], [a, b, (a + b) / 2 + 1e-12]])
    glued = np.concatenate([tri, flap])
    assert _edge_counts(glued).get(4) or _edge_counts(glued).get(3)
    fixed, n = drop_slivers(glued)
    assert n >= 2 and not set(_edge_counts(fixed)) & {3, 4}        # (the degenerate pole fans of the ellipsoid go too)


def test_needle_triangle_is_removed_and_the_mesh_stays_closed():
    from aeroplan.skin_body import mesh_volume, repair_for_panel

    tri = ellipsoid(n_u=20, n_v=12)
    k = len(tri) // 2
    a, b, c = tri[k]
    mid = (a + b) / 2                                      # split the neighbour across edge a-b at its middle point:
    other = next(j for j in range(len(tri)) if j != k and any(np.allclose(tri[j][i], a) and np.allclose(tri[j][(i + 1) % 3], b)
                                                                or np.allclose(tri[j][i], b) and np.allclose(tri[j][(i + 1) % 3], a)
                                                                for i in range(3)))
    t = tri[other]
    i = next(i for i in range(3) if {tuple(np.round(t[i], 9)), tuple(np.round(t[(i + 1) % 3], 9))} ==
             {tuple(np.round(a, 9)), tuple(np.round(b, 9))})
    u, w, p = t[i], t[(i + 1) % 3], t[(i + 2) % 3]
    pieces = np.array([[u, mid, p], [mid, w, p]])
    # the triangle k gets a needle neighbour: (a, mid, b) has three collinear points
    needle = np.array([[a, mid, b]])
    mesh = np.concatenate([np.delete(tri, other, axis=0), pieces, needle])
    fixed, info = repair_for_panel(mesh)
    assert info["needles"] >= 1
    a_ = 0.5 * np.linalg.norm(np.cross(fixed[:, 1] - fixed[:, 0], fixed[:, 2] - fixed[:, 0]), axis=1)
    assert a_.min() > 0
    assert mesh_volume(fixed) == pytest.approx(mesh_volume(tri), rel=1e-6)
