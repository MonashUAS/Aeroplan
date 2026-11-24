"""ADH compatibility. Method follows ADH's own tests: Pydantic validation, import checks, schema export."""
import json
import re
from pathlib import Path

import pytest

from aeroplan import MUAS_SCHEMA_VERSION, adh_doc
from aeroplan.schema_export import export_schemas

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "aeroplan"


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

    committed = Path(__file__).resolve().parents[1] / "standards" / "schema" / f"v{MUAS_SCHEMA_VERSION}"
    if not committed.exists():
        pytest.skip("schema not exported yet")
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        for f in export_schemas(Path(d)):
            assert (committed / f.name).read_text() == f.read_text(), f"{f.name} is stale: run `aeroplan schema`"


def test_imports():
    from aeroplan import adh_doc, assets, build, checks, consumers, daveml_adh, gltf, h5json, package, source_tree, spokes  # noqa: F401,E501
    from aeroplan.muas import aircraft, assets, dataset, flight, mass, node, propulsion, reference, uncertainty  # noqa: F401,F811,E501


def test_tool_independence():
    """ADH principle: data is separate from tools. AeroPlan imports no sibling repo."""
    pattern = re.compile(r"^\s*(import|from)\s+(aerolink|propalyser|proptimiser)", re.I | re.M)
    # These modules run in aeroplan/aerosandbox/.venv, not in AeroPlan: they may import proptimiser
    workers = {SRC / "aerosandbox" / name for name in ("model.py", "component.py", "mission.py", "optimise.py", "result.py",
                                                       "plot.py", "window.py")}
    for py in (p for p in SRC.rglob("*.py") if ".venv" not in p.parts):
        text = py.read_text(encoding="utf-8")
        assert not (re.compile(r"^\s*(import|from)\s+(aerolink|propalyser)", re.I | re.M) if py in workers else pattern).search(text), py


def test_every_muas_key_has_a_row_in_the_extension_register():
    """ADR 0027: standards/adh/EXTENSIONS.md says, for each muas key, what ADH has and why MUAS adds the key. A new key
    needs a row before it goes in. A row for a key that is gone is stale."""
    from aeroplan.muas.node import MuasNodeExt, PackageInfo
    from aeroplan.muas.requirement import RequirementExt

    text = (ROOT / "standards" / "adh" / "EXTENSIONS.md").read_text(encoding="utf-8")
    rows = set(re.findall(r"^\| `([a-z_]+)` \|", text, re.M))
    keys = set(MuasNodeExt.model_fields) | set(RequirementExt.model_fields) | {"package"}
    assert set(PackageInfo.model_fields) == {"kind", "consumers"}
    assert keys - rows == set(), f"muas keys with no row in EXTENSIONS.md: {sorted(keys - rows)}"
    assert rows - keys == set(), f"EXTENSIONS.md rows for keys that do not exist: {sorted(rows - keys)}"


TOOLS = ("aerolink", "aerosandbox", "ardupilot", "creo", "daveml", "flow5", "openvsp", "propalyser", "specsheet")


def _imports(py: Path):
    """(module name, the function that holds the import or None) of each import of a file."""
    import ast

    out = []

    def walk(node, fn):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, child.name)
                continue
            if isinstance(child, ast.Import):
                out.extend((a.name, fn) for a in child.names)
            elif isinstance(child, ast.ImportFrom):
                base = "." * child.level + (child.module or "")
                sep = "." if child.module else ""
                out.extend([(base, fn)] + [(base + sep + a.name, fn) for a in child.names])
            walk(child, fn)

    walk(ast.parse(py.read_text(encoding="utf-8")), None)
    return out


def test_core_code_imports_no_tool_package():
    """ADR 0025: aeroplan/<tool>/ uses the core. The core (aeroplan/*.py, aeroplan/muas/) never imports a tool package."""
    core = [*SRC.glob("*.py"), *(SRC / "muas").glob("*.py")]
    for py in core:
        for name, _ in _imports(py):
            parts = name.lstrip(".").split(".")
            tool = parts[1] if parts[0] == "aeroplan" and len(parts) > 1 else (parts[0] if name.startswith(".") else None)
            assert tool not in TOOLS, f"{py.name} imports the tool package {name}"


def test_the_aerosandbox_model_reads_the_source_tree_in_one_place():
    """ADR 0028: the model files of aeroplan/aerosandbox read the source tree only in component.base_document, so a split
    into their own repository changes one function. They never import the spoke machinery."""
    workers = ("model.py", "component.py", "mission.py", "optimise.py", "result.py", "plot.py", "window.py")
    for name in workers:
        for mod, fn in _imports(SRC / "aerosandbox" / name):
            if mod.endswith("spokes") or ".spokes." in mod:
                raise AssertionError(f"aerosandbox/{name} imports {mod}")
            if mod.endswith("source_tree"):
                assert (name, fn) == ("component.py", "base_document"), f"aerosandbox/{name} reads the tree in {fn}"
