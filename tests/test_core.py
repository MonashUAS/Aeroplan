import math

import pytest
from pydantic import ValidationError

from aeroplan import adh_doc
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
    d = dict(nominal_cg={"xyz": [1, 0, 0.1]}, mrp={"config_id": "c", "point": {"xyz": [1, 0, 0.1]}})
    d.update(kw)
    return ReferenceData(**d)


def test_mrp_is_nominal_cg():
    assert _ref().mrp.definition.value == "nominal_cg"
    with pytest.raises(ValidationError):
        _ref(mrp={"config_id": "c", "point": {"xyz": [1.5, 0, 0.1]}})


def test_reference_values_are_adh_data_with_the_adh_aliases():
    """ADR 0027: S, b and c are the ADH reference_data of node 1.2. ADH reads only its aliases (Sref, BLref, Cbar): a field
    name passes the ADH validation as an unknown extra key and the value is lost, so validate_document refuses it."""
    doc = adh_doc.new_document("T", "synthetic")
    adh_doc.set_reference(doc, 1.0, 2.0, 0.5)
    adh_doc.validate_document(doc)
    assert adh_doc.reference(doc) == {"s_ref": {"value": 1.0, "units": "m^2"}, "b_ref": {"value": 2.0, "units": "m"},
                                      "c_ref": {"value": 0.5, "units": "m"}}
    with pytest.raises(ValidationError):
        _ref(s_ref=Q(1, "m^2"))                                         # no copy in muas.reference
    adh_doc.node(doc, "1.2")["parameters"]["reference_data"]["reference_area"] = 1.0
    with pytest.raises(ValueError, match="aliases"):
        adh_doc.validate_document(doc)


# --- propeller installation ---
def test_installation_axis_unit_vector():
    ok = dict(role="cruise", hub={"xyz": [0, 0, 0]}, thrust_axis=[-1, 0, 0], spin="cw", diameter={"value": 0.25, "units": "m"})
    PropellerInstallation(**ok)
    with pytest.raises(ValidationError):
        PropellerInstallation(**{**ok, "thrust_axis": [-2, 0, 0]})
