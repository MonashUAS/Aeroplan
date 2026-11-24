"""Initial-condition spec (brief D17). Rate frame, latitude type and attitude sequence are mandatory.

NESC TM-2015-218675: misread initial conditions caused a large share of the verification effort.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict

from pydantic import Field

from .base import MuasModel


class RateFrame(str, Enum):
    LOCAL_NED = "local_NED"
    INERTIAL = "inertial"


class LatitudeType(str, Enum):
    GEODETIC = "geodetic"
    GEOCENTRIC = "geocentric"


class InitialConditions(MuasModel):
    rate_frame: RateFrame = Field(description="Frame that the velocity and rotation rates are relative to")
    latitude_type: LatitudeType
    attitude_sequence: str = Field(pattern=r"^[1-3]-[1-3]-[1-3]$", description="Euler sequence, for example 3-2-1")
    units: str = "SI"
    values: Dict[str, float] = Field(description="Named state values in SI. Angles in radians")
    placeholder: bool = False
