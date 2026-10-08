"""Ground contacts (user answer 3, 2026-10-08). Group for a later structural and landing-loads analysis.

ADH has no landing-gear WBS number. The contacts sit on the Airframe node 1.2.2 (key `muas.ground_contacts`),
because the wing tips and the tail skid are airframe structure too.

A contact is a point with a linear spring and damper along the local vertical:
BOGEY is a wheel (it can roll), STRUCTURE is a part of the airframe that can touch the ground.
"""
from __future__ import annotations

from enum import Enum

from pydantic import Field

from .base import MuasModel
from .reference import Position


class ContactKind(str, Enum):
    BOGEY = "BOGEY"
    STRUCTURE = "STRUCTURE"


class GroundContact(MuasModel):
    name: str = Field(pattern=r"^[A-Z0-9_]+$")
    type: ContactKind
    position: Position
    spring_N_per_m: float = Field(gt=0)
    damping_N_per_m_s: float = Field(ge=0)
    source: str = Field(min_length=1)
    placeholder: bool = False
