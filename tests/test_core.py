import math

import pytest
from pydantic import ValidationError

from aeroplan.muas.mass import Inertia, MassProperties
from aeroplan.muas.propulsion import PropellerInstallation
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


# --- mass (D11) ---
def test_mass_properties_need_a_positive_mass():
    MassProperties(mass=Q(1, "kg"), cg={"xyz": [0, 0, 0]}, inertia=Inertia(ixx=0.1, iyy=0.1, izz=0.1), source="estimate")
    with pytest.raises(ValidationError):
        MassProperties(mass=Q(-1, "kg"), cg={"xyz": [0, 0, 0]}, source="estimate")


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


# --- propeller installation ---
def test_installation_axis_unit_vector():
    ok = dict(role="cruise", hub={"xyz": [0, 0, 0]}, thrust_axis=[-1, 0, 0], spin="cw", diameter={"value": 0.25, "units": "m"})
    PropellerInstallation(**ok)
    with pytest.raises(ValidationError):
        PropellerInstallation(**{**ok, "thrust_axis": [-2, 0, 0]})
