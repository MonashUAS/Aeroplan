"""`aeroplan build <aircraft>`: run the spokes, check the ADH document, write the source tree `aircraft/<aircraft>/`.

Order: read the source tree (or start a new aircraft), let each spoke with input change the aircraft
(spokes.SPOKES order), check the document against upstream ADH, run the datum checks, record the build, then write
the source tree. A failed check writes nothing. `aeroplan pack` makes a `.muas` package from the source tree.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import adh_doc, assets, source_tree
from .consumers import missing_for_flight
from .spokes import SPOKES, context, load, repo_root


@dataclass
class BuildResult:
    path: Path
    version: str
    changes: Dict[str, List[str]] = field(default_factory=dict)
    skipped: List[str] = field(default_factory=list)
    datum: Any = None
    missing_for_flight: List[str] = field(default_factory=list)
    placeholders: List[str] = field(default_factory=list)


def aircraft_dir(aircraft: str) -> Path:
    return repo_root() / "aircraft" / aircraft


def load_aircraft(aircraft: str) -> source_tree.Aircraft:
    return source_tree.read(aircraft_dir(aircraft))


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=repo_root(), capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _next_version(doc: Dict[str, Any]) -> str:
    b = (doc.get("muas") or {}).get("build")
    if not b:
        return "0.1.0"
    major, minor, patch = (int(x) for x in b["version"].split("."))
    return f"{major}.{minor}.{patch + 1}"


def placeholders(doc: Dict[str, Any]) -> List[str]:
    """Every item path whose value is marked placeholder (a stand-in, not data)."""
    out: List[str] = []

    def scan(v, path):
        if isinstance(v, dict):
            if v.get("placeholder") is True:
                out.append(path)
            for k, x in v.items():
                scan(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                scan(x, f"{path}[{i}]")

    for path, item, _ in adh_doc.iter_nodes(doc):
        scan(item.get("muas") or {}, f"{path}.muas")
        for i, r in enumerate(item.get("requirements") or []):
            scan(r.get("muas") or {}, f"{path}.requirements[{i}].muas")
    return out


def build(aircraft: str, *, author: str, version: Optional[str] = None, new: bool = False,
          only: Optional[List[str]] = None, dry_run: bool = False,
          consumers: Optional[List[str]] = None) -> BuildResult:
    """Build the source tree `aircraft/<aircraft>/`. Raises ValueError (and writes nothing) when a check fails."""
    from .datum import datum_checks

    if not author.strip():
        raise ValueError("the build needs an author (a person's name)")
    folder = aircraft_dir(aircraft)
    if new or not (folder / "aircraft.yaml").is_file():
        acft = source_tree.new(aircraft, consumers=consumers or ["review", "archive"])
    else:
        acft = source_tree.read(folder)
        if consumers:
            acft.info["consumers"] = consumers
    version = version or _next_version(acft.doc)
    res = BuildResult(folder, version)
    for name in SPOKES:
        if only and name not in only:
            continue
        spoke = load(name)
        changes = spoke.ingest(acft.doc, context(name, aircraft, acft))
        if changes is None:
            res.skipped.append(name)
        else:
            res.changes[name] = changes
    acft.prune()
    gone = assets.collect(acft.doc)
    if gone:
        res.changes["asset register"] = [f"removed {n} (no item names it)" for n in gone]
    res.placeholders = placeholders(acft.doc)
    rec = {"aeroplan_commit": _git("rev-parse", "HEAD") or "unknown",
           "aeroplan_dirty": bool(_git("status", "--porcelain", "--", "src", *SPOKES)),
           "built": date.today().isoformat(), "author": author, "version": version,
           "spokes": {k: f"{len(v)} changes" for k, v in res.changes.items()},
           "placeholder_items": res.placeholders}
    adh_doc.muas(acft.doc, "aircraft_system")["build"] = rec
    adh_doc.normalize(acft.doc)
    adh_doc.validate_document(acft.doc)
    res.datum = datum_checks(acft.doc, repo_root())
    if not res.datum.ok:
        raise ValueError("datum check failed, nothing written:\n" + res.datum.text())
    res.missing_for_flight = missing_for_flight(acft.doc)
    if not dry_run:
        source_tree.write(acft, folder)
    return res


def generate(spoke_name: str, aircraft: str) -> List[Path]:
    """Write the tool input files of a spoke from the source tree."""
    spoke = load(spoke_name)
    if not hasattr(spoke, "generate"):
        raise ValueError(f"the spoke {spoke_name} has no generate step")
    if getattr(spoke, "GENERATE_NEEDS_TREE", True) is False and not (aircraft_dir(aircraft) / "aircraft.yaml").is_file():
        return spoke.generate(None, context(spoke_name, aircraft))      # a download for an aircraft not built yet
    acft = load_aircraft(aircraft)
    return spoke.generate(acft.doc, context(spoke_name, aircraft, acft))


def sweep(spoke_name: str, aircraft: str, **options: Any) -> Dict[str, Any]:
    """Run the tool sweep of a spoke on the source tree (flow5: the flow5 runner). Returns the spoke result."""
    spoke = load(spoke_name)
    if not hasattr(spoke, "sweep"):
        raise ValueError(f"the spoke {spoke_name} has no sweep step")
    acft = load_aircraft(aircraft)
    return spoke.sweep(acft.doc, context(spoke_name, aircraft, acft), **options)


def export(spoke_name: str, aircraft: str, out: Path) -> List[Path]:
    """Write the tool files of a spoke (for example the Aerolink package) into `out`."""
    spoke = load(spoke_name)
    if not hasattr(spoke, "export"):
        raise ValueError(f"the spoke {spoke_name} has no export step")
    acft = load_aircraft(aircraft)
    return spoke.export(acft.doc, context(spoke_name, aircraft, acft), Path(out))
