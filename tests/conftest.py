"""Shared fixtures. Every number here is a synthetic test value, not aircraft data."""
from datetime import datetime

import pytest

H = "a" * 64


@pytest.fixture
def prov():
    return {"tool": "test", "tool_version": "0", "author": "test", "created": datetime(2026, 1, 1).isoformat()}


@pytest.fixture
def unc_normal():
    return {
        "status": "quantitative", "scope": "result", "basis": "synthetic test value",
        "effect": "additive", "distribution": "normal", "sigma": 0.05, "method": "engineering",
    }


@pytest.fixture
def mrp():
    return {"config_id": "cfg_nominal", "point": {"xyz": [1.0, 0.0, 0.1]}}


@pytest.fixture
def aero_manifest(prov, unc_normal, mrp):
    return {
        "dataset_id": "aero.cm_static.test.cfg_nominal.1", "role": "nominal", "config_id": "cfg_nominal",
        "geometry_hash": H, "fidelity": "L1", "source_tool": "test",
        "inputs": [
            {"name": "angleOfAttack", "id": "alpha", "units": "deg", "range": [-5, 10]},
            {"name": "angleOfSideslip", "id": "beta", "units": "deg", "fixed": 0},
        ],
        "outputs": [{"name": "pitchingMomentCoefficient", "id": "Cm", "units": "nd",
                     "axis_system": "body", "sign": "nose-up positive", "is_moment": True}],
        "reference": {"s_ref_m2": 1.0, "b_ref_m": 2.0, "c_ref_m": 0.5, "mrp": mrp},
        "uncertainty": unc_normal,
        "processing": {"binning": "none", "n_raw": 3, "n_points": 3},
        "provenance": prov,
    }
