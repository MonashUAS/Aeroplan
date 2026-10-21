"""
The mission of a quadplane: the flight conditions the model evaluates, and the segments that add up to the energy.

    FlightCondition   one steady state: a name, a mode (hover, climb, max, cruise), a speed, the load case
    Segment           a condition held for a time, plus the energy of a height change
    Mission           a component (params: heights, rates, distances, survey, hover times, payload). It gives the
                      conditions and, with the powers of the model, the energy of each segment

The model (model.py) evaluates each condition once. The mission turns the powers into a time-weighted energy, the
objective of the optimiser. The segment rules are those of Redback flight 00000171 with 10 endurance laps in place of 1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from component import Component

G0 = 9.80665


@dataclass(frozen=True)
class FlightCondition:
    """
    One steady flight state.
      name           H_TO (hover, take-off mass), C_TO (vertical climb), H_L (hover, landing mass, cargo gone), MAX (full
                     throttle, hover thrust times thrust_factor), F_LAP and F_MAP (forward flight on the nose propeller)
      mode           hover, climb, max, cruise
      speed_m_s      climb rate (mode climb); airspeed at the start (mode cruise)
      payload        False: the cargo is gone (landing mass)
      thrust_factor  MAX only: thrust over weight
      turn           F_MAP only: the survey turns raise the load factor (share of the path and bank angle in the mission)
    """
    name: str
    mode: str
    speed_m_s: float = 0.0
    payload: bool = True
    thrust_factor: float = 1.0
    turn: bool = False


@dataclass
class Segment:
    """A condition held for `time_s`, plus `extra_J` (the potential energy of a climb, divided by the efficiency)."""
    name: str
    condition: str
    time_s: Any
    extra_J: Any = 0.0


class Mission(Component):
    """
    The mission. Params (SI):
      climb_height_m, climb_rate_m_s          forward-flight climb to the cruise height
      transit_m, lap_length_m, lap_count, rtl_m
      survey_lines, survey_line_length_m, survey_turn_bank_deg
      deployment_hover_s, reserve_hover_s
      vtol_climb_m, vtol_climb_rate_m_s, vtol_descent_rate_m_s, transition_s
    The payload is the cargo, a point-mass component of the model. It is released at the deployment: gone in the H_L condition.
    """
    KIND = "mission"

    def conditions(self, thrust_factor: float) -> List[FlightCondition]:
        """The six conditions, in the order the model adds them."""
        return [FlightCondition("H_TO", "hover"),
                FlightCondition("C_TO", "climb", self.num("vtol_climb_rate_m_s")),
                FlightCondition("H_L", "hover", payload=False),
                FlightCondition("MAX", "max", thrust_factor=thrust_factor),
                FlightCondition("F_LAP", "cruise"),
                FlightCondition("F_MAP", "cruise", turn=True)]

    def survey(self, turn_radius_m: float) -> Dict[str, float]:
        """Length of the survey lines and turns, the share of the path in turns, and the load factor in a turn."""
        lines = self.num("survey_lines")
        turn_len = (lines - 1) * math.pi * turn_radius_m
        line_len = lines * self.num("survey_line_length_m")
        return {"turn_len": turn_len, "line_len": line_len, "turn_frac": turn_len / (turn_len + line_len),
                "n_turn": 1.0 / math.cos(math.radians(self.num("survey_turn_bank_deg")))}

    def segments(self, V_lap: Any, V_map: Any, turn_radius_m: float, M_g: Any, eta_lap: Any) -> List[Segment]:
        """The segments. V_lap and V_map: airspeeds (numbers or expressions). M_g: weight in N. eta_lap: the total efficiency
        (thrust power over battery power) of the laps, for the climb energy."""
        sv = self.survey(turn_radius_m)
        t_vclimb = self.num("vtol_climb_m") / self.num("vtol_climb_rate_m_s")
        dh = self.num("climb_height_m") - self.num("vtol_climb_m")
        dist = self.num("transit_m") + self.num("lap_length_m") * self.num("lap_count") + self.num("rtl_m")
        return [
            Segment("vtol_takeoff_climb", "C_TO", t_vclimb),
            Segment("transitions", "H_TO", 2.0 * self.num("transition_s")),
            Segment("fw_climb", "F_LAP", dh / self.num("climb_rate_m_s"), M_g * dh / eta_lap),
            Segment("transit_laps_rtl", "F_LAP", dist / V_lap),
            Segment("survey", "F_MAP", (sv["line_len"] + sv["turn_len"]) / V_map),
            Segment("deploy_hover", "H_L", self.num("deployment_hover_s")),
            Segment("landing", "H_L", self.num("vtol_climb_m") / self.num("vtol_descent_rate_m_s")),
            Segment("reserve", "H_L", self.num("reserve_hover_s")),
        ]

    def energy(self, power_W: Dict[str, Any], segments: List[Segment]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """(energy in J, time in s) of each segment: the power of its condition times its time, plus its extra energy."""
        seg_J = {s.name: power_W[s.condition] * s.time_s + s.extra_J for s in segments}
        t = {s.name: s.time_s for s in segments}
        return seg_J, t
