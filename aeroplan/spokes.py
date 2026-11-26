"""Spokes: one subpackage for each tool, `aeroplan/<tool>/`. A spoke moves data between its tool and the source tree
of an aircraft (`aircraft/<aircraft>/`). The subpackage name is the spoke name in lower case.

    aeroplan/aerosandbox/   initial sizing (the first source of a new aircraft)
    aeroplan/flow5/         geometry and aero analysis
    aeroplan/specsheet/     the Master Specification Sheet: weight log and CG sheet -> the mass model
    aeroplan/propalyser/    the propulsion system
    aeroplan/creo/          the CAD link (part meshes and their pose)
    aeroplan/openvsp/       geometry to and from an OpenVSP model
    aeroplan/daveml/        a published DAVE-ML model (for example the NASA F-16)
    aeroplan/ardupilot/     flight events (log, firmware, segments) and flight files (.parm, .waypoints, geofence)
    aeroplan/aerolink/      simulator export (the aerolink `.muas` package)

Each subpackage holds `spoke.py` (the code), `README.md` and a `settings/` folder for tool settings (committed). The raw
tool files of an aircraft are in `work/<tool>/<aircraft>/` at the repository root (git ignores `work/`). A spoke
module defines (`HOOKS`, checked by `check_spoke` when the spoke loads):

    NAME                         the spoke name in SPOKES. The build runs the spokes in SPOKES order
    ingest(doc, ctx)             read work/<aircraft>/ (and settings) and change the ADH document. Return a list of
                                 change lines, or None when this spoke has no input for the aircraft
    generate(doc, ctx)           optional: write tool input files from the document into work/<aircraft>/
    GENERATE_NEEDS_TREE          optional, default True: False lets `generate` run before the first build (doc is None)
    sweep(doc, ctx, **options)   optional: run the tool sweep
    export(doc, ctx, out)        optional: write tool files from the document into `out`
    setup(ctx, ...)              optional: make the tool runtime on this machine
    describe()                   optional: one line about the tool runtime (`aeroplan spokes`)

`python -m aeroplan new-spoke <Name>` writes the skeleton of a new spoke.

Only ADH data goes into the source tree. A spoke registers each raw file it read as an asset (`ctx.source_ref`) and
each table or model it made as a dataset (`ctx.add_dataset`).
"""
from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Iterable, List, Optional

from . import REPO_ROOT
from .assets import sha256_file  # noqa: F401  (spokes use it)

SPOKES = ("AeroSandbox", "flow5", "SpecSheet", "Propalyser", "CREO", "OpenVSP", "DAVEML", "ArduPilot", "Aerolink")


def folder_name(spoke: str) -> str:
    """The subpackage of a spoke below `aeroplan/` and its folder below `work/`: the spoke name in lower case."""
    return spoke.lower()


def repo_root() -> Path:
    """The AeroPlan repository root. Spokes need an editable install."""
    root = REPO_ROOT
    if not (root / "pyproject.toml").is_file():
        raise RuntimeError(f"{root} is not the AeroPlan repository root: install AeroPlan with `pip install -e .`")
    return root


@dataclass
class Context:
    """What a spoke gets: the aircraft name, its work folder and settings file, the aircraft in memory (`acft`,
    a source_tree.Aircraft), and the asset helpers."""

    aircraft: str
    root: Path
    spoke: str
    acft: Any = field(default=None, repr=False)

    @property
    def work(self) -> Path:
        return self.root / "work" / folder_name(self.spoke) / self.aircraft

    @property
    def settings_file(self) -> Path:
        return self.root / "aeroplan" / folder_name(self.spoke) / "settings" / f"{self.aircraft}.yaml"

    def settings(self) -> Dict[str, Any]:
        """The tool settings of this aircraft (YAML, committed), or an empty dict."""
        import yaml

        f = self.settings_file
        return yaml.safe_load(f.read_text(encoding="utf-8")) or {} if f.is_file() else {}

    def source_ref(self, path: Path, role: str, note: Optional[str] = None, url: Optional[str] = None) -> Dict[str, Any]:
        """Register a raw file of this spoke in the asset register and give its `SourceRef`."""
        from .assets import register_file

        aid = register_file(self.acft.doc, path, self.root, tool=self.spoke, role=role, url=url, note=note)
        ref = {"tool": self.spoke, "asset": aid, "role": role}
        if note:
            ref["note"] = note
        return ref

    def add_dataset(self, item: Dict[str, Any], name: str, content: Any, *, role: str, dataset_role: str,
                    meta: Dict[str, Any], derived_from: Iterable[str] = (), **kw) -> str:
        """Register a dataset and point `item` at it (`muas.datasets`, one dataset for each role)."""
        from .assets import register_dataset, set_item_dataset

        aid = register_dataset(self.acft, name, content, tool=self.spoke, role=role, dataset_role=dataset_role,
                               meta=meta, derived_from=derived_from,
                               built_against=f"{self.aircraft}@{self.acft.version}", **kw)
        set_item_dataset(item, dataset_role, aid)
        return aid

    def dataset(self, ref: str) -> Any:
        from .assets import dataset

        return dataset(self.acft, ref)


#: hook -> (required, the first parameters it must take)
HOOKS: Dict[str, tuple] = {
    "ingest": (True, ("doc", "ctx")),
    "generate": (False, ("doc", "ctx")),
    "sweep": (False, ("doc", "ctx")),
    "export": (False, ("doc", "ctx", "out")),
    "setup": (False, ("ctx",)),
    "describe": (False, ()),
}


class SpokeError(TypeError):
    """A spoke module breaks the spoke contract (the module docstring)."""


def check_spoke(name: str, module: ModuleType) -> List[str]:
    """The faults of a spoke module against the contract. An empty list means the module is a good spoke."""
    faults = []
    if getattr(module, "NAME", None) != name:
        faults.append(f"NAME is {getattr(module, 'NAME', None)!r}, not {name!r}")
    for hook, (required, params) in HOOKS.items():
        fn = getattr(module, hook, None)
        if fn is None:
            if required:
                faults.append(f"no {hook}() function")
            continue
        if not callable(fn):
            faults.append(f"{hook} is not a function")
            continue
        got = tuple(inspect.signature(fn).parameters)[: len(params)]
        if got != params:
            faults.append(f"{hook}{tuple(inspect.signature(fn).parameters)} must start with {params}")
    if not isinstance(getattr(module, "GENERATE_NEEDS_TREE", True), bool):
        faults.append("GENERATE_NEEDS_TREE is not a bool")
    return faults


def load(name: str) -> ModuleType:
    """Import the spoke of a tool (the module `aeroplan.<tool>.spoke`) and check it against the spoke contract."""
    if name not in SPOKES:
        raise KeyError(f"unknown spoke {name!r} (spokes: {', '.join(SPOKES)})")
    module = importlib.import_module(f"aeroplan.{folder_name(name)}.spoke")
    faults = check_spoke(name, module)
    if faults:
        raise SpokeError(f"spoke {name} breaks the spoke contract (aeroplan/spokes.py): " + "; ".join(faults))
    return module


_SPOKE_TEMPLATE = '''"""{name} spoke: <the tool data> -> <the ADH items it writes>. See README.md."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from aeroplan.spokes import Context

NAME = "{name}"


def ingest(doc: Dict[str, Any], ctx: Context) -> Optional[List[str]]:
    """Read work/{folder}/<aircraft>/ and change the ADH document. Return the change lines, or None (no input)."""
    if not ctx.work.is_dir():
        return None
    raise NotImplementedError("write the ingest of the {name} spoke (read the rules: python -m aeroplan rules <file>)")
'''

_README_TEMPLATE = """# {name} spoke

What the tool is, and which ADH items the spoke writes.

| Item | Place |
|---|---|
| Input | `work/{folder}/<aircraft>/` |
| Settings | `settings/<aircraft>.yaml` |
| Writes | the ADH items and `muas` keys (each key has a row in `standards/adh/EXTENSIONS.md`) |
"""


def new_spoke(name: str, pkg: Path = REPO_ROOT / "aeroplan") -> List[Path]:
    """Write the skeleton of a new spoke (`aeroplan new-spoke`): the four parts that rule AP005 needs. The caller adds
    the name to SPOKES. Refuses a folder that exists."""
    folder = pkg / folder_name(name)
    if folder.exists():
        raise FileExistsError(f"{folder} exists")
    fmt = {"name": name, "folder": folder_name(name)}
    files = {
        folder / "__init__.py": f'"""The {name} spoke (`spoke.py`). See README.md."""\n',
        folder / "spoke.py": _SPOKE_TEMPLATE.format(**fmt),
        folder / "README.md": _README_TEMPLATE.format(**fmt),
        folder / "settings" / "README.md": f"# {name} settings\n\nOne file `<aircraft>.yaml` for each aircraft.\n",
    }
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return list(files)


def context(name: str, aircraft: str, acft: Any = None) -> Context:
    return Context(aircraft, repo_root(), name, acft)


def set_sources(item: Dict[str, Any], tool: str, refs: List[Dict[str, Any]]) -> None:
    """Replace the source pointers of one tool on an item, keep the pointers of the other tools."""
    m = item["muas"]
    keep = [r for r in m.get("sources") or [] if r["tool"] != tool]
    m["sources"] = keep + refs
