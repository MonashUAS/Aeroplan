"""Flight events (1.8.1.4 FlightTests) and firmware releases (1.2.9 AirVehicleSoftwareRelease).

ADH has the two WBS nodes but no slot for their data, so it sits under their `muas` key. A flight record keeps the
ArduPilot log as a linked asset. The decoded data and the segments for system identification are datasets.
"""
from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import Field, model_validator

from .base import MuasModel
from .reference import Position
from .units import Quantity

ASSET_ID = r"^asset:sha256:[0-9a-f]{64}$"


class SoftwareRelease(MuasModel):
    """A firmware release that flies on the air vehicle."""

    release_id: str = Field(min_length=1)
    firmware: str = Field(min_length=1, description="For example ArduPlane")
    version: str = Field(min_length=1)
    git_hash: Optional[str] = None
    board: Optional[str] = None
    binary: Optional[str] = Field(None, pattern=ASSET_ID, description="The firmware file, when registered")
    source: str = Field(min_length=1)


class Segment(MuasModel):
    """A time slice of a flight for one purpose (for example a doublet for system identification)."""

    name: str = Field(min_length=1)
    t_start_s: float = Field(ge=0)
    t_end_s: float
    purpose: Literal["system_id", "trim", "performance", "handling", "other"]
    note: Optional[str] = None

    @model_validator(mode="after")
    def _order(self):
        if self.t_end_s <= self.t_start_s:
            raise ValueError(f"segment {self.name}: t_end_s must be after t_start_s")
        return self


class FlightEvent(MuasModel):
    """One flight: the configuration flown, the as-flown mass and CG, the firmware and parameters, the segments."""

    event_id: str = Field(min_length=1)
    date: date
    package_hash: Optional[str] = Field(None, pattern=r"^[0-9a-f]{64}$",
                                        description="The `.muas` package of the configuration flown")
    aircraft_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    mass: Quantity
    cg: Position
    firmware: str = Field(min_length=1, description="release_id of a 1.2.9 software release")
    parameters: Optional[str] = Field(None, pattern=ASSET_ID, description="The parameter dataset")
    log: str = Field(pattern=ASSET_ID, description="The raw ArduPilot DataFlash log (linked)")
    segments: List[Segment] = Field(default_factory=list)
    source: str = Field(min_length=1)
    placeholder: bool = False

    @model_validator(mode="after")
    def _check(self):
        self.mass.require("mass", "as-flown mass")
        names = [s.name for s in self.segments]
        if len(set(names)) != len(names):
            raise ValueError(f"flight {self.event_id}: a segment name is used twice")
        return self
