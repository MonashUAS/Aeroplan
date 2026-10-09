"""Electric propulsion extension (brief D12; user answers 3, 4).

Propeller performance is a Ct/Cp table, a point dataset against advance ratio J
(and rpm when known). The data reaches AeroPlan through Propalyser. Proptimiser
output is an input to Propalyser, not to AeroPlan.

Definitions (standard propeller coefficients, see the references page, A8)::

    J  = V / (n D)
    Ct = T / (rho n^2 D^4)
    Cp = P / (rho n^3 D^5)

with n in rev/s and D the propeller diameter.
"""
from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import Field, model_validator

from .base import MuasModel
from .reference import Position
from .units import Quantity


class PropRole(str, Enum):
    CRUISE = "cruise"
    LIFT = "lift"


class Spin(str, Enum):
    CW = "cw"
    CCW = "ccw"


class PropellerInstallation(MuasModel):
    """Mount of a propeller or rotor in the design frame (WBS 1.2.3.9)."""

    role: PropRole
    hub: Position
    thrust_axis: List[float] = Field(min_length=3, max_length=3, description="Unit vector, design frame")
    spin: Spin
    diameter: Quantity

    @model_validator(mode="after")
    def _check(self):
        self.diameter.require("length", "diameter")
        norm = sum(v * v for v in self.thrust_axis) ** 0.5
        if abs(norm - 1.0) > 1e-6:
            raise ValueError("thrust_axis must be a unit vector")
        return self
