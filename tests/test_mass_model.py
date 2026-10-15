"""The mass model: roll-up with parallel axis, and the strip distribution. Synthetic numbers only."""
import numpy as np
import pytest

from aeroplan import mass_model


def test_rollup_two_masses():
    r = mass_model.rollup([{"mass_kg": 1.0, "xyz": [0.0, 0.0, 0.0]}, {"mass_kg": 3.0, "xyz": [4.0, 0.0, 0.0]}])
    assert r["mass_kg"] == pytest.approx(4.0)
    assert r["cg"] == pytest.approx([3.0, 0.0, 0.0])
    # distances to the CG: 3 and 1 -> Iyy = Izz = 1*9 + 3*1
    assert r["inertia"]["iyy"] == pytest.approx(12.0)
    assert r["inertia"]["izz"] == pytest.approx(12.0)
    assert r["inertia"]["ixx"] == pytest.approx(0.0)


def test_rollup_products_and_empty():
    r = mass_model.rollup([{"mass_kg": 1.0, "xyz": [1.0, 0.0, 1.0]}, {"mass_kg": 1.0, "xyz": [-1.0, 0.0, -1.0]}])
    assert r["inertia"]["ixz"] == pytest.approx(2.0)
    with pytest.raises(ValueError):
        mass_model.rollup([])


def _planform(kind="WING", symmetric=True):
    secs = [{"y": 0.0, "chord": 0.4, "x_offset": 0.0, "dihedral_deg": 0.0, "twist_deg": 0.0, "foil": "f"},
            {"y": 1.0, "chord": 0.2, "x_offset": 0.1, "dihedral_deg": 0.0, "twist_deg": 0.0, "foil": "f"}]
    return {"surface_name": "w", "kind": kind, "position": {"xyz": [0.0, 0.0, 0.0]}, "symmetric": symmetric,
            "sections": secs}


def test_strips_keep_mass_and_cg():
    strips = mass_model.distribute_on_planform(2.0, _planform(), 6, -0.25)
    r = mass_model.rollup(strips)
    assert r["mass_kg"] == pytest.approx(2.0)
    assert r["cg"][0] == pytest.approx(-0.25)
    assert r["cg"][1] == pytest.approx(0.0, abs=1e-12)
    assert len(strips) == 12
    assert r["inertia"]["ixx"] > 0.0
    # the root strips are heavier than the tip strips (more area)
    ys = np.array([abs(s["xyz"][1]) for s in strips])
    ms = np.array([s["mass_kg"] for s in strips])
    assert ms[ys.argmin()] > ms[ys.argmax()]
