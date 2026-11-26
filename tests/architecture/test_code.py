"""AP006 to AP012 and AP016 to AP019: the rules about code, data, schema and notebooks."""
from __future__ import annotations

import ast
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from archlib import PKG, ROOT, core_files, fail, py_files, ratchet, rel, tree

TESTS = ROOT / "tests"


def _chain(node: ast.AST) -> List[object]:
    """The keys of a chain of subscripts and .get/.setdefault/.pop calls, outermost last. A key that is not a constant
    is None."""
    keys: List[object] = []
    while True:
        if isinstance(node, ast.Subscript):
            keys.append(node.slice.value if isinstance(node.slice, ast.Constant) else None)
            node = node.value
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in ("get", "setdefault", "pop") and node.args):
            keys.append(node.args[0].value if isinstance(node.args[0], ast.Constant) else None)
            node = node.func.value
        else:
            return keys[::-1]


def _walk(path: Path):
    return ast.walk(tree(path))


# ------------------------------------------------------------------------------------------------------------ AP006
def test_ap006_the_repository_root_is_repo_root():
    found: Dict[str, List[str]] = defaultdict(list)
    for p in py_files(PKG, TESTS):
        if p == PKG / "__init__.py":
            continue
        for n in _walk(p):
            if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute) and n.value.attr == "parents":
                found[rel(p)].append(f"line {n.lineno}: .parents[...]")
            elif (isinstance(n, ast.Attribute) and n.attr == "parent" and isinstance(n.value, ast.Attribute)
                  and n.value.attr == "parent"):
                found[rel(p)].append(f"line {n.lineno}: .parent.parent")
    ratchet("AP006", found, "use aeroplan.REPO_ROOT (tests: the fixture or archlib.ROOT).")


# ------------------------------------------------------------------------------------------------------------ AP007
def test_ap007_each_muas_key_has_a_row_in_the_extension_register():
    from aeroplan.muas.node import MuasNodeExt, PackageInfo
    from aeroplan.muas.requirement import RequirementExt

    text = (ROOT / "standards" / "adh" / "EXTENSIONS.md").read_text(encoding="utf-8")
    rows = set(re.findall(r"^\| `([a-z_]+)` \|", text, re.M))
    keys = set(MuasNodeExt.model_fields) | set(RequirementExt.model_fields) | {"package"}
    assert set(PackageInfo.model_fields) == {"kind", "consumers"}
    fail("AP007", [f"muas key with no row: {k}" for k in sorted(keys - rows)]
         + [f"row for a key that does not exist: {k}" for k in sorted(rows - keys)],
         "add the row (what ADH has, why MUAS adds the key) to standards/adh/EXTENSIONS.md, or remove the stale row.")


# ------------------------------------------------------------------------------------------------------------ AP008
def test_ap008_only_the_fact_helpers_touch_the_adh_fact_fields():
    from aeroplan.adh_doc import FACTS

    pairs = {pair: name for name, f in FACTS.items() for pair in f["fields"]}
    owners = {pair: set(FACTS[name]["owners"]) for pair, name in pairs.items()}
    bad = []
    for p in py_files(PKG):
        seen = set()
        for n in _walk(p):
            keys = _chain(n)
            for a, b in zip(keys, keys[1:]):
                if (a, b) in pairs and rel(p) not in owners[(a, b)] and (n.lineno, a, b) not in seen:
                    seen.add((n.lineno, a, b))
                    f = FACTS[pairs[(a, b)]]
                    bad.append(f"{rel(p)}:{n.lineno} touches {a}.{b}: use {f['read']} or {f['write']}")
    fail("AP008", bad, "read and write the fact through its helper in adh_doc.FACTS.")


# ------------------------------------------------------------------------------------------------------------ AP009
def test_ap009_only_source_tree_makes_a_path_into_aircraft():
    allowed = {"aeroplan/source_tree.py"}
    bad = []
    for p in py_files(PKG):
        if rel(p) in allowed:
            continue
        for n in _walk(p):
            if (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) and isinstance(n.right, ast.Constant)
                    and n.right.value == "aircraft"):
                bad.append(f"{rel(p)}:{n.lineno} makes a path / \"aircraft\"")
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("aircraft/"):
                bad.append(f"{rel(p)}:{n.lineno} holds the path {n.value!r}")
    fail("AP009", bad, "use source_tree.aircraft_dir(<aircraft>, root) and source_tree.read / write.")


# ------------------------------------------------------------------------------------------------------------ AP010
_DEG_CALLS = {"degrees", "radians", "deg2rad", "rad2deg"}


def _is_180(n: ast.AST) -> bool:
    return isinstance(n, ast.Constant) and n.value in (180, 180.0)


def _is_pi(n: ast.AST) -> bool:
    return isinstance(n, ast.Attribute) and n.attr == "pi"


def test_ap010_the_core_converts_no_degrees():
    found: Dict[str, List[str]] = defaultdict(list)
    for p in core_files():
        for n in _walk(p):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _DEG_CALLS:
                found[rel(p)].append(f"line {n.lineno}: {n.func.attr}()")
            elif isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Mult, ast.Div)) and (
                    (_is_180(n.left) and _is_pi(n.right)) or (_is_pi(n.left) and _is_180(n.right))):
                found[rel(p)].append(f"line {n.lineno}: 180 and pi")
    ratchet("AP010", found, "keep radians in the core. Convert to degrees only in aeroplan/<tool>/, at the tool edge.")


# ------------------------------------------------------------------------------------------------------------ AP011
CONSTANTS = {9.80665: "G0", 9.81: "G0 (9.80665)", 0.0254: "INCH_M"}


def test_ap011_a_physical_constant_is_written_once():
    found: Dict[str, List[str]] = defaultdict(list)
    for p in py_files(PKG):
        if rel(p) == "aeroplan/constants.py":
            continue
        for n in _walk(p):
            if isinstance(n, ast.Constant) and type(n.value) is float and n.value in CONSTANTS:
                found[rel(p)].append(f"line {n.lineno}: {n.value} (use constants.{CONSTANTS[n.value]})")
    ratchet("AP011", found, "import the value from aeroplan/constants.py.")


# ------------------------------------------------------------------------------------------------------------ AP012
_ROOT_NAMES = {"ROOT", "REPO", "REPO_ROOT", "SRC", "HERE"}
_DATA_PARTS = {"aircraft", "settings", "data", "notebooks"}


def _path_parts(n: ast.AST):
    """(the base of a path made with `/`, the constant parts after it)."""
    parts: List[object] = []
    while isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
        parts.append(n.right.value if isinstance(n.right, ast.Constant) else None)
        n = n.left
    return n, parts[::-1]


def _is_repo_root(base: ast.AST) -> bool:
    text = ast.unparse(base)
    return (isinstance(base, ast.Name) and base.id in _ROOT_NAMES) or "parents" in text or "REPO_ROOT" in text


def test_ap012_tests_read_no_committed_data():
    found: Dict[str, List[str]] = defaultdict(list)
    for p in py_files(TESTS):
        if p.name == "test_aircraft_files.py" or "architecture" in p.parts:
            continue
        inner = {id(n.left) for n in _walk(p) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)}
        for n in _walk(p):
            if not (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)) or id(n) in inner:
                continue                                    # only the outermost `/` of each path
            base, parts = _path_parts(n)
            if _is_repo_root(base) and _DATA_PARTS & set(parts):
                found[rel(p)].append(f"line {n.lineno}: {ast.unparse(n)}")
    ratchet("AP012", found, "make a synthetic copy of the data in the test (tmp_path). Tests use synthetic numbers only.")


# ------------------------------------------------------------------------------------------------------------ AP016
def test_ap016_the_committed_schema_is_the_export(tmp_path):
    from aeroplan import MUAS_SCHEMA_VERSION
    from aeroplan.schema_export import export_schemas

    committed = ROOT / "standards" / "schema" / f"v{MUAS_SCHEMA_VERSION}"
    files = export_schemas(tmp_path)
    bad = [f"{f.name} differs" for f in files
           if not (committed / f.name).is_file()
           or (committed / f.name).read_text(encoding="utf-8") != f.read_text(encoding="utf-8")]
    extra = {p.name for p in committed.glob("*.json")} - {f.name for f in files}
    fail("AP016", bad + [f"{n} has no model" for n in sorted(extra)],
         "raise MUAS_SCHEMA_VERSION when a model changed, then run `python -m aeroplan schema --out standards/schema`.")


def test_ap016_a_changed_schema_has_a_new_version():
    """A schema folder that main already has must not change: a model change needs a new MUAS_SCHEMA_VERSION."""
    from aeroplan import MUAS_SCHEMA_VERSION

    folder = f"standards/schema/v{MUAS_SCHEMA_VERSION}"
    ref = subprocess.run(["git", "rev-parse", "--verify", "-q", "origin/main"], cwd=ROOT, capture_output=True, text=True)
    if ref.returncode:
        import pytest

        pytest.skip("no origin/main to compare with (CI fetches it)")
    diff = subprocess.run(["git", "diff", "--name-only", "origin/main", "--", folder], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.split()
    on_main = subprocess.run(["git", "ls-tree", "--name-only", "origin/main", folder + "/"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split()
    fail("AP016", [f"{f} changed, but main has v{MUAS_SCHEMA_VERSION}" for f in diff if on_main],
         "raise MUAS_SCHEMA_VERSION in aeroplan/__init__.py, then export the schema again.")


# ------------------------------------------------------------------------------------------------------------ AP017
def test_ap017_notebooks_have_outputs_stay_small_and_use_python3():
    notebooks = sorted(PKG.glob("*/notebooks/*.ipynb"))
    assert notebooks, "no notebook in aeroplan/<tool>/notebooks"
    bad = []
    for nb in notebooks:
        if nb.stat().st_size >= 5_000_000:
            bad.append(f"{rel(nb)} is {nb.stat().st_size / 1e6:.1f} MB: strip the widget state and big outputs")
        d = json.loads(nb.read_text(encoding="utf-8"))
        if not any(c.get("outputs") for c in d["cells"] if c["cell_type"] == "code"):
            bad.append(f"{rel(nb)} has no outputs: run it and save it")
        if "widgets" in d.get("metadata", {}):
            bad.append(f"{rel(nb)} holds a widget state")
        if d.get("metadata", {}).get("kernelspec", {}).get("name") != "python3":
            bad.append(f"{rel(nb)}: the kernelspec name is not python3 (the .venv kernel)")
    fail("AP017", bad, "run the notebook in the repository .venv and save it with its outputs.")


# ------------------------------------------------------------------------------------------------------------ AP018
def _params(o, path=""):
    if isinstance(o, dict):
        if isinstance(o.get("params"), dict):
            for k, v in o["params"].items():
                yield f"{path}/params/{k}", v
        for k, v in o.items():
            if k != "params":
                yield from _params(v, f"{path}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _params(v, f"{path}[{i}]")


def test_ap018_each_model_param_names_its_source():
    bad = []
    for f in sorted(PKG.glob("*/settings/*.json")):
        for path, v in _params(json.loads(f.read_text(encoding="utf-8")).get("components", {}), "components"):
            value = v.get("value") if isinstance(v, dict) else v
            if isinstance(value, (int, float)) and not isinstance(value, bool) and not str(v.get("source") or "").strip():
                bad.append(f"{rel(f)}: {path} = {value} has no source")
    fail("AP018", bad, "give the param a source. A stand-in value gets placeholder: true and still names its source.")


# ------------------------------------------------------------------------------------------------------------ AP019
def test_ap019_no_big_file_in_the_source_tree():
    bad = [f"{rel(p)} is {p.stat().st_size / 1e6:.1f} MB" for p in sorted((ROOT / "aircraft").rglob("*"))
           if p.is_file() and p.stat().st_size > 1_000_000]
    fail("AP019", bad, "keep the big file in work/<tool>/<aircraft>/ and register it as an asset (ADR 0003).")
