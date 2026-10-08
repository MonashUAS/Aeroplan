import copy
import math

import numpy as np
import pytest
from pydantic import ValidationError

from aeroplan.frames import design_to_frd, frd_to_design, transfer_moment_coefficients
from aeroplan.muas.mass import Inertia, MassProperties, roll_up
from aeroplan.muas.reference import ReferenceData
from aeroplan.muas.units import Q, Quantity


# --- units (D04) ---
def test_units_normalise_to_si():
    assert Q(1000, "g").value == pytest.approx(1.0) and Q(1000, "g").units == "kg"
    assert Q(180, "deg").value == pytest.approx(math.pi)
    assert Q(0.3, "nd").units == "nd"


def test_units_reject_unknown_and_wrong_dimension():
    with pytest.raises(ValidationError):
        Quantity(value=1, units="furlongs_per_banana")
    with pytest.raises(ValueError):
        Q(1, "m").require("mass")


# --- frames (D05) ---
def test_design_frd_roundtrip():
    v = [1.0, 2.0, 3.0]
    assert np.allclose(frd_to_design(design_to_frd(v)), v)
    assert np.allclose(design_to_frd([1, 2, 3]), [-1, 2, -3])


def test_lift_aft_of_reference_is_nose_down():
    # Lift (CZ = -CL in FRD) acting 0.1 m aft of the target point must give a nose-down moment.
    cl = 0.5
    _, cm, _ = transfer_moment_coefficients((0, 0, -cl), (0, 0, 0), [1.1, 0, 0], [1.0, 0, 0], b_ref=2.0, c_ref=0.5)
    assert cm == pytest.approx(-cl * 0.1 / 0.5)


def test_transfer_is_reversible_and_asymmetric_point_checked():
    cf, cm = (0.02, 0.1, -0.4), (0.01, -0.02, 0.005)  # beta != 0 style point
    a, b = [1.0, 0.0, 0.1], [1.2, 0.05, 0.0]
    there = transfer_moment_coefficients(cf, cm, a, b, 2.0, 0.5)
    back = transfer_moment_coefficients(cf, there, b, a, 2.0, 0.5)
    assert np.allclose(back, cm)
    assert not np.allclose(there, cm)


# --- mass (D11) ---
def _mp(m, xyz, ixx=0.1, iyy=0.1, izz=0.1):
    return MassProperties(mass=Q(m, "kg"), cg={"xyz": xyz}, inertia=Inertia(ixx=ixx, iyy=iyy, izz=izz), source="estimate")


def test_rollup_parallel_axis():
    total = roll_up([_mp(1, [0, 0, 0]), _mp(1, [2, 0, 0])])
    assert total.mass.value == pytest.approx(2.0)
    assert total.cg.xyz == pytest.approx([1.0, 0, 0])
    # each point mass sits 1 m from the combined CG along x: Iyy and Izz gain 2*1*1^2
    assert total.inertia.ixx == pytest.approx(0.2)
    assert total.inertia.iyy == pytest.approx(0.2 + 2.0)


def test_rollup_keeps_placeholder_flag():
    item = _mp(1, [0, 0, 0])
    item.placeholder = True
    assert roll_up([item, _mp(1, [1, 0, 0])]).placeholder


def test_inertia_rejects_unphysical():
    with pytest.raises(ValidationError):
        Inertia(ixx=1, iyy=1, izz=5)  # triangle inequality
    with pytest.raises(ValidationError):
        Inertia(ixx=1, iyy=1, izz=1, ixy=2)  # not positive definite


# --- reference and MRP (user answer 7) ---
def _ref(**kw):
    d = dict(s_ref=Q(1, "m^2"), b_ref=Q(2, "m"), c_ref=Q(0.5, "m"), nominal_cg={"xyz": [1, 0, 0.1]},
             mrp={"config_id": "c", "point": {"xyz": [1, 0, 0.1]}})
    d.update(kw)
    return ReferenceData(**d)


def test_mrp_is_nominal_cg():
    assert _ref().mrp.definition.value == "nominal_cg"
    with pytest.raises(ValidationError):
        _ref(mrp={"config_id": "c", "point": {"xyz": [1.5, 0, 0.1]}})


def test_reference_rejects_wrong_dimension():
    with pytest.raises(ValidationError):
        _ref(s_ref=Q(1, "m"))
