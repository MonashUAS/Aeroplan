"""The `.muas` package: a ZIP archive that holds one immutable, hashed snapshot of an aircraft or a flight record.

    <name>-<version>-<profile>.muas      (ZIP64 when needed)
    ├── mimetype                        "application/vnd.muas+zip", the first entry, not compressed
    ├── manifest.json                   kind, format version, ADH fork, MUAS schema version, profile, consumers,
    │                                   the files {path, sha256, size, role, storage, asset}, package hash
    ├── aircraft.adh.json               the monolithic ADH tree, MUAS additions under "muas"
    ├── data/<name>.h5                  embedded datasets (not compressed in the ZIP, gzip by chunk inside HDF5)
    ├── assets/<sha256>-<name>          embedded raw files (archive profile)
    └── preview/aircraft.glb            the glTF view of the parts (aerolink: required, review, archive)

`pack` builds it from the source tree and never edits a package: a package of the same name with other bytes is
refused. `open_package` checks the mimetype, every file hash, the package hash, and the hash of every embedded
dataset. `unpack` writes the source tree back.

The package hash is the sha256 of the canonical JSON of the manifest `files` list (every file except mimetype and
manifest.json). The ZIP is deterministic: sorted entries, fixed time stamps.
"""
from __future__ import annotations

import copy
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import MUAS_SCHEMA_VERSION, adh_doc, assets, consumers, h5json, source_tree

MIMETYPE = "application/vnd.muas+zip"
FORMAT, FORMAT_VERSION = "muas", "2.0.0"
EPOCH = (1980, 1, 1, 0, 0, 0)
ADH_JSON, MANIFEST, PREVIEW = "aircraft.adh.json", "manifest.json", "preview/aircraft.glb"
PACK_FIELDS = ("storage", "package_path", "inline")


class PackageError(ValueError):
    """The package is not a `.muas` package, or a hash does not match."""


def adh_fork(root: Path) -> Dict[str, Any]:
    """The ADH copy that checks the package: upstream commit, the hash of the upstream tree and of each patch."""
    base = Path(root) / "packages" / "muas_adh"
    up = base / "upstream" / "src"
    h = []
    for p in sorted(up.rglob("*.py")):
        h.append(f"{p.relative_to(up).as_posix()} {assets.sha256_file(p)}")
    info = {}
    if (base / "upstream_commit.txt").is_file():
        for line in (base / "upstream_commit.txt").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition(":")
            info[k.strip()] = v.strip()
    return {"repository": info.get("repository"), "upstream_commit": info.get("commit"),
            "upstream_tree_sha256": assets.sha256_bytes("\n".join(h).encode()),
            "patches": [{"name": p.name, "sha256": assets.sha256_file(p)}
                        for p in sorted((base / "patches").glob("*.patch"))]}


def _zinfo(path: str, stored: bool) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(path, date_time=EPOCH)
    zi.compress_type = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    zi.create_system = 3
    zi.external_attr = 0o644 << 16
    return zi


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=1, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _preview(acft, root: Path) -> Optional[bytes]:
    from .gltf import write_glb
    from .parts import part_meshes

    ps = part_meshes(acft.doc, root)
    if not ps.parts:
        return None
    parts = []
    for name, p in ps.parts.items():
        ex = {"item": p.instance, "source": p.source}
        if p.hinge is not None:
            ex["hinge"] = p.hinge
        if p.material:
            ex["material"] = p.material
        if p.placeholder:
            ex["placeholder"] = True
        if p.alpha is not None:
            ex["alpha"] = p.alpha
        parts.append((name, p.tri, ex))
    return write_glb(parts, aircraft=acft.name)


def package_name(acft, profile: str) -> str:
    return f"{acft.name}-{acft.version}-{profile}.muas"


def pack(acft, profile: str, root: Path, out_dir: Path, *, supersedes: Optional[str] = None) -> Path:
    """Write `<out_dir>/<name>-<version>-<profile>.muas`. Raises PackageError when the profile needs an item that
    the aircraft lacks, or when a package of that name with other bytes exists."""
    problems = consumers.profile_problems(acft, profile)
    if problems:
        raise PackageError(f"cannot pack {acft.name} as {profile}:\n  " + "\n  ".join(problems))
    adh_doc.validate_document(acft.doc)
    doc = copy.deepcopy(acft.doc)
    payload: Dict[str, tuple] = {}            # path -> (bytes, role, asset id, stored)
    for e in assets.register(doc, create=False):
        t = consumers.tier(profile, e)
        if t == "embedded" and e["kind"] == "dataset":
            value = acft.datasets.get(e["id"])
            if value is None:
                raise PackageError(f"dataset {e['name']} is not on this machine")
            if e["size"] <= consumers.INLINE_MAX:
                e.update(storage="inline", inline=value)
                continue
            path = f"data/{e['name']}.h5"
            payload[path] = (h5json.to_bytes(value, attrs={"asset_id": e["id"], "name": e["name"]}),
                             f"dataset {e.get('dataset_role')}", e["id"], True)
            e.update(storage="embedded", package_path=path)
        elif t == "embedded":
            try:
                local = assets.fetch(e, root)
            except assets.AssetError as err:
                raise PackageError(f"the {profile} profile embeds every file: {err}") from err
            path = f"assets/{assets.sha_of(e['id'])}-{e['name']}"
            payload[path] = (local.read_bytes(), f"file {e['role']}", e["id"], True)
            e.update(storage="embedded", package_path=path)
        else:
            e["storage"] = "linked"
    if consumers.PREVIEW.get(profile):
        glb = _preview(acft, root)
        if glb is None and consumers.PREVIEW[profile] == "required":
            raise PackageError(f"the {profile} profile needs the glTF preview: the aircraft has no visual parts")
        if glb is not None:
            payload[PREVIEW] = (glb, "preview glTF", None, True)
    payload[ADH_JSON] = (_json_bytes(doc), "ADH document", None, False)
    files = []
    for path in sorted(payload, key=lambda p: (p != ADH_JSON, p)):
        data, role, aid, stored = payload[path]
        f = {"path": path, "sha256": assets.sha256_bytes(data), "size": len(data), "role": role,
             "storage": "stored" if stored else "deflated"}
        if aid:
            f["asset"] = aid
        files.append(f)
    out_dir = Path(out_dir)
    name = package_name(acft, profile)
    manifest = {"format": FORMAT, "format_version": FORMAT_VERSION, "kind": acft.info.get("kind", "aircraft"),
                "aircraft": acft.name, "version": acft.version, "profile": profile,
                "consumers": list(acft.info.get("consumers") or []),
                "muas_schema_version": MUAS_SCHEMA_VERSION, "adh": adh_fork(root),
                "supersedes": supersedes if supersedes is not None else _previous(out_dir, acft, profile),
                "files": files, "package_hash": assets.sha256_bytes(assets.canonical_json(files))}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", allowZip64=True) as z:
        z.writestr(_zinfo("mimetype", True), MIMETYPE.encode("ascii"))
        z.writestr(_zinfo(MANIFEST, False), _json_bytes(manifest))
        for f in files:
            z.writestr(_zinfo(f["path"], f["storage"] == "stored"), payload[f["path"]][0])
    data = buf.getvalue()
    out = out_dir / name
    if out.exists() and out.read_bytes() != data:
        raise PackageError(f"{out} exists with other content. A package is never edited: run `aeroplan build` "
                           "(a new version) first")
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".muas.tmp")
    tmp.write_bytes(data)
    tmp.replace(out)
    return out


def _version_key(v: str):
    return tuple(int(x) for x in v.split("."))


def _previous(out_dir: Path, acft, profile: str) -> Optional[str]:
    """The package hash of the newest older package of this aircraft and profile in `out_dir`, or None."""
    best = None
    for p in Path(out_dir).glob(f"{acft.name}-*-{profile}.muas"):
        v = p.name[len(acft.name) + 1: -len(f"-{profile}.muas")]
        try:
            if _version_key(v) >= _version_key(acft.version):
                continue
        except ValueError:
            continue
        if best is None or _version_key(v) > _version_key(best[0]):
            best = (v, p)
    if best is None:
        return None
    try:
        return open_package(best[1]).manifest["package_hash"]
    except PackageError:
        return None


@dataclass
class Package:
    """An open `.muas` package (every hash checked)."""

    path: Path
    manifest: Dict[str, Any]
    doc: Dict[str, Any]
    files: Dict[str, bytes] = field(repr=False, default_factory=dict)

    def entry(self, aid: str) -> Dict[str, Any]:
        return assets.entry(self.doc, aid)

    def dataset(self, ref: str) -> Any:
        """The JSON value of a dataset reference. Raises PackageError for a linked dataset."""
        aid, ptr = assets.split_ref(ref)
        e = self.entry(aid)
        if e.get("storage") == "inline":
            return assets.resolve(e["inline"], ptr)
        if e.get("storage") == "embedded":
            return assets.resolve(h5json.read_file(self.files[e["package_path"]])[1], ptr)
        raise PackageError(f"dataset {e['name']} is linked: it is not in this {self.manifest['profile']} package")

    @property
    def preview(self) -> Optional[bytes]:
        return self.files.get(PREVIEW)


def open_package(path: Path) -> Package:
    path = Path(path)
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as err:
        raise PackageError(f"{path.name} is not a ZIP archive: {err}") from err
    with z:
        infos = z.infolist()
        if not infos or infos[0].filename != "mimetype" or infos[0].compress_type != zipfile.ZIP_STORED:
            raise PackageError(f"{path.name}: the first entry must be 'mimetype', not compressed")
        if z.read("mimetype").decode("ascii", "replace") != MIMETYPE:
            raise PackageError(f"{path.name}: mimetype is not {MIMETYPE}")
        manifest = json.loads(z.read(MANIFEST))
        if manifest.get("format") != FORMAT or str(manifest.get("format_version", "")).split(".")[0] != \
                FORMAT_VERSION.split(".")[0]:
            raise PackageError(f"{path.name}: format {manifest.get('format')} {manifest.get('format_version')} is "
                               f"not readable (this reader: {FORMAT} {FORMAT_VERSION})")
        names = {i.filename for i in infos} - {"mimetype", MANIFEST}
        listed = {f["path"] for f in manifest["files"]}
        if names != listed:
            raise PackageError(f"{path.name}: the archive and the manifest list other files: "
                               f"{sorted(names ^ listed)}")
        if assets.sha256_bytes(assets.canonical_json(manifest["files"])) != manifest["package_hash"]:
            raise PackageError(f"{path.name}: the package hash does not match the file list")
        files = {}
        for f in manifest["files"]:
            try:
                data = z.read(f["path"])
            except (zipfile.BadZipFile, KeyError) as err:
                raise PackageError(f"{path.name}: {f['path']} cannot be read (sha256 not checked): {err}") from err
            if len(data) != f["size"] or assets.sha256_bytes(data) != f["sha256"]:
                raise PackageError(f"{path.name}: {f['path']} does not match its sha256 in the manifest")
            files[f["path"]] = data
    doc = json.loads(files[ADH_JSON])
    pkg = Package(path, manifest, doc, files)
    for e in assets.register(doc, create=False):
        if e.get("storage") == "inline" and assets.dataset_id(e["inline"]) != e["id"]:
            raise PackageError(f"{path.name}: the inline dataset {e['name']} does not match {e['id']}")
        if e.get("storage") == "embedded":
            if e["package_path"] not in files:
                raise PackageError(f"{path.name}: {e['package_path']} of {e['name']} is missing")
            if e["kind"] == "dataset":
                if assets.dataset_id(pkg.dataset(e["id"])) != e["id"]:
                    raise PackageError(f"{path.name}: the dataset {e['name']} does not match {e['id']}")
            elif assets.sha256_bytes(files[e["package_path"]]) != assets.sha_of(e["id"]):
                raise PackageError(f"{path.name}: the file {e['name']} does not match {e['id']}")
    return pkg


def unpack(path: Path, folder: Path, root: Optional[Path] = None) -> List[str]:
    """Write the source tree of a package into `folder`. A linked dataset comes from its repository location under
    `root` (hash checked). Embedded raw files go into the asset cache. Returns notes. Raises PackageError when a
    dataset cannot be found."""
    pkg = open_package(path)
    doc = copy.deepcopy(pkg.doc)
    acft = source_tree.Aircraft(pkg.manifest["aircraft"], doc, {}, {
        "name": pkg.manifest["aircraft"], "kind": pkg.manifest["kind"]})
    notes, missing = [], []
    for e in assets.register(doc, create=False):
        storage = e.get("storage")
        if e["kind"] == "dataset":
            if storage in ("inline", "embedded"):
                acft.datasets[e["id"]] = pkg.dataset(e["id"])
            else:
                value = None
                for loc in e.get("locations") or []:
                    p = Path(root) / loc["repo"] if root is not None and "repo" in loc else None
                    if p is not None and p.is_file():
                        v = json.loads(p.read_text(encoding="utf-8"))
                        if assets.dataset_id(v) == e["id"]:
                            value = v
                            break
                if value is None:
                    missing.append(f"{e['name']} ({e['id']})")
                else:
                    acft.datasets[e["id"]] = value
        elif storage == "embedded":
            dest = assets.cache_dir() / assets.sha_of(e["id"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(pkg.files[e["package_path"]])
            notes.append(f"{e['name']}: into the asset cache {dest}")
        for k in PACK_FIELDS:
            e.pop(k, None)
    if missing:
        raise PackageError(f"{Path(path).name}: linked datasets not found: {', '.join(missing)}")
    acft.info["consumers"] = list(pkg.manifest.get("consumers") or [pkg.manifest["profile"]])
    source_tree.write(acft, folder)
    return notes
