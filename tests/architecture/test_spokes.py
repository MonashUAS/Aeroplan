"""AP005: the shape of each spoke. The spoke list is `spokes.SPOKES`. The contract is `spokes.check_spoke`."""
import importlib

from archlib import PKG, fail

from aeroplan.spokes import SPOKES, check_spoke, folder_name

#: The subpackages of aeroplan/ that are core, not a tool (ADR 0025)
CORE_PACKAGES = {"muas"}


def test_ap005_each_spoke_has_its_folder_and_keeps_the_contract():
    bad = []
    for name in SPOKES:
        folder = PKG / folder_name(name)
        for part, is_dir in (("__init__.py", False), ("spoke.py", False), ("README.md", False), ("settings", True)):
            p = folder / part
            if not (p.is_dir() if is_dir else p.is_file()):
                bad.append(f"aeroplan/{folder_name(name)}/{part} is missing")
        if (folder / "spoke.py").is_file():
            module = importlib.import_module(f"aeroplan.{folder_name(name)}.spoke")
            bad += [f"aeroplan/{folder_name(name)}/spoke.py: {f}" for f in check_spoke(name, module)]
    fail("AP005", bad, "run `python -m aeroplan new-spoke <Name>` for a new spoke, or fix the part that is named.")


def test_ap005_each_subpackage_is_a_spoke_or_core():
    tools = {folder_name(s) for s in SPOKES}
    bad = [f"aeroplan/{d.name}/ is a package but not a spoke in spokes.SPOKES and not core"
           for d in sorted(PKG.iterdir()) if (d / "__init__.py").is_file() and d.name not in tools | CORE_PACKAGES]
    fail("AP005", bad, "add the spoke name to spokes.SPOKES, or add a core package to CORE_PACKAGES in this test.")


def test_ap005_new_spoke_writes_a_spoke_that_keeps_the_contract(tmp_path):
    import importlib.util

    from aeroplan.spokes import new_spoke

    files = new_spoke("MyTool", tmp_path)
    folder = tmp_path / "mytool"
    assert {p.relative_to(folder).as_posix() for p in files} == {"__init__.py", "spoke.py", "README.md", "settings/README.md"}
    spec = importlib.util.spec_from_file_location("mytool_spoke", folder / "spoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert check_spoke("MyTool", module) == []
