"""The asset register: one entry for each large file or dataset, under the `muas` key of 1.10.2 DataRepository.

An asset has one ID, its content hash: `asset:sha256:<hash>`. Every other item refers to the ID, never to a file
path. The register says where the bytes are:

    inline     in the ADH JSON (the entry field `inline`)
    embedded   inside the `.muas` package (the entry field `package_path`)
    linked     outside the package. `locations` lists where to fetch it. Each fetch checks the hash.

The source tree holds no tier: `aeroplan pack` sets `storage` from the packing profile.

A file asset (CAD, a tool file, a flight log) has the hash of its bytes. A dataset asset has the hash of its
canonical JSON (aeroplan.assets.canonical_json). A derived asset records `derived_from` (the assets it was made
from) and `built_against` (the aircraft version it was made from). A `derived_from` ID that is no longer in the
register shows a stale asset (for example an aero model older than the CAD).
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, model_validator

from .base import MuasModel
from .dataset import DatasetMeta, DatasetRole

ASSET_ID = r"^asset:sha256:[0-9a-f]{64}$"


class Location(MuasModel):
    """Where a linked asset can be fetched: a path in the AeroPlan repository, or a URL. `member` names the file
    inside a ZIP archive at the URL: a path, where a part that ends in .zip is a ZIP inside the ZIP."""

    repo: Optional[str] = Field(None, description="Path relative to the AeroPlan repository root")
    url: Optional[str] = None
    member: Optional[str] = None

    @model_validator(mode="after")
    def _one(self):
        if (self.repo is None) == (self.url is None):
            raise ValueError("a location is a repo path or a URL, not both and not neither")
        if self.member is not None and self.url is None:
            raise ValueError("member needs a URL")
        return self


class Asset(MuasModel):
    id: str = Field(pattern=ASSET_ID)
    kind: Literal["file", "dataset"]
    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$",
                      description="File name (file) or dataset name (dataset). Unique in the register")
    role: str = Field(min_length=1, description="What the asset gives, for example 'CAD mesh of aileron_l'")
    tool: str = Field(min_length=1, description="The spoke that registered the asset")
    media_type: str = Field(min_length=1)
    size: int = Field(ge=0, description="Bytes of the file, or of the canonical JSON of the dataset")
    locations: List[Location] = Field(default_factory=list)
    derived_from: List[str] = Field(default_factory=list)
    built_against: Optional[str] = Field(None, description="<aircraft>@<version> that the asset was made from")
    dataset: Optional[DatasetMeta] = Field(None, description="The metadata of a dataset asset")
    dataset_role: Optional[DatasetRole] = None
    reference: Optional[List[Dict[str, Any]]] = Field(None, description="ADH Reference items (the published source)")
    storage: Optional[Literal["inline", "embedded", "linked"]] = Field(None, description="Set by aeroplan pack")
    package_path: Optional[str] = Field(None, description="Path in the package of an embedded asset")
    inline: Optional[Any] = Field(None, description="The dataset of an inline asset")
    note: Optional[str] = None

    @model_validator(mode="after")
    def _check(self):
        if self.kind == "dataset" and (self.dataset is None or self.dataset_role is None):
            raise ValueError(f"{self.name}: a dataset asset needs dataset and dataset_role")
        if self.kind == "file" and self.dataset is not None:
            raise ValueError(f"{self.name}: a file asset has no dataset metadata")
        if self.storage == "embedded" and not self.package_path:
            raise ValueError(f"{self.name}: an embedded asset needs package_path")
        if self.storage == "inline" and self.inline is None:
            raise ValueError(f"{self.name}: an inline asset needs inline")
        if self.reference:
            from aircraft_data_hierarchy.behavior import Reference

            for r in self.reference:
                Reference.model_validate(r)
        return self
