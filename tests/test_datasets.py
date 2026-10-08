import copy

import pandas as pd
import pytest
from pydantic import ValidationError

from aeroplan.muas.dataset import AeroPointManifest, check_points_file
from aeroplan.muas.propulsion import PropCtCpManifest, PropellerInstallation


def test_aero_manifest_ok(aero_manifest):
    m = AeroPointManifest(**aero_manifest)
    assert m.expected_columns() == ["alpha", "beta", "Cm"]


def test_every_input_is_explicit(aero_manifest):
    aero_manifest["inputs"][1] = {"name": "angleOfSideslip", "id": "beta", "units": "deg"}
    with pytest.raises(ValidationError):
        AeroPointManifest(**aero_manifest)


def test_outputs_declare_axes_and_sign(aero_manifest):
    del aero_manifest["outputs"][0]["axis_system"]
    with pytest.raises(ValidationError):
        AeroPointManifest(**aero_manifest)


def test_correction_rules(aero_manifest):
    aero_manifest["role"] = "correction"
    with pytest.raises(ValidationError):
        AeroPointManifest(**aero_manifest)
    aero_manifest.update(effect="stopped_lift_rotors", nominal_ref="aero.cm_static.test.cfg_nominal.1")
    AeroPointManifest(**aero_manifest)
    aero_manifest["role"] = "nominal"
    with pytest.raises(ValidationError):
        AeroPointManifest(**aero_manifest)


def test_mrp_travels_with_dataset(aero_manifest):
    del aero_manifest["reference"]["mrp"]
    with pytest.raises(ValidationError):
        AeroPointManifest(**aero_manifest)


def test_points_file_columns(aero_manifest, tmp_path):
    m = AeroPointManifest(**aero_manifest)
    pd.DataFrame({"alpha": [0, 1, 2], "beta": [0, 0, 0], "Cm": [0.0, 0.1, 0.2]}).to_parquet(tmp_path / "points.parquet")
    check_points_file(m, tmp_path)
    pd.DataFrame({"alpha": [0, 1, 2]}).to_parquet(tmp_path / "points.parquet")
    with pytest.raises(ValueError):
        check_points_file(m, tmp_path)


def _prop(prov, **kw):
    d = dict(
        dataset_id="prop.ctcp.test.1", config_id="cfg_nominal", propeller_id="prop_test", fidelity="L3",
        source_tool="test", diameter={"value": 10, "units": "in"}, valid_domain="static_only",
        limits=["static chain overstates power in forward flight"],
        uncertainty={"status": "quantitative", "scope": "result", "basis": "synthetic", "effect": "additive",
                     "distribution": "normal", "per_point_column": "Ct_sigma", "method": "measurement_chain"},
        processing={"binning": "none", "n_raw": 3, "n_points": 3}, provenance=prov,
    )
    d.update(kw)
    return PropCtCpManifest(**d)


def test_prop_ctcp_ok_and_diameter_si(prov):
    assert _prop(prov).diameter.value == pytest.approx(0.254)


def test_static_only_needs_limits(prov):
    with pytest.raises(ValidationError):
        _prop(prov, limits=[])


def test_prop_needs_per_point_sigma(prov):
    with pytest.raises(ValidationError):
        _prop(prov, uncertainty={"status": "quantitative", "scope": "result", "basis": "x", "effect": "additive",
                                  "distribution": "normal", "sigma": 0.1, "method": "engineering"})


def test_installation_axis_unit_vector():
    ok = dict(role="cruise", hub={"xyz": [0, 0, 0]}, thrust_axis=[-1, 0, 0], spin="cw", diameter={"value": 0.25, "units": "m"})
    PropellerInstallation(**ok)
    with pytest.raises(ValidationError):
        PropellerInstallation(**{**ok, "thrust_axis": [-2, 0, 0]})
