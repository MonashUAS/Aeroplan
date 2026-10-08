"""Uncertainty schema tests. The three states follow NASA-STD-7009B [M&S 33] a, b, c."""
import copy

import pytest
from pydantic import ValidationError

from aeroplan.muas.uncertainty import Uncertainty


def test_quantitative_ok(unc_normal):
    assert Uncertainty(**unc_normal).sigma == 0.05


def test_basis_is_required(unc_normal):
    unc_normal["basis"] = ""
    with pytest.raises(ValidationError):
        Uncertainty(**unc_normal)


def test_quantitative_needs_sigma_or_column(unc_normal):
    del unc_normal["sigma"]
    with pytest.raises(ValidationError):
        Uncertainty(**unc_normal)
    unc_normal["per_point_column"] = "Cm_sigma"
    Uncertainty(**unc_normal)


def test_qualitative_needs_level():
    base = dict(status="qualitative", scope="input", basis="SME judgement")
    with pytest.raises(ValidationError):
        Uncertainty(**base)
    assert Uncertainty(**base, qualitative_level="large").qualitative_level.value == "large"


def test_unavailable_is_explicit_and_carries_no_numbers():
    u = Uncertainty(status="unavailable", scope="derived", basis="no estimate available")
    assert u.sigma is None
    with pytest.raises(ValidationError):
        Uncertainty(status="unavailable", scope="derived", basis="x", sigma=0.1)


def test_uniform_bounds_order(unc_normal):
    d = {**unc_normal, "distribution": "uniform", "lower": 2.0, "upper": 1.0}
    del d["sigma"]
    with pytest.raises(ValidationError):
        Uncertainty(**d)


def test_factors_and_correlations_recorded(unc_normal):
    u = Uncertainty(**unc_normal, factors=[{"name": "FS", "value": 1.5, "covers": "model form"}],
                    correlations=[{"var_id": "Cl", "coefficient": 0.3}])
    assert u.factors[0].covers == "model form"
    with pytest.raises(ValidationError):
        Uncertainty(**unc_normal, correlations=[{"var_id": "Cl", "coefficient": 1.5}])


def test_extra_keys_rejected(unc_normal):
    with pytest.raises(ValidationError):
        Uncertainty(**unc_normal, sigmaa=1)


def test_maps_to_adh_normal_and_uniform(unc_normal):
    adh = Uncertainty(**unc_normal).to_adh()
    assert adh.effect.value == "additive" and adh.normal_pdf.bounds[0].value == "0.05"
    uni = {**unc_normal, "distribution": "uniform", "lower": -1.0, "upper": 1.0}
    del uni["sigma"]
    assert len(Uncertainty(**uni).to_adh().uniform_pdf.bounds) == 2


def test_only_quantitative_maps_to_adh():
    with pytest.raises(ValueError):
        Uncertainty(status="unavailable", scope="input", basis="x").to_adh()
