"""
The mission of a quadplane: the flight conditions the model evaluates, and the segments that add up to the energy.

    FlightCondition   one steady state: a name, a mode (hover, climb, max, cruise), a speed, the load case
    Segment           a condition held for a time, plus the energy of a height change
    Mission           a component (params: heights, rates, distances, survey, hover times, payload). It gives the
                      conditions and, with the powers of the model, the energy of each segment

    pack_current      the current of a pack (V = V_oc - R_b I) at a terminal power

The model (model.py) evaluates each condition once. Mission.discharge takes the pack through the segments in flight order
(state of charge, voltage sag) and gives the energy of each segment, the objective of the optimiser. The segment rules are
those of Redback flight 00000171 with 10 endurance laps in place of 1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from component import Component

G0 = 9.80665
N_SUB = 4                       # midpoint steps per segment in Mission.discharge. Project choice: 0.02 % of the energy against 50 steps


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

    @staticmethod
    def discharge(bus_W: Dict[str, Any], segments: List[Segment], S: int, cap_Ah: Any, R_b: Any, ocv: Any,
                  n_sub: int = N_SUB) -> Dict[str, Dict[str, Any]]:
        """
        The pack through the segments in flight order, from a full charge (SOC 1). bus_W: the power at the pack terminals of
        each condition (W). A segment draws its power plus extra_J / time_s. The pack is V = S OCV(SOC) - R_b I (see
        pack_current). Each segment has n_sub steps of the midpoint rule on dSOC/dt = -I / (3600 cap). The energy of a
        segment is the charge it takes at the OCV: S cap (F(SOC start) - F(SOC end)), so the energies add up to
        S cap (F(1) - F(SOC end)) and include the R_b I^2 loss.
        Returns {"J", "t", "soc", "V", "I"}: for each segment the energy (J), the time (s), and at its end the SOC, the
        terminal voltage (V) and the current (A).
        """
        out: Dict[str, Dict[str, Any]] = {k: {} for k in ("J", "t", "soc", "V", "I")}
        Q = 3600.0 * cap_Ah

        def current(P, s):
            return pack_current(P, S * ocv.ocv(s), R_b)

        s = 1.0
        for seg in segments:
            P = bus_W[seg.condition] + seg.extra_J / seg.time_s
            dt, s0 = seg.time_s / n_sub, s
            for _ in range(n_sub):
                s_mid = s - 0.5 * dt * current(P, s) / Q
                s = s - dt * current(P, s_mid) / Q
            I_end = current(P, s)
            out["J"][seg.name] = 3600.0 * S * cap_Ah * (ocv.F(s0) - ocv.F(s))
            out["t"][seg.name], out["soc"][seg.name] = seg.time_s, s
            out["V"][seg.name], out["I"][seg.name] = S * ocv.ocv(s) - R_b * I_end, I_end
        return out


def pack_current(P_W: Any, V_oc: Any, R_b: Any) -> Any:
    """The current (A) of a pack with the open-circuit voltage V_oc and the resistance R_b that gives the power P_W at its
    terminals: P = (V_oc - R_b I) I, the low root. The guard keeps the root real when the pack cannot give P (the solver
    can step there)."""
    import aerosandbox.numpy as anp
    disc = anp.fmax(V_oc ** 2 - 4.0 * R_b * P_W, 0.01 * V_oc ** 2)
    return 2.0 * P_W / (V_oc + anp.sqrt(disc))
