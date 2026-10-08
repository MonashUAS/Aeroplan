"""Export package v1: an immutable folder, plus a one-file .h5 wrapper (brief D19, section 6.5).

Folder layout: manifest.json plus the files the manifest lists, each with a sha256.
The package sha256 is the hash of the sorted "path<TAB>sha256" lines. A package is never edited.
The .h5 wrapper holds the same bytes, so a hand copy of one file moves the whole package.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import Field, model_validator

from . import MUAS_SCHEMA_VERSION
from .config import canonical_json
from .dml_validate import validate_dml
from .muas.base import MuasModel

PACKAGE_SPEC = "muas-export/1.0.0"
MANIFEST = "manifest.json"


class FileEntry(MuasModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    standard: Optional[str] = None


class Source(MuasModel):
    repo: str
    commit: str
    data_repo: Optional[str] = None
    data_commit: Optional[str] = None
    muas_schema_version: str = MUAS_SCHEMA_VERSION
    adh_upstream: str = "96179ca+patches"


class Correction(MuasModel):
    effect: str
    default_weight: float = 1.0


class PackageManifest(MuasModel):
    package_spec: str = PACKAGE_SPEC
    package_id: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supersedes: Optional[str] = None
    source: Source
    config_id: str
    fidelity_summary: Dict[str, str]
    frames: Dict[str, str]
    reference: Dict[str, object]
    files: List[FileEntry] = Field(min_length=1)
    datasets_used: List[Dict[str, str]] = Field(default_factory=list)
    corrections: List[Correction] = Field(default_factory=list)
    known_limits: List[str] = Field(default_factory=list)
    placeholder: bool = Field(False, description="True when any value is a stand-in")

    @model_validator(mode="after")
    def _check(self):
        paths = [f.path for f in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate file path")
        for p in paths:
            if p.startswith(("/", "..")) or "\\" in p or ".." in p.split("/") or p == MANIFEST:
                raise ValueError(f"bad package path {p!r}")
        return self


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package_hash(entries: List[FileEntry]) -> str:
    lines = "".join(f"{e.path}\t{e.sha256}\n" for e in sorted(entries, key=lambda e: e.path))
    return sha256_bytes(lines.encode("utf-8"))


def build_package(
    out_dir: Path,
    files: Dict[str, bytes],
    *,
    package_id: str,
    source: Source,
    config_id: str,
    fidelity_summary: Dict[str, str],
    frames: Dict[str, str],
    reference: Dict[str, object],
    standards: Optional[Dict[str, str]] = None,
    supersedes: Optional[str] = None,
    datasets_used: Optional[List[Dict[str, str]]] = None,
    corrections: Optional[List[Correction]] = None,
    known_limits: Optional[List[str]] = None,
    placeholder: bool = False,
) -> PackageManifest:
    """Write a new package folder. Refuses to touch an existing one (immutable)."""
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(f"package {out_dir} exists. Packages are immutable: cut a new id")
    standards = standards or {}
    for p, std in standards.items():
        if "S-119" in std:  # DAVE-ML must pass the vendored 2.0 DTD before it enters a package
            errors = validate_dml(files[p])
            if errors:
                raise ValueError(f"{p} is not valid DAVE-ML 2.0: {errors[:3]}")
    entries = [FileEntry(path=p, sha256=sha256_bytes(b), standard=standards.get(p)) for p, b in sorted(files.items())]
    manifest = PackageManifest(
        package_id=package_id, sha256=package_hash(entries), supersedes=supersedes, source=source,
        config_id=config_id, fidelity_summary=fidelity_summary, frames=frames, reference=reference, files=entries,
        datasets_used=datasets_used or [], corrections=corrections or [], known_limits=known_limits or [],
        placeholder=placeholder,
    )
    for p, b in files.items():
        dst = out_dir / p
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b)
    (out_dir / MANIFEST).write_text(canonical_json(json.loads(manifest.model_dump_json())), encoding="utf-8")
    return manifest


def verify_package(pkg_dir: Path) -> PackageManifest:
    """Check the manifest, every file hash, the package hash and that no extra file exists."""
    pkg_dir = Path(pkg_dir)
    manifest = PackageManifest.model_validate_json((pkg_dir / MANIFEST).read_text(encoding="utf-8"))
    for e in manifest.files:
        f = pkg_dir / e.path
        if not f.is_file():
            raise ValueError(f"missing file {e.path}")
        if sha256_bytes(f.read_bytes()) != e.sha256:
            raise ValueError(f"hash mismatch {e.path}")
    if package_hash(manifest.files) != manifest.sha256:
        raise ValueError("package sha256 does not match the file list")
    on_disk = {p.relative_to(pkg_dir).as_posix() for p in pkg_dir.rglob("*") if p.is_file()} - {MANIFEST}
    extra = on_disk - {e.path for e in manifest.files}
    if extra:
        raise ValueError(f"files not in manifest: {sorted(extra)}")
    return manifest


def pack_h5(pkg_dir: Path, h5_path: Path) -> Path:
    """Wrap a verified package folder into ONE .h5 file."""
    import h5py
    import numpy as np

    pkg_dir, h5_path = Path(pkg_dir), Path(h5_path)
    manifest = verify_package(pkg_dir)
    if h5_path.exists():
        raise FileExistsError(h5_path)
    with h5py.File(h5_path, "w") as h:
        h.attrs["package_spec"] = manifest.package_spec
        h.attrs["package_id"] = manifest.package_id
        h.attrs["sha256"] = manifest.sha256
        h.create_dataset("manifest", data=np.frombuffer((pkg_dir / MANIFEST).read_bytes(), dtype=np.uint8))
        grp = h.create_group("files")
        for e in manifest.files:
            grp.create_dataset(e.path, data=np.frombuffer((pkg_dir / e.path).read_bytes(), dtype=np.uint8))
    return h5_path


def unpack_h5(h5_path: Path, out_dir: Path) -> PackageManifest:
    """Rebuild the package folder from the .h5 file and verify it."""
    import h5py

    out_dir = Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(out_dir)
    with h5py.File(h5_path, "r") as h:
        out_dir.mkdir(parents=True)
        (out_dir / MANIFEST).write_bytes(bytes(h["manifest"][()]))

        def _write(name, obj):
            if hasattr(obj, "shape"):
                dst = out_dir / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(bytes(obj[()]))

        h["files"].visititems(_write)
    return verify_package(out_dir)
