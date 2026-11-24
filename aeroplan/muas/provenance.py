"""Provenance (brief D09). Hash fields live here. ADH ModelDescription and DAVE-ML Provenance stay as upstream."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from .base import MuasModel

SHA256 = r"^[0-9a-f]{64}$"


class Provenance(MuasModel):
    tool: str
    tool_version: str
    author: str
    created: Optional[datetime] = Field(None, description="None when the source does not record a date")
    input_sha256: Optional[str] = Field(None, pattern=SHA256)
    geometry_hash: Optional[str] = Field(None, pattern=SHA256)
    config_id: Optional[str] = None
    method: Optional[str] = None
