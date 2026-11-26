"""AP001 to AP004: the import rules of the hub and the spokes. The tool list comes from `spokes.SPOKES`."""
from archlib import PKG, TOOLS, core_files, fail, imports, py_files, rel, tool_of

SIBLINGS = ("aerolink", "propalyser", "proptimiser")
ASB = PKG / "aerosandbox"
#: The AeroSandbox model files: every module of the tool but the spoke (ADR 0028)
ASB_MODEL = [p for p in py_files(ASB) if p.parent == ASB and p.name not in ("spoke.py", "__init__.py")]


def _tool_imported(name: str):
    parts = name.split(".")
    return parts[1] if parts[0] == "aeroplan" and len(parts) > 1 and parts[1] in TOOLS else None


def test_ap001_the_core_imports_no_tool_package():
    bad = [f"{rel(p)}:{line} imports {name}" for p in core_files() for name, _, line in imports(p) if _tool_imported(name)]
    fail("AP001", bad, "move the code that needs the tool into aeroplan/<tool>/, or move a tool-neutral form into the core.")


def test_ap002_a_tool_imports_no_other_tool():
    bad = []
    for p in py_files(PKG):
        own = tool_of(p)
        if own:
            bad += [f"{rel(p)}:{line} imports {name}" for name, _, line in imports(p)
                    if _tool_imported(name) not in (None, own)]
    fail("AP002", bad, "move the shared code into the core (aeroplan/*.py) and import it from there.")


def test_ap003_no_import_of_a_sibling_repository():
    bad = []
    for p in py_files(PKG):
        allowed = {"proptimiser"} if p in ASB_MODEL else set()
        bad += [f"{rel(p)}:{line} imports {name}" for name, _, line in imports(p)
                if name.split(".")[0] in SIBLINGS and name.split(".")[0] not in allowed]
    fail("AP003", bad, "copy the data by hand (ADR 0036). AeroPlan imports no sibling repository.")


def test_ap004_the_aerosandbox_model_reads_the_tree_in_one_place():
    assert {p.name for p in ASB_MODEL} >= {"component.py", "model.py"}, "the AeroSandbox model files moved"
    bad = []
    for p in ASB_MODEL:
        for name, fn, line in imports(p):
            if name == "aeroplan.spokes" or name.startswith("aeroplan.spokes."):
                bad.append(f"{rel(p)}:{line} imports {name}")
            if name.endswith("source_tree") and (p.name, fn) != ("component.py", "base_document"):
                bad.append(f"{rel(p)}:{line} reads the source tree in {fn or 'the module body'}")
    fail("AP004", bad, "read the base aircraft through component.base_document only.")


def test_ap020_the_openvsp_worker_imports_only_openvsp_numpy_and_the_standard_library():
    import sys

    worker = PKG / "openvsp" / "vsp_worker.py"
    allowed = {"openvsp", "numpy", "__future__"} | set(sys.stdlib_module_names)
    bad = [f"{rel(worker)}:{line} imports {name}" for name, _, line in imports(worker)
           if name.split(".")[0] not in allowed]
    fail("AP020", bad, "the worker runs in the OpenVSP Python, which has no other package (ADR 0011).")
