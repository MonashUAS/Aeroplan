"""Control-system extensions (user answers 3 and 4, 2026-10-08). Group for a later control-systems analysis.

- `Actuator` sits on a control-surface node (key `muas.actuator`): the servo lag and rate limit of that surface.
- `Autopilot` sits on the ADH node 1.2.5.10 AutomaticFlightControl (key `muas.autopilot`): the servo output map.
  It is the ground truth for SITL and for the flight controller (Cube). Aerolink makes the ArduPilot parameters from it.

ArduPilot output functions (SERVOn_FUNCTION): aileron 4, elevator 19, rudder 21, throttle 70, motor1 to motor8 33 to 40,
motor9 to motor12 82 to 85. Source: ArduPilot parameter list, SERVOn_FUNCTION [reference/index needed]. A quadcopter
uses motor1 to motor4. A quadplane (H4) uses motor5 to motor8 for the lift rotors, an H8 quadplane uses motor5 to motor12.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import Field, model_validator

from .base import MuasModel

ARDUPILOT_FUNCTION = {"aileron": 4, "elevator": 19, "rudder": 21, "throttle": 70, "motor1": 33, "motor2": 34, "motor3": 35,
                      "motor4": 36,
                      "motor5": 37, "motor6": 38, "motor7": 39, "motor8": 40, "motor9": 82, "motor10": 83, "motor11": 84,
                      "motor12": 85}
MOTOR_FUNCTIONS = tuple(f"motor{n}" for n in range(1, 13))


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
    MOTOR1 = "motor1"
    MOTOR2 = "motor2"
    MOTOR3 = "motor3"
    MOTOR4 = "motor4"
    MOTOR5 = "motor5"
    MOTOR6 = "motor6"
    MOTOR7 = "motor7"
    MOTOR8 = "motor8"
    MOTOR9 = "motor9"
    MOTOR10 = "motor10"
    MOTOR11 = "motor11"
    MOTOR12 = "motor12"


class ServoOutput(MuasModel):
    """One output channel of the flight controller.

    `sign` relates the PWM to the surface: +1 means a PWM above the trim gives a positive deflection in the
    JSBSim sign (aileron rolls right, elevator trailing edge down, rudder trailing edge left). A throttle and a
    motor output have no sign. A motor output (`motor1` to `motor12`) drives one lift rotor: `targets` holds the
    `muas.instance` of the rotor whose `propeller.motor` equals the output number. `pwm_min_us` and `pwm_max_us` are
    the ESC end points.
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
        if self.function is OutputFunction.THROTTLE or self.function.value in MOTOR_FUNCTIONS:
            if self.sign is not None:
                raise ValueError(f"a {self.function.value} output has no sign")
            if self.function.value in MOTOR_FUNCTIONS and len(self.targets) != 1:
                raise ValueError(f"channel {self.channel}: a motor output drives exactly one rotor")
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
