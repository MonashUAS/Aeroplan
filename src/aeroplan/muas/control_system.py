"""Control-system extensions (user answers 3 and 4, 2026-10-08). Group for a later control-systems analysis.

- `Actuator` sits on a control-surface node (key `muas.actuator`): the servo lag and rate limit of that surface.
- `Autopilot` sits on the ADH node 1.2.5.10 AutomaticFlightControl (key `muas.autopilot`): the servo output map.
  It is the ground truth for SITL and for the flight controller (Cube). Aerolink makes the ArduPilot parameters from it.

ArduPilot output functions (SERVOn_FUNCTION): aileron 4, elevator 19, rudder 21, throttle 70.
Source: ArduPilot parameter list, ArduPlane, SERVOn_FUNCTION [reference/index needed].
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import Field, model_validator

from .base import MuasModel

ARDUPILOT_FUNCTION = {"aileron": 4, "elevator": 19, "rudder": 21, "throttle": 70}


class Actuator(MuasModel):
    """Servo of one control surface: a first-order lag and a rate limit (surface deflection, rad)."""

    tau_s: float = Field(gt=0, description="First-order lag time constant, s")
    rate_limit_rad_s: float = Field(gt=0, description="Largest deflection rate, rad/s")
    model: Optional[str] = Field(None, description="Servo make and model, when known")
    source: str = Field(min_length=1)
    placeholder: bool = False


class OutputFunction(str, Enum):
    AILERON = "aileron"
    ELEVATOR = "elevator"
    RUDDER = "rudder"
    THROTTLE = "throttle"


class ServoOutput(MuasModel):
    """One output channel of the flight controller.

    `sign` relates the PWM to the surface: +1 means a PWM above the trim gives a positive deflection in the
    JSBSim sign (aileron rolls right, elevator trailing edge down, rudder trailing edge left). A throttle has no sign.
    """

    channel: int = Field(ge=1, le=16)
    function: OutputFunction
    targets: List[str] = Field(min_length=1, description="muas.instance of each surface or propeller on this output")
    sign: Optional[int] = Field(None, description="+1 or -1. Absent for a throttle")
    reversed: Optional[bool] = Field(None, description="SERVOn_REVERSED on the aircraft. None when not recorded")
    pwm_min_us: Optional[int] = Field(None, ge=500, le=2500)
    pwm_trim_us: Optional[int] = Field(None, ge=500, le=2500)
    pwm_max_us: Optional[int] = Field(None, ge=500, le=2500)
    source: str = Field(min_length=1)
    placeholder: bool = False

    @property
    def ardupilot_function(self) -> int:
        return ARDUPILOT_FUNCTION[self.function.value]

    @model_validator(mode="after")
    def _check(self):
        if self.function is OutputFunction.THROTTLE:
            if self.sign is not None:
                raise ValueError("a throttle output has no sign")
        elif self.sign not in (1, -1):
            raise ValueError(f"channel {self.channel}: sign must be +1 or -1 for a surface output")
        pwm = [p for p in (self.pwm_min_us, self.pwm_trim_us, self.pwm_max_us) if p is not None]
        if pwm != sorted(pwm) or len(set(pwm)) != len(pwm):
            raise ValueError(f"channel {self.channel}: pwm_min_us < pwm_trim_us < pwm_max_us")
        return self


class Autopilot(MuasModel):
    """The flight controller and its output map."""

    firmware: str = Field(description="For example ArduPlane")
    firmware_version: Optional[str] = None
    board: Optional[str] = Field(None, description="For example CubeOrange")
    outputs: List[ServoOutput] = Field(min_length=1)
    notes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self):
        ch = [o.channel for o in self.outputs]
        if len(set(ch)) != len(ch):
            raise ValueError("an output channel is used twice")
        return self
