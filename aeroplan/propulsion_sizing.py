"""First sizing of a quadplane propulsion system from the maximum take-off mass (MTOW). Pure functions, SI units.

Method (momentum theory, the first pass before a motor and propeller are chosen):
- Lift rotors: each of `n_lift` rotors carries W / n_lift in hover. The rotor area follows from the disc loading
  (weight per total rotor area). Ideal hover power per rotor is T^1.5 / sqrt(2 rho A). The shaft power is the ideal
  power over the figure of merit. The electrical power is the shaft power over the motor and ESC efficiency.
- Peak thrust: `hover_tw` times the weight, shared by the rotors. Power at peak thrust scales with T^1.5.
- Cruise: thrust = W / (L/D). Electrical power = T V / (propeller efficiency * chain efficiency).
- Battery: energy of the hover time and the cruise time, plus the reserve, over the usable depth of discharge.

Every input is an assumption until a member confirms it. The caller marks the outputs `placeholder` until then.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Dict, List

G = 9.80665


@dataclass(frozen=True)
class Inputs:
    mtow_kg: float
    n_lift: int
    hover_tw: float                      # peak lift thrust over weight (control margin, 1.5 to 2.0)
    disc_loading_n_m2: float             # W / total lift rotor area at MTOW
    figure_of_merit: float               # hover rotor efficiency (0.6 to 0.75)
    eta_lift_chain: float                # motor * ESC, lift motors
    cruise_speed_m_s: float
    lift_to_drag: float
    eta_prop_cruise: float
    eta_cruise_chain: float
    hover_time_s: float                  # total hover time of the mission (take-off, landing, hold)
    cruise_time_s: float
    reserve_fraction: float              # extra energy kept back, of the mission energy
    depth_of_discharge: float            # usable fraction of the battery capacity
    battery_wh_per_kg: float             # pack level, not cell level
    rho_kg_m3: float = 1.225


def inputs_from(settings: Dict[str, Any], mtow_kg: float) -> Inputs:
    """The inputs from the settings block `propulsion_sizing`. A missing key is an error: no hidden default."""
    names = [f.name for f in fields(Inputs) if f.name not in ("mtow_kg", "rho_kg_m3")]
    missing = [n for n in names if n not in settings]
    if missing:
        raise ValueError(f"propulsion_sizing settings miss: {', '.join(missing)}")
    unknown = sorted(set(settings) - set(names) - {"rho_kg_m3", "confirmed"})
    if unknown:
        raise ValueError(f"propulsion_sizing settings have unknown keys: {', '.join(unknown)}")
    kw = {n: settings[n] for n in names}
    if "rho_kg_m3" in settings:
        kw["rho_kg_m3"] = settings["rho_kg_m3"]
    return Inputs(mtow_kg=mtow_kg, **kw)


def _check(i: Inputs) -> None:
    for name in ("mtow_kg", "disc_loading_n_m2", "cruise_speed_m_s", "lift_to_drag", "battery_wh_per_kg", "rho_kg_m3"):
        if getattr(i, name) <= 0:
            raise ValueError(f"{name} must be positive")
    if i.n_lift < 1 or int(i.n_lift) != i.n_lift:
        raise ValueError("n_lift must be a whole number of at least 1")
    if i.hover_tw < 1:
        raise ValueError("hover_tw must be at least 1 (the rotors must lift the aircraft)")
    for name in ("figure_of_merit", "eta_lift_chain", "eta_prop_cruise", "eta_cruise_chain", "depth_of_discharge"):
        if not 0 < getattr(i, name) <= 1:
            raise ValueError(f"{name} must be in (0, 1]")
    if i.hover_time_s < 0 or i.cruise_time_s < 0 or i.reserve_fraction < 0:
        raise ValueError("times and the reserve fraction must not be negative")


def size(i: Inputs) -> Dict[str, float]:
    """The propulsion requirements for the inputs. Keys carry their unit as a suffix."""
    _check(i)
    w = i.mtow_kg * G
    t_hover = w / i.n_lift
    area = w / i.disc_loading_n_m2 / i.n_lift                            # one rotor
    p_ideal = t_hover ** 1.5 / math.sqrt(2 * i.rho_kg_m3 * area)
    p_el_hover = p_ideal / i.figure_of_merit / i.eta_lift_chain          # one motor, hover
    p_el_peak = p_el_hover * i.hover_tw ** 1.5                           # one motor, peak thrust
    t_cruise = w / i.lift_to_drag
    p_el_cruise = t_cruise * i.cruise_speed_m_s / (i.eta_prop_cruise * i.eta_cruise_chain)
    e_mission_wh = (p_el_hover * i.n_lift * i.hover_time_s + p_el_cruise * i.cruise_time_s) / 3600.0
    e_pack_wh = e_mission_wh * (1 + i.reserve_fraction) / i.depth_of_discharge
    m_batt = e_pack_wh / i.battery_wh_per_kg
    return {
        "weight_n": w,
        "lift_motor_thrust_hover_n": t_hover,
        "lift_motor_thrust_peak_n": t_hover * i.hover_tw,
        "lift_rotor_diameter_m": 2 * math.sqrt(area / math.pi),
        "lift_motor_power_hover_w": p_el_hover,
        "lift_motor_power_peak_w": p_el_peak,
        "hover_power_total_w": p_el_hover * i.n_lift,
        "cruise_thrust_n": t_cruise,
        "cruise_power_w": p_el_cruise,
        "mission_energy_wh": e_mission_wh,
        "battery_energy_wh": e_pack_wh,
        "battery_mass_kg": m_batt,
        "battery_mass_fraction": m_batt / i.mtow_kg,
    }


# (result key, requirement key, bound, units, description)
REQUIREMENTS: List[tuple] = [
    ("lift_motor_thrust_peak_n", "lift_motor_thrust_peak", "min", "N", "Peak thrust of each lift motor with its propeller"),
    ("lift_rotor_diameter_m", "lift_rotor_diameter", "target", "m", "Diameter of each lift rotor"),
    ("lift_motor_power_peak_w", "lift_motor_power_peak", "min", "W", "Peak electrical power of each lift motor and ESC"),
    ("hover_power_total_w", "hover_power_total", "target", "W", "Electrical power of all lift motors in hover at MTOW"),
    ("cruise_thrust_n", "cruise_thrust", "target", "N", "Cruise thrust at the cruise speed"),
    ("cruise_power_w", "cruise_power", "target", "W", "Electrical power in cruise"),
    ("battery_energy_wh", "battery_energy", "min", "W*h", "Pack energy (mission, reserve and depth of discharge)"),
    ("battery_mass_kg", "battery_mass", "target", "kg", "Pack mass at the assumed pack energy density"),
]
