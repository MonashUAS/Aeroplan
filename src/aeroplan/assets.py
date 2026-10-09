"""The asset register (1.10.2 DataRepository `muas.assets`) and the datasets it names.

    register_file(doc, path, root, ...)          a raw file (CAD, tool file, log) -> its asset ID
    register_dataset(acft, name, content, ...)   a dataset (JSON value) -> its asset ID
    dataset(acft, ref)                           the JSON value of a dataset reference (`asset:sha256:<h>#/path`)
    fetch(entry, root)                           the local path of a linked file, hash checked

The ID of a file is the sha256 of its bytes. The ID of a dataset is the sha256 of its canonical JSON (sorted keys,
no spaces, UTF-8). So an ID changes when the content changes, and a dataset is never edited in place: a change
gives a new dataset.
"""
from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import adh_doc

PREFIX = "asset:sha256:"
REGISTER_NODE = "1.10.2"


class AssetError(ValueError):
    """An asset is missing, or its bytes do not match its hash."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def asset_id(sha: str) -> str:
    return PREFIX + sha


def sha_of(aid: str) -> str:
    if not aid.startswith(PREFIX) or len(aid) != len(PREFIX) + 64:
        raise AssetError(f"{aid!r} is not an asset ID")
    return aid[len(PREFIX):]


def split_ref(ref: str) -> Tuple[str, str]:
    """(asset ID, JSON pointer) of a reference `asset:sha256:<h>#/<path>`. The pointer is '' for the whole value."""
    aid, _, frag = ref.partition("#")
    sha_of(aid)
    return aid, frag


def clean(value: Any) -> Any:
    """A JSON value without None (a dataset holds no None, see aeroplan.h5json)."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def dataset_id(content: Any) -> str:
    return asset_id(sha256_bytes(canonical_json(content)))


def register(doc: Dict[str, Any], create: bool = True) -> List[Dict[str, Any]]:
    """The register list of the document (made when it is missing and `create`)."""
    if not create and not adh_doc.has_node(doc, REGISTER_NODE):
        return []
    n = adh_doc.node(doc, REGISTER_NODE, create=create)
    return adh_doc.muas(n, "data_repository").setdefault("assets", [])


def entry(doc: Dict[str, Any], aid: str) -> Dict[str, Any]:
    for e in register(doc, create=False):
        if e["id"] == aid:
            return e
    raise AssetError(f"{aid} is not in the asset register (1.10.2)")


def _put(doc: Dict[str, Any], new: Dict[str, Any]) -> str:
    """Add an entry, or update the entry with the same ID. A name names one asset only: an older asset of the same
    name leaves the register (the content changed, so the dataset or file is a new one)."""
    from .muas.assets import Asset

    Asset.model_validate(new)
    reg = register(doc)
    reg[:] = [e for e in reg if e["name"] != new["name"] or e["id"] == new["id"]]
    for i, e in enumerate(reg):
        if e["id"] == new["id"]:
            if e["name"] != new["name"]:
                raise AssetError(f"{new['id']} is registered as {e['name']!r}, not {new['name']!r}")
            reg[i] = new
            return new["id"]
    reg.append(new)
    reg.sort(key=lambda e: e["name"])
    return new["id"]


def register_file(doc: Dict[str, Any], path: Path, root: Path, *, tool: str, role: str,
                  url: Optional[str] = None, member: Optional[str] = None, derived_from: Iterable[str] = (),
                  note: Optional[str] = None, name: Optional[str] = None) -> str:
    """Register a raw file. Its location is its path in the repository (and `url`, with the `member` of a ZIP
    archive at the URL, when it has one)."""
    path = Path(path)
    sha = sha256_file(path)
    locs = []
    try:
        locs.append({"repo": path.resolve().relative_to(Path(root).resolve()).as_posix()})
    except ValueError:
        if url is None:
            raise AssetError(f"{path} is outside the repository and has no URL: it cannot be fetched again")
    if url:
        locs.append({"url": url, **({"member": member} if member else {})})
    e = {"id": asset_id(sha), "kind": "file", "name": name or f"{tool}.{path.name}".replace(" ", "_"),
         "role": role, "tool": tool,
         "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
         "size": path.stat().st_size, "locations": locs, "derived_from": sorted(set(derived_from))}
    if note:
        e["note"] = note
    return _put(doc, e)


def register_dataset(acft, name: str, content: Any, *, tool: str, role: str, dataset_role: str,
                     meta: Dict[str, Any], derived_from: Iterable[str] = (), built_against: Optional[str] = None,
                     reference: Optional[List[Dict[str, Any]]] = None, note: Optional[str] = None) -> str:
    """Register a dataset of the aircraft `acft` (source_tree.Aircraft) and keep its content in `acft.datasets`."""
    content = clean(content)
    data = canonical_json(content)
    aid = asset_id(sha256_bytes(data))
    e = {"id": aid, "kind": "dataset", "name": name, "role": role, "tool": tool,
         "media_type": "application/json", "size": len(data),
         "locations": [{"repo": f"aircraft/{acft.name}/datasets/{name}.json"}],
         "derived_from": sorted(set(derived_from)), "dataset": meta, "dataset_role": dataset_role}
    if built_against:
        e["built_against"] = built_against
    if reference:
        e["reference"] = reference
    if note:
        e["note"] = note
    _put(acft.doc, e)
    acft.datasets[aid] = content
    acft.prune()
    return aid


def resolve(value: Any, pointer: str) -> Any:
    """The part of a JSON value at a JSON pointer ('' or '/a/0/b')."""
    if not pointer:
        return value
    if not pointer.startswith("/"):
        raise AssetError(f"{pointer!r} is not a JSON pointer")
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def dataset(acft, ref: str) -> Any:
    aid, ptr = split_ref(ref)
    if aid not in acft.datasets:
        raise AssetError(f"the dataset {aid} is not on this machine (it is linked: fetch the source tree)")
    return resolve(acft.datasets[aid], ptr)


def item_dataset(item: Dict[str, Any], role: str) -> Optional[Dict[str, Any]]:
    """The dataset reference of `role` on an item, or None."""
    for d in (item.get("muas") or {}).get("datasets") or []:
        if d["role"] == role:
            return d
    return None


def set_item_dataset(item: Dict[str, Any], role: str, aid: str) -> None:
    refs = [d for d in item["muas"].get("datasets") or [] if d["role"] != role]
    item["muas"]["datasets"] = refs + [{"role": role, "ref": aid}]


def referenced(doc: Dict[str, Any]) -> List[str]:
    """Every asset ID that an item of the document names (sources, datasets, meshes, flight records)."""
    out: List[str] = []

    def scan(v):
        if isinstance(v, dict):
            for x in v.values():
                scan(x)
        elif isinstance(v, list):
            for x in v:
                scan(x)
        elif isinstance(v, str) and v.startswith(PREFIX):
            out.append(v.partition("#")[0])

    for _, item, _ in adh_doc.iter_nodes(doc):
        m = dict(item.get("muas") or {})
        reg = m.pop("assets", None) or []
        scan(m)
        for e in reg:
            scan(e.get("derived_from"))
    return out


def collect(doc: Dict[str, Any]) -> List[str]:
    """Remove the file assets that no item and no dataset names. Returns their names."""
    used = set(referenced(doc))
    reg = register(doc, create=False)
    gone = [e["name"] for e in reg if e["kind"] == "file" and e["id"] not in used]
    reg[:] = [e for e in reg if e["kind"] != "file" or e["id"] in used]
    return gone


def cache_dir() -> Path:
    return Path.home() / ".cache" / "aeroplan" / "assets"


def local_path(e: Dict[str, Any], root: Path) -> Optional[Path]:
    """The repository path of a file asset when it is on this machine with the registered hash, else None."""
    sha = sha_of(e["id"])
    for loc in e.get("locations") or []:
        if "repo" in loc:
            p = Path(root) / loc["repo"]
            if p.is_file() and sha256_file(p) == sha:
                return p
    p = cache_dir() / sha
    if p.is_file() and sha256_file(p) == sha:
        return p
    return None


def _download(url: str) -> Path:
    """A download of `url` in the cache (kept, so the members of one archive come from one download)."""
    p = cache_dir() / "downloads" / sha256_bytes(url.encode("utf-8"))
    if not p.is_file():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        tmp.replace(p)
    return p


def _zip_member(archive: Path, member: str) -> bytes:
    """The bytes of `member` in a ZIP archive. A path part that ends in .zip opens the ZIP inside."""
    data = archive.read_bytes()
    parts = member.split("/")
    i = 0
    while True:
        z = zipfile.ZipFile(io.BytesIO(data))
        j = next((k for k in range(i, len(parts)) if parts[k].lower().endswith(".zip")), None)
        name = "/".join(parts[i:(j + 1 if j is not None else len(parts))])
        data = z.read(name)
        if j is None or j == len(parts) - 1:
            return data
        i = j + 1


def fetch(e: Dict[str, Any], root: Path) -> Path:
    """The local path of a file asset: the repository copy, the cache, or a download into the cache. Every fetch
    checks the hash. Raises AssetError when no location gives the right bytes."""
    p = local_path(e, root)
    if p is not None:
        return p
    sha = sha_of(e["id"])
    errors = []
    for loc in e.get("locations") or []:
        if "url" not in loc:
            continue
        dest = cache_dir() / sha
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        try:
            if loc.get("member"):
                tmp.write_bytes(_zip_member(_download(loc["url"]), loc["member"]))
            else:
                with urllib.request.urlopen(loc["url"], timeout=60) as r, open(tmp, "wb") as f:
                    shutil.copyfileobj(r, f)
        except (OSError, KeyError, zipfile.BadZipFile) as err:
            errors.append(f"{loc['url']}: {err}")
            continue
        got = sha256_file(tmp)
        if got != sha:
            tmp.unlink()
            errors.append(f"{loc['url']}: sha256 {got} is not {sha}")
            continue
        tmp.replace(dest)
        return dest
    raise AssetError(f"{e['name']} ({e['id']}) is not on this machine" + (": " + "; ".join(errors) if errors else ""))
