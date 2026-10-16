"""ADH compatibility. Method follows ADH's own tests: Pydantic validation, import checks, schema export."""
import json
import re
from pathlib import Path

import pytest

from aeroplan import MUAS_SCHEMA_VERSION, adh_doc
from aeroplan.schema_export import export_schemas

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "aeroplan"


def _doc(prov):
    """A document with a wing node and one aileron subcomponent (synthetic values)."""
    doc = adh_doc.new_document("Test", "synthetic aircraft")
    wing = adh_doc.node(doc, "1.2.2.3", create=True)
    wing.update({"description": "synthetic wing", "muas": {
        "ext_version": MUAS_SCHEMA_VERSION, "instance": "wing_main", "fidelity": "L1", "provenance": prov,
        "mass_properties": {"mass": {"value": 1, "units": "kg"}, "cg": {"xyz": [0, 0, 0]},
                            "source": "estimate", "placeholder": True}}})
    wing["subcomponents"] = [{"name": "Ailerons", "muas": {"ext_version": MUAS_SCHEMA_VERSION, "instance": "ail_L"}}]
    return doc


def test_document_validates(prov):
    adh_doc.validate_document(_doc(prov))


def test_wbs_numbers_come_from_upstream():
    assert {"1.2.2.3", "1.2.2.3.3", "1.2.3.9", "1.2.3.11", "1.10.2", "1.8.1.4", "1.2.9"} <= set(adh_doc.wbs_tree())
    assert adh_doc.wbs_tree()["1.10.2"]["path"] == ("data", "data_repository")
    assert adh_doc.wbs_tree()["1.8.1.4"]["path"][-1] == "flight_tests"


def test_invented_wbs_number_rejected():
    doc = adh_doc.new_document("Test", "synthetic")
    with pytest.raises(KeyError):
        adh_doc.node(doc, "9.9.9", create=True)


def test_typo_in_muas_key_rejected(prov):
    doc = _doc(prov)
    adh_doc.node(doc, "1.2.2.3")["muas"]["mass_propertes"] = {}
    with pytest.raises(Exception):
        adh_doc.validate_document(doc)


def test_subcomponent_has_no_wbs_number(prov):
    """A subcomponent shares the WBS number of its node (adh_doc rule): a wbs_no on it is refused."""
    doc = _doc(prov)
    wing = adh_doc.node(doc, "1.2.2.3")
    wing["subcomponents"][0]["wbs_no"] = "1.2.2.3.3"
    with pytest.raises(ValueError, match="subcomponent has no wbs_no"):
        adh_doc.validate_document(doc)
    del wing["subcomponents"][0]["wbs_no"]
    adh_doc.validate_document(doc)


def test_register_and_flight_keys_belong_on_their_node(prov):
    doc = _doc(prov)
    adh_doc.node(doc, "1.2.2.3")["muas"]["assets"] = []
    with pytest.raises(ValueError, match="1.10.2"):
        adh_doc.validate_document(doc)


def test_patched_adh_schema_exports():
    """Known upstream defect (brief section 1). Patch 0001 must fix it."""
    from aircraft_data_hierarchy.work_breakdown_structure.airframe import Component

    json.dumps(Component.model_json_schema())


def test_muas_schemas_export(tmp_path):
    files = export_schemas(tmp_path)
    assert len(files) == 14 and all(json.loads(f.read_text()) for f in files)


def test_committed_schema_is_current():
    from aeroplan import MUAS_SCHEMA_VERSION

    committed = Path(__file__).resolve().parents[1] / "schema" / f"v{MUAS_SCHEMA_VERSION}"
    if not committed.exists():
        pytest.skip("schema not exported yet")
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        for f in export_schemas(Path(d)):
            assert (committed / f.name).read_text() == f.read_text(), f"{f.name} is stale: run `aeroplan schema`"


def test_imports():
    from aeroplan import adh_doc, assets, build, checks, consumers, daveml_adh, gltf, h5json, package, source_tree, spokes  # noqa: F401,E501
    from aeroplan.muas import aircraft, assets, dataset, flight, mass, node, propulsion, reference, uncertainty  # noqa: F401,E501


def test_tool_independence():
    """ADH principle: data is separate from tools. AeroPlan imports no sibling repo."""
    pattern = re.compile(r"^\s*(import|from)\s+(aerolink|propalyser|proptimiser)", re.I | re.M)
    spokes = [ROOT / name for name in ("Prototype", "AeroSandbox", "flow5", "Propalyser", "CREO", "OpenVSP", "DAVEML", "ArduPilot", "MissionPlanner", "Aerolink")]
    worker = ROOT / "AeroSandbox" / "asb_worker.py"       # runs in AeroSandbox/.venv: it may import proptimiser
    for py in [*SRC.rglob("*.py"), *(f for d in spokes for f in d.glob("*.py"))]:
        text = py.read_text(encoding="utf-8")
        assert not (re.compile(r"^\s*(import|from)\s+(aerolink|propalyser)", re.I | re.M) if py == worker else pattern).search(text), py
