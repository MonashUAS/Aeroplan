import json
import xml.etree.ElementTree as ET

import pandas as pd
import pytest
from pydantic import ValidationError

from aeroplan.assemble import assemble_adh
from aeroplan.dml import points_to_dml
from aeroplan.muas.ic import InitialConditions
from aeroplan.package import pack_h5, unpack_h5, verify_package
from aeroplan.synthetic import make_placeholder_package


@pytest.fixture
def pkg(tmp_path):
    d = tmp_path / "pkg"
    return d, make_placeholder_package(d)


def test_synthetic_package_verifies_and_is_flagged(pkg):
    d, m = pkg
    assert m.placeholder and verify_package(d).sha256 == m.sha256
    assert {"adh/aircraft.adh.json", "dml/aero.dml", "dml/propulsion.dml", "ic/initial_conditions.json"} <= {
        f.path for f in m.files}


def test_package_is_immutable(pkg):
    d, _ = pkg
    with pytest.raises(FileExistsError):
        make_placeholder_package(d)


def test_tamper_and_extra_files_are_detected(pkg):
    d, _ = pkg
    (d / "dml" / "aero.dml").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_package(d)


def test_extra_file_detected(pkg):
    d, _ = pkg
    (d / "stray.txt").write_text("x")
    with pytest.raises(ValueError, match="not in manifest"):
        verify_package(d)


def test_h5_wrapper_roundtrip_is_byte_identical(pkg, tmp_path):
    d, m = pkg
    h5 = pack_h5(d, tmp_path / "pkg.h5")
    out = tmp_path / "unpacked"
    assert unpack_h5(h5, out).sha256 == m.sha256
    for f in m.files:
        assert (out / f.path).read_bytes() == (d / f.path).read_bytes()


def test_adh_document_is_deterministic_and_has_real_wbs(pkg):
    d, _ = pkg
    doc = json.loads((d / "adh" / "aircraft.adh.json").read_text())
    assert [n["wbs_no"] for n in doc["nodes"]] == ["1.2.2.3", "1.2.3.9"]


def test_duplicate_node_rejected():
    n = {"wbs_no": "1.2.2.3", "name": "Wing", "muas": {"ext_version": "0.1.0", "instance": "a"}}
    with pytest.raises(ValueError, match="duplicate"):
        assemble_adh([n, dict(n)], muas_schema_version="0.1.0")


def test_dml_is_well_formed_and_uses_brief_elements(pkg):
    d, _ = pkg
    root = ET.fromstring((d / "dml" / "aero.dml").read_bytes())
    assert root.tag == "DAVEfunc"
    for tag in ("variableDef", "ungriddedTableDef", "function", "independentVarRef", "dependentVarRef",
                "ungriddedTableRef", "checkData", "staticShot", "uncertainty", "normalPDF"):
        assert root.find(f".//{tag}") is not None, tag
    # per-point sigma is a companion table (D21); fixed beta is not an independent variable
    assert root.find(".//ungriddedTableDef[@utID='Cm_sigma_table']") is not None
    assert [e.get("varID") for e in root.iter("independentVarRef")] == ["alpha"]


def test_dml_rejects_varying_fixed_input():
    pts = pd.DataFrame({"a": [0.0, 1.0], "b": [0.0, 1.0], "y": [0.0, 1.0]})
    ins = [{"id": "a", "name": "a", "units": "nd", "range": [0, 1]}, {"id": "b", "name": "b", "units": "nd", "fixed": 0.0}]
    with pytest.raises(ValueError, match="fixed"):
        points_to_dml(name="t", inputs=ins, outputs=[{"id": "y", "name": "y", "units": "nd"}], points=pts,
                      author="t", created="2026-01-01", ref_id="r")


def test_ic_mandatory_fields():
    with pytest.raises(ValidationError):
        InitialConditions(latitude_type="geodetic", attitude_sequence="3-2-1", values={})
    with pytest.raises(ValidationError):
        InitialConditions(rate_frame="inertial", latitude_type="geodetic", attitude_sequence="9-9-9", values={})


def test_dml_passes_the_vendored_dtd(pkg):
    from aeroplan.dml_validate import validate_dml

    d, _ = pkg
    for f in ("aero", "propulsion"):
        assert validate_dml((d / "dml" / f"{f}.dml").read_bytes()) == []


def test_dtd_check_rejects_the_brief_snippet_layout():
    """Snippet 6.3 put provenance at the root. The 2.0 DTD forbids it. The check must catch this."""
    from aeroplan.dml_validate import validate_dml

    bad = (b'<DAVEfunc><fileHeader><author name="a" org="o"/><creationDate date="2026-01-01"/></fileHeader>'
           b'<variableDef name="x" varID="x" units="nd"/><provenance provID="p"><author name="a" org="o"/>'
           b'<creationDate date="2026-01-01"/></provenance></DAVEfunc>')
    assert validate_dml(bad)


def test_invalid_dml_cannot_enter_a_package(tmp_path):
    from aeroplan.package import Source, build_package

    with pytest.raises(ValueError, match="not valid DAVE-ML"):
        build_package(tmp_path / "p", {"dml/x.dml": b"<DAVEfunc/>"}, package_id="x", source=Source(repo="r", commit="c"),
                      config_id="c", fidelity_summary={}, frames={}, reference={}, standards={"dml/x.dml": "ANSI/AIAA S-119-2011"})
