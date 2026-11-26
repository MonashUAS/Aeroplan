"""The source tree of an aircraft: `aircraft/<name>/`, committed to git. It is the single source of truth.

    aircraft/<name>/                the folder name is the aircraft name
      <wbs>.<key>.json              one file for each ADH node, without its child nodes. Subcomponents stay in the
                                    file of their node. 1.0.aircraft_system.json also holds `muas.package`: the kind
                                    (aircraft or flight-record) and the consumers (the packing profiles it serves)
      datasets/<name>.json          one file for each dataset of the asset register (the JSON value only: the
                                    metadata is in the register entry, 1.10.2.data_repository.json)

One file for each node and each dataset gives readable git diffs and merges. The write is deterministic: sorted
keys in the order the document holds them, two-space indent, LF, a newline at the end.

`muas.package` is a fact of the source tree, not of the ADH document: the reader moves it to `Aircraft.info`, and
the package keeps it in its manifest. The reader checks the hash of every dataset against its asset ID. A mismatch
stops the read. A file that is not a node file or a dataset also stops the read.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from . import REPO_ROOT, adh_doc, assets
from .muas.node import PackageInfo

KINDS = ("aircraft", "flight-record")
ROOT_FILE = "1.0.aircraft_system.json"
DATASETS = "datasets"
AIRCRAFT = "aircraft"


def aircraft_dir(name: str, root: Path = REPO_ROOT) -> Path:
    """The source tree folder of an aircraft: `<root>/aircraft/<name>/`. The only place that makes this path (AP009)."""
    return Path(root) / AIRCRAFT / name


def dataset_repo_path(aircraft: str, name: str) -> str:
    """The repository path of a dataset file, as the asset register names it."""
    return f"{AIRCRAFT}/{aircraft}/{DATASETS}/{name}.json"


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
        raise SourceTreeError(f"muas.package kind must be one of {KINDS}")
    (folder / DATASETS).mkdir(parents=True, exist_ok=True)
    written = []
    files = _node_files(acft.doc)
    root = files[ROOT_FILE]
    pkg = PackageInfo(kind=acft.info["kind"], consumers=list(acft.info.get("consumers") or []))
    root["muas"] = {**(root.get("muas") or {}), "package": pkg.model_dump()}
    for old in folder.glob("*.json"):
        if old.name not in files:
            old.unlink()
    for name, node in files.items():
        p = folder / name
        p.write_text(_dump(node), encoding="utf-8", newline="\n")
        written.append(p)
    names = {}
    for e in assets.register(acft.doc, create=False):
        if e["kind"] == "dataset":
            if e["id"] not in acft.datasets:
                raise SourceTreeError(f"dataset {e['name']} ({e['id']}) is in the register but not in memory")
            names[f"{e['name']}.json"] = acft.datasets[e["id"]]
    for old in (folder / DATASETS).glob("*.json"):
        if old.name not in names:
            old.unlink()
    for name, value in sorted(names.items()):
        p = folder / DATASETS / name
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
            raise SourceTreeError(f"{name}: the file name must be <wbs_no>.<ADH key>.json")
        by_wbs[wbs] = dict(node)
    if "1.0" not in by_wbs:
        raise SourceTreeError(f"{ROOT_FILE} is missing")
    for wbs in sorted(by_wbs, key=_wbs_key):
        if wbs == "1.0":
            continue
        path = tree[wbs]["path"]
        parent_wbs = adh_doc._by_path()[path[:-1]] if len(path) > 1 else "1.0"
        if parent_wbs not in by_wbs:
            raise SourceTreeError(f"node {wbs} has no parent node file ({parent_wbs})")
        by_wbs[parent_wbs][path[-1]] = by_wbs[wbs]
    return by_wbs["1.0"]


def exists(folder: Path) -> bool:
    """True when `folder` holds an aircraft source tree (its root node file)."""
    return (Path(folder) / ROOT_FILE).is_file()


def list_aircraft(root: Path) -> List[Path]:
    """The source trees below `<root>/aircraft/`, sorted by name."""
    return sorted(p for p in (Path(root) / "aircraft").iterdir() if p.is_dir() and exists(p))


def read(folder: Path) -> Aircraft:
    folder = Path(folder)
    if not exists(folder):
        raise SourceTreeError(f"{folder} is not an aircraft source tree (no {ROOT_FILE})")
    other = sorted(p.name for p in folder.iterdir() if not (p.suffix == ".json" and p.is_file()) and p.name != DATASETS)
    if other:
        raise SourceTreeError(f"{folder} holds files that are not node files or datasets: {other}")
    files = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))}
    pkg = PackageInfo.model_validate((files[ROOT_FILE].get("muas") or {}).pop("package", None) or {})
    doc = _assemble(files)
    acft = Aircraft(folder.name, doc, {}, {"name": folder.name, **pkg.model_dump()})
    for e in assets.register(doc, create=False):
        if e["kind"] != "dataset":
            continue
        p = folder / DATASETS / f"{e['name']}.json"
        if not p.is_file():
            raise SourceTreeError(f"{DATASETS}/{p.name} is missing (asset {e['id']})")
        value = json.loads(p.read_text(encoding="utf-8"))
        if assets.dataset_id(value) != e["id"]:
            raise SourceTreeError(f"{DATASETS}/{p.name}: the content hash is not {e['id']}. A dataset is never edited "
                                  "in place: a spoke writes a new one")
        acft.datasets[e["id"]] = value
    extra = {p.name for p in (folder / DATASETS).glob("*.json")} - \
            {f"{e['name']}.json" for e in assets.register(doc, create=False) if e["kind"] == "dataset"}
    if extra:
        raise SourceTreeError(f"{DATASETS}/ holds files that the register does not name: {sorted(extra)}")
    return acft
