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


def test_rollup_own_inertia():
    # a rod of mass 2 kg and length 3 m along x, split in two halves of 1 kg at x = -0.75 and +0.75 (own Iyy = m l^2 / 12)
    # against the same rod as one item with its own inertia: the two roll-ups must agree about the CG
    halves = mass_model.rollup([{"mass_kg": 1.0, "xyz": [-0.75, 0.0, 0.0], "inertia_own": [0.0, 1.5 ** 2 / 12, 1.5 ** 2 / 12]},
                                {"mass_kg": 1.0, "xyz": [0.75, 0.0, 0.0], "inertia_own": [0.0, 1.5 ** 2 / 12, 1.5 ** 2 / 12]}])
    rod = mass_model.rollup([{"mass_kg": 2.0, "xyz": [0.0, 0.0, 0.0], "inertia_own": {"ixx": 0.0, "iyy": 2 * 9 / 12, "izz": 2 * 9 / 12}}])
    assert halves["inertia"]["iyy"] == pytest.approx(rod["inertia"]["iyy"])
    assert rod["inertia"]["iyy"] == pytest.approx(1.5)
    # own inertia moves with the item: the item at x = 5 and a point mass at x = 0 (both 1 kg), own Ixx = 0.2
    r = mass_model.rollup([{"mass_kg": 1.0, "xyz": [0.0, 0.0, 0.0]},
                           {"mass_kg": 1.0, "xyz": [0.0, 2.0, 0.0], "inertia_own": {"ixx": 0.2, "iyy": 0.1, "izz": 0.3, "ixy": 0.05}}])
    assert r["inertia"]["ixx"] == pytest.approx(2 * 1.0 + 0.2)       # parallel axis 2 x 1^2, plus the own term
    assert r["inertia"]["ixy"] == pytest.approx(0.05)
    assert r["inertia"]["izz"] == pytest.approx(2 * 1.0 + 0.3)


def test_rollup_own_inertia_input_checks():
    with pytest.raises(ValueError):
        mass_model.rollup([{"mass_kg": 1.0, "xyz": [0.0, 0.0, 0.0], "inertia_own": {"ixx": 1.0}}])
    with pytest.raises(ValueError):
        mass_model.rollup([{"mass_kg": 1.0, "xyz": [0.0, 0.0, 0.0], "inertia_own": [1.0, 2.0]}])
    with pytest.raises(ValueError):
        mass_model.rollup([{"mass_kg": 1.0, "xyz": [0.0, 0.0, 0.0], "inertia_own": [-1.0, 2.0, 1.0]}])


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
