"""The source tree of an aircraft: `aircraft/<name>/`, committed to git. It is the single source of truth.

    aircraft/<name>/
      aircraft.yaml                 name, kind (aircraft or flight-record), consumers (the packing profiles it serves)
      adh/<wbs>.<key>.json          one file for each ADH node, without its child nodes. Subcomponents stay in the
                                    file of their node.
      datasets/<name>.json          one file for each dataset of the asset register (the JSON value only: the
                                    metadata is in the register entry, adh/1.10.2.data_repository.json)

One file for each node and each dataset gives readable git diffs and merges. The write is deterministic: sorted
keys in the order the document holds them, two-space indent, LF, a newline at the end.

The reader checks the hash of every dataset against its asset ID. A mismatch stops the read.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

from . import adh_doc, assets

KINDS = ("aircraft", "flight-record")


class SourceTreeError(ValueError):
    """The source tree is incomplete, or a file does not match its hash."""


@dataclass
class Aircraft:
    """An aircraft in memory: the ADH document, the datasets of its register (ID -> JSON value), and its info."""

    name: str
    doc: Dict[str, Any]
    datasets: Dict[str, Any] = field(default_factory=dict)
    info: Dict[str, Any] = field(default_factory=dict)

    def prune(self) -> None:
        """Forget the datasets that the register no longer names."""
        keep = {e["id"] for e in assets.register(self.doc, create=False) if e["kind"] == "dataset"}
        for aid in list(self.datasets):
            if aid not in keep:
                del self.datasets[aid]

    @property
    def version(self) -> str:
        return ((self.doc.get("muas") or {}).get("build") or {}).get("version", "0.0.0")


def new(name: str, *, kind: str = "aircraft", consumers: List[str] = ("review", "archive"),
        description: str = "") -> Aircraft:
    doc = adh_doc.new_document(name.capitalize(), description or f"{name.capitalize()} aircraft system")
    return Aircraft(name, doc, {}, {"name": name, "kind": kind, "consumers": list(consumers)})


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _node_files(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """file name -> node without its child nodes."""
    out: Dict[str, Dict[str, Any]] = {}

    def walk(n, key):
        kids = set(adh_doc.child_keys(n))
        out[f"{n['wbs_no']}.{key}.json"] = {k: v for k, v in n.items() if k not in kids}
        for k in adh_doc.child_keys(n):
            walk(n[k], k)

    walk(doc, "aircraft_system")
    return out


def _wbs_key(wbs: str):
    return tuple(int(x) for x in wbs.split("."))


def write(acft: Aircraft, folder: Path) -> List[Path]:
    """Write the source tree. Files of nodes and datasets that the aircraft no longer has are removed."""
    folder = Path(folder)
    if acft.info.get("kind") not in KINDS:
        raise SourceTreeError(f"aircraft.yaml kind must be one of {KINDS}")
    (folder / "adh").mkdir(parents=True, exist_ok=True)
    (folder / "datasets").mkdir(parents=True, exist_ok=True)
    written = []
    info = folder / "aircraft.yaml"
    info.write_text(yaml.safe_dump(acft.info, sort_keys=False), encoding="utf-8", newline="\n")
    written.append(info)
    files = _node_files(acft.doc)
    for old in (folder / "adh").glob("*.json"):
        if old.name not in files:
            old.unlink()
    for name, node in files.items():
        p = folder / "adh" / name
        p.write_text(_dump(node), encoding="utf-8", newline="\n")
        written.append(p)
    names = {}
    for e in assets.register(acft.doc, create=False):
        if e["kind"] == "dataset":
            if e["id"] not in acft.datasets:
                raise SourceTreeError(f"dataset {e['name']} ({e['id']}) is in the register but not in memory")
            names[f"{e['name']}.json"] = acft.datasets[e["id"]]
    for old in (folder / "datasets").glob("*.json"):
        if old.name not in names:
            old.unlink()
    for name, value in sorted(names.items()):
        p = folder / "datasets" / name
        p.write_text(_dump(value), encoding="utf-8", newline="\n")
        written.append(p)
    return written


def _assemble(files: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    tree = adh_doc.wbs_tree()
    by_wbs: Dict[str, Dict[str, Any]] = {}
    for name, node in files.items():
        wbs = node.get("wbs_no")
        key = name[len(str(wbs)) + 1: -len(".json")] if wbs else None
        if wbs not in tree or not name.startswith(f"{wbs}.") or (tree[wbs]["path"][-1:] or ("aircraft_system",))[0] != key:
            raise SourceTreeError(f"adh/{name}: the file name must be <wbs_no>.<ADH key>.json")
        by_wbs[wbs] = dict(node)
    if "1.0" not in by_wbs:
        raise SourceTreeError("adh/1.0.aircraft_system.json is missing")
    for wbs in sorted(by_wbs, key=_wbs_key):
        if wbs == "1.0":
            continue
        path = tree[wbs]["path"]
        parent_wbs = adh_doc._by_path()[path[:-1]] if len(path) > 1 else "1.0"
        if parent_wbs not in by_wbs:
            raise SourceTreeError(f"adh: node {wbs} has no parent node file ({parent_wbs})")
        by_wbs[parent_wbs][path[-1]] = by_wbs[wbs]
    return by_wbs["1.0"]


def read(folder: Path) -> Aircraft:
    folder = Path(folder)
    info_p = folder / "aircraft.yaml"
    if not info_p.is_file():
        raise SourceTreeError(f"{folder} is not an aircraft source tree (no aircraft.yaml)")
    info = yaml.safe_load(info_p.read_text(encoding="utf-8")) or {}
    files = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted((folder / "adh").glob("*.json"))}
    doc = _assemble(files)
    acft = Aircraft(info.get("name") or folder.name, doc, {}, info)
    for e in assets.register(doc, create=False):
        if e["kind"] != "dataset":
            continue
        p = folder / "datasets" / f"{e['name']}.json"
        if not p.is_file():
            raise SourceTreeError(f"datasets/{p.name} is missing (asset {e['id']})")
        value = json.loads(p.read_text(encoding="utf-8"))
        if assets.dataset_id(value) != e["id"]:
            raise SourceTreeError(f"datasets/{p.name}: the content hash is not {e['id']}. A dataset is never edited "
                                  "in place: a spoke writes a new one")
        acft.datasets[e["id"]] = value
    extra = {p.name for p in (folder / "datasets").glob("*.json")} - \
            {f"{e['name']}.json" for e in assets.register(doc, create=False) if e["kind"] == "dataset"}
    if extra:
        raise SourceTreeError(f"datasets/ holds files that the register does not name: {sorted(extra)}")
    return acft
