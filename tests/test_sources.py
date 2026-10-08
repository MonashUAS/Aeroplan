import json

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from aeroplan.adapters.flow5 import Flow5SweepAdapter, PolarError, control_range, parse_polar_text
from aeroplan.adapters.propalyser import PropalyserAdapter
from aeroplan.config import json_to_commented_yaml, strip_comments
from aeroplan.muas.dataset import AeroPointManifest, check_points_file
from aeroplan.muas.propulsion import PropCtCpManifest
from aeroplan.muas.uncertainty import ScalarResult, Uncertainty

from sources import make_propalyser_h5, make_sweep, polar_text


# --- flow5 polar parser ---
def test_polar_welded_first_row_is_found():
    p = parse_polar_text(polar_text("alpha", n=3))
    assert p.data.shape == (3, 10) and p.columns[:4] == ["Ctrl", "alpha", "beta", "phi"] and p.speed == 10.0


def test_polar_partial_file_refused():
    with pytest.raises(PolarError, match="declared"):
        parse_polar_text(polar_text("alpha", n=3, drop_declared=5))


def test_control_range_equal_or_reversed():
    p = parse_polar_text(polar_text("elevator", t6=True))
    assert control_range(p) == (-10.0, 10.0, True)


def test_control_range_conflict_refused():
    text = polar_text("elevator", t6=True).replace("10.000, -10.000", "5.000, -5.000")
    with pytest.raises(PolarError, match="neither equal nor reversed"):
        control_range(parse_polar_text(text))


# --- flow5 adapter ---
def test_flow5_sweep_adapter(tmp_path):
    make_sweep(tmp_path / "sweep")
    files = Flow5SweepAdapter("cfg_x", "a" * 64).ingest(tmp_path / "sweep", tmp_path / "out")
    names = sorted({f.parent.name for f in files})
    assert names == ["aero.flow5.alpha.cfg_x", "aero.flow5.elevator.cfg_x"]  # t7_reference is skipped
    m = AeroPointManifest.model_validate_json((tmp_path / "out" / names[1] / "manifest.json").read_text())
    check_points_file(m, tmp_path / "out" / names[1])
    assert m.term.value == "control" and m.uncertainty.status.value == "unavailable"
    assert m.reference.mrp.point.xyz == [0.1, 0.0, -0.01]
    df = pd.read_parquet(tmp_path / "out" / names[1] / "points.parquet")
    assert df["delta"].tolist() == [-10.0, 0.0, 10.0]
    roll = next(o for o in m.outputs if o.id == "Cl")
    assert "OPPOSITE" in roll.sign  # the flow5 sign trap is stated, values are stored as written


def test_flow5_adapter_needs_the_plane(tmp_path):
    make_sweep(tmp_path / "sweep")
    (tmp_path / "sweep" / "plane_with_body.xml").unlink()
    with pytest.raises(FileNotFoundError):
        Flow5SweepAdapter("c").ingest(tmp_path / "sweep", tmp_path / "out")


# --- propalyser adapter (contract B, v2) ---
def test_propalyser_adapter(tmp_path):
    make_propalyser_h5(tmp_path / "sys.h5")
    files = PropalyserAdapter("cfg_x").ingest(tmp_path / "sys.h5", tmp_path / "out")
    m = PropCtCpManifest.model_validate_json(next(f for f in files if f.name == "manifest.json").read_text())
    assert m.placeholder and m.valid_j == (0.0, 0.5) and m.propeller_id == "PROP_X"
    assert m.derived["ct0"].coverage == 0.95 and m.derived["ct0"].lower == 0.07
    assert m.uncertainty.status.value == "quantitative" and m.uncertainty.per_point_column == "Ct_sigma"
    assert m.provenance.author == "Test Person"
    assert any(f.name == "source_propulsion.dml" for f in files)
    df = pd.read_parquet(next(f for f in files if f.name == "points.parquet"))
    assert list(df.columns) == ["J", "Ct", "Cp", "Ct_sigma", "Cp_sigma"]


def test_propalyser_unavailable_uncertainty(tmp_path):
    make_propalyser_h5(tmp_path / "sys.h5", status="unavailable")
    files = PropalyserAdapter("c").ingest(tmp_path / "sys.h5", tmp_path / "out")
    m = PropCtCpManifest.model_validate_json(files[0].read_text())
    assert m.uncertainty.status.value == "unavailable"


@pytest.mark.parametrize("kw, match", [({"version": 1}, "version 2"), ({"dirty": True}, "dirty"),
                                       ({"units": False}, "units"), ({"bad_units": True}, "pint spelling")])
def test_propalyser_refusals(tmp_path, kw, match):
    make_propalyser_h5(tmp_path / "sys.h5", **kw)
    with pytest.raises(ValueError, match=match):
        PropalyserAdapter("c").ingest(tmp_path / "sys.h5", tmp_path / "out")


# --- uncertainty additions ---
def test_interval_needs_coverage_and_has_no_adh_form():
    base = dict(status="quantitative", scope="derived", basis="b", effect="absolute", distribution="interval",
                method="monte_carlo", lower=0.1, upper=0.2)
    with pytest.raises(ValidationError):
        Uncertainty(**base)
    u = Uncertainty(**base, coverage=0.95)
    with pytest.raises(ValueError, match="no ADH"):
        u.to_adh()


def test_scalar_result_order():
    with pytest.raises(ValidationError):
        ScalarResult(median=3, lower=1, upper=2, coverage=0.95)


# --- legacy JSON config to YAML ---
def test_commented_yaml_keeps_the_data():
    legacy = {"_readme": ["line 1", "line 2"], "name": "x", "a": {"_comment": "why", "v": 1.5, "l": [1, 2], "e": {}},
              "_note": "tail"}
    text = json_to_commented_yaml(legacy)
    assert "# why" in text and "# note: tail" in text
    assert yaml.safe_load(text) == strip_comments(legacy)


def test_unknown_provenance_date_is_allowed():
    from aeroplan.muas.provenance import Provenance

    assert Provenance(tool="t", tool_version="v", author="unknown").created is None
