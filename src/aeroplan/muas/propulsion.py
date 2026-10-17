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
from typing import List, Optional

from pydantic import Field, model_validator

from .base import MuasModel
from .reference import Position
from .units import Quantity


class PropRole(str, Enum):
    CRUISE = "cruise"
    LIFT = "lift"


class Spin(str, Enum):
    """The turn direction of a rotor, seen looking ALONG the thrust vector from behind the rotor (the JSBSim sense
    convention). CW means the angular velocity vector points along `thrust_axis` (right-hand rule): the rotor
    reaction torque on the airframe then points against the thrust axis.

    A lift rotor with its thrust up is seen from below. An ArduPilot motor that turns CCW seen from above is
    therefore `cw` here, and an ArduPilot CW motor is `ccw` here."""

    CW = "cw"
    CCW = "ccw"


class PropellerInstallation(MuasModel):
    """Mount of a propeller or rotor in the design frame (WBS 1.2.3.9).

    A multirotor has one installation for each lift rotor (the first one on the WBS node, the others as
    subcomponents of it). `motor` is the autopilot motor number (ArduPilot MOTn, 1 to 12; a quadplane lift rotor starts at 5) and `system` names the
    propulsion system (`muas.propulsion_system.system_id`) that drives the rotor. The system data and the Ct/Cp
    dataset are stored once, on one item."""

    role: PropRole
    hub: Position
    thrust_axis: List[float] = Field(min_length=3, max_length=3, description="Unit vector, design frame")
    spin: Spin
    diameter: Quantity
    motor: Optional[int] = Field(None, ge=1, le=12, description="Autopilot motor number (ArduPilot MOTn). "
                                 "Needed for a lift rotor")
    system: Optional[str] = Field(None, min_length=1, description="system_id of the propulsion system")

    @model_validator(mode="after")
    def _check(self):
        self.diameter.require("length", "diameter")
        norm = sum(v * v for v in self.thrust_axis) ** 0.5
        if abs(norm - 1.0) > 1e-6:
            raise ValueError("thrust_axis must be a unit vector")
        if self.role is PropRole.LIFT and self.motor is None:
            raise ValueError("a lift rotor needs its autopilot motor number (`motor`)")
        return self
