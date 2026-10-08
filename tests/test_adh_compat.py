"""ADH compatibility. Method follows ADH's own tests: Pydantic validation, import checks, schema export."""
import copy
import json
import re
from pathlib import Path

import pytest

from aeroplan.config import compile_yaml, roundtrip_ok
from aeroplan.muas.node import adh_wbs_numbers, validate_node
from aeroplan.schema_export import export_schemas

SRC = Path(__file__).resolve().parents[1] / "src" / "aeroplan"


@pytest.fixture
def node(prov):
    return {
        "wbs_no": "1.2.2.3", "name": "Wing", "description": "synthetic wing",
        "subcomponents": [{"wbs_no": "1.2.2.3.3", "name": "Ailerons", "muas": {"ext_version": "0.1.0", "instance": "ail_L"}}],
        "muas": {
            "ext_version": "0.1.0", "instance": "wing_main", "fidelity": "L1", "provenance": prov,
            "mass_properties": {"mass": {"value": 1, "units": "kg"}, "cg": {"xyz": [0, 0, 0]},
                                "source": "estimate", "placeholder": True},
        },
    }


def test_node_validates(node):
    validate_node(node)


def test_wbs_numbers_come_from_upstream():
    nums = adh_wbs_numbers()
    assert {"1.2.2.3", "1.2.2.3.3", "1.2.3.9", "1.2.3.11"} <= nums


def test_invented_wbs_number_rejected(node):
    node["wbs_no"] = "9.9.9"
    with pytest.raises(ValueError):
        validate_node(node)


def test_typo_in_muas_key_rejected(node):
    node["muas"]["mass_propertes"] = {}
    with pytest.raises(Exception):
        validate_node(node)


def test_subcomponent_is_checked(node):
    node["subcomponents"][0]["wbs_no"] = "7.7"
    with pytest.raises(ValueError):
        validate_node(node)


def test_patched_adh_schema_exports():
    """Known upstream defect (brief section 1). Patch 0001 must fix it."""
    from aircraft_data_hierarchy.work_breakdown_structure.airframe import Component

    json.dumps(Component.model_json_schema())


def test_muas_schemas_export(tmp_path):
    files = export_schemas(tmp_path)
    assert len(files) == 10 and all(json.loads(f.read_text()) for f in files)


def test_committed_schema_is_current():
    committed = Path(__file__).resolve().parents[1] / "schema" / "v0.1.0"
    if not committed.exists():
        pytest.skip("schema not exported yet")
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        for f in export_schemas(Path(d)):
            assert (committed / f.name).read_text() == f.read_text(), f"{f.name} is stale: run `aeroplan schema`"


def test_yaml_to_json_roundtrip(tmp_path):
    y = tmp_path / "hand.yaml"
    y.write_text("# comment\nb: 2\na:\n  - 1\n  - {c: 3.5}\n", encoding="utf-8")
    out = compile_yaml(y, tmp_path / "hand.json")
    assert roundtrip_ok(y, out)
    assert out.read_text().index('"a"') < out.read_text().index('"b"')  # sorted keys


def test_imports():
    from aeroplan.adapters import REGISTRY
    from aeroplan.muas import dataset, mass, node, propulsion, reference, uncertainty  # noqa: F401

    assert {"config_yaml", "flow5", "cad"} <= set(REGISTRY)


def test_tool_independence():
    """ADH principle: data is separate from tools. AeroPlan imports no sibling repo."""
    pattern = re.compile(r"^\s*(import|from)\s+(aerolink|propalyser|proptimiser)", re.I | re.M)
    for py in SRC.rglob("*.py"):
        assert not pattern.search(py.read_text(encoding="utf-8")), py
