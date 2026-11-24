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
module defines:

    NAME                         the build runs the spokes in SPOKES order
    ingest(doc, ctx)             read work/<aircraft>/ (and settings) and change the ADH document. Return a list of
                                 change lines, or None when this spoke has no input for the aircraft
    generate(doc, ctx)           optional: write tool input files from the document into work/<aircraft>/
    export(doc, ctx, out)        optional: write tool files from the document into `out`

Only ADH data goes into the source tree. A spoke registers each raw file it read as an asset (`ctx.source_ref`) and
each table or model it made as a dataset (`ctx.add_dataset`).
"""
from __future__ import annotations

import importlib
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


def load(name: str) -> ModuleType:
    """Import the spoke of a tool: the module `aeroplan.<tool>.spoke`."""
    if name not in SPOKES:
        raise KeyError(f"unknown spoke {name!r} (spokes: {', '.join(SPOKES)})")
    return importlib.import_module(f"aeroplan.{folder_name(name)}.spoke")


def context(name: str, aircraft: str, acft: Any = None) -> Context:
    return Context(aircraft, repo_root(), name, acft)


def set_sources(item: Dict[str, Any], tool: str, refs: List[Dict[str, Any]]) -> None:
    """Replace the source pointers of one tool on an item, keep the pointers of the other tools."""
    m = item["muas"]
    keep = [r for r in m.get("sources") or [] if r["tool"] != tool]
    m["sources"] = keep + refs
