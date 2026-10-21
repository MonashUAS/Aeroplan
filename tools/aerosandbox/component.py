"""
Components of an aircraft model, and the functions that give a component at a chosen fidelity level.

    from component import Material, Tube, Rotor, level, rotor_model, airframe_model, motor_model

A component is a named bag of `Param`. A `Param` holds a value, its units, its source, a `placeholder` flag, and the
optimiser settings (`free`, `lo`, `hi`, `scale`). A free param is a design variable of the optimiser. A fixed param is a
parameter of the optimisation problem. `comp.free("r_o", "t")` and `comp.fix(r_o=0.0175)` switch a param. Components are
made in code (a notebook) and saved in one file for each aircraft (`model.AircraftModel.save`, settings/<aircraft>.json).

Level functions (the second half of this file) take a component and a `Level` and give the model the solver uses:
  rotor_model(rotor, level, state)   momentum theory, a fitted CT/CP table, or the Proptimiser BEMT in the full space
  airframe_model(airframe, level)    the Currawong airframe with its neutral point (vortex lattice) and polar (AeroBuildup)
  motor_model(motor, level)          the mass, resistance and idle current of the motor, fitted on data/motor_survey.csv
`Level` also lists the constraint groups that are on. The ladder (optimise.py) runs the levels L0 to L4 in turn.

This file imports numpy at the top and aerosandbox, casadi, proptimiser and aeroplan inside the functions that need them.
So the AeroPlan Python (no aerosandbox) can read and write the JSON of a model.

Frame: x aft, y right, z up, metres, kilograms, seconds, radians. Quantities are SI. Angles in names ending _deg are degrees.
"""
from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
G0 = 9.80665
RHO0 = 1.225                                            # kg/m3, ISA sea level (the air of the Proptimiser tables)
MU0 = 1.789e-5                                          # Pa s
A0 = 340.3                                              # m/s, speed of sound used for the tip Mach number
CU_RHO, CU_RES = 8960.0, 1.724e-8                       # copper density (kg/m3) and resistivity (Ohm m, 20 C)


def work_dir(aircraft: str) -> Path:
    """work/aerosandbox/<aircraft>: raw tool files, tables and results (git ignores it)."""
    return ROOT / "work" / "aerosandbox" / aircraft


# ================================================================================================== 1. param and component
@dataclass
class Param:
    """One number (or text, or list) of a component. `free`, `lo`, `hi` and `scale` are for the optimiser."""
    value: Any = None
    units: str = ""
    source: str = ""
    placeholder: bool = False
    free: bool = False
    lo: Optional[float] = None
    hi: Optional[float] = None
    scale: Optional[float] = None

    def to_json(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"value": _plain(self.value)}
        for k in ("units", "source"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        for k in ("placeholder", "free"):
            if getattr(self, k):
                d[k] = True
        for k in ("lo", "hi", "scale"):
            if getattr(self, k) is not None:
                d[k] = _plain(getattr(self, k))
        return d

    @classmethod
    def from_json(cls, d: Any) -> "Param":
        if not isinstance(d, dict) or "value" not in d:
            return cls(value=d)
        return cls(**{k: d[k] for k in d if k in {f.name for f in fields(cls)}})

    def __float__(self) -> float:
        return float(self.value)


def _plain(x: Any) -> Any:
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    return x


def P(value: Any, units: str = "", source: str = "", placeholder: bool = False, **kw) -> Param:
    """A param. `placeholder=True` marks a stand-in that has no source yet; its `source` says where the stand-in comes from."""
    return Param(value, units, source, placeholder, **kw)


REGISTRY: Dict[str, type] = {}


class Component:
    """A named set of params. A subclass sets `KIND` and may add methods that read the params."""
    KIND = "spec"

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        REGISTRY[cls.KIND] = cls

    def __init__(self, name: str, **params: Any):
        self.name = name
        self.params: Dict[str, Param] = {}
        for k, v in params.items():
            self.params[k] = v if isinstance(v, Param) else Param(v)

    def __getitem__(self, key: str) -> Any:
        return self.params[key].value

    def __setitem__(self, key: str, value: Any) -> None:
        if isinstance(value, Param):
            self.params[key] = value
        elif key in self.params:
            self.params[key].value = value
        else:
            self.params[key] = Param(value)

    def __contains__(self, key: str) -> bool:
        return key in self.params

    def get(self, key: str, default: Any = None) -> Any:
        return self.params[key].value if key in self.params and self.params[key].value is not None else default

    def num(self, key: str) -> float:
        return float(self.params[key].value)

    def p(self, key: str) -> Param:
        return self.params[key]

    def free(self, *keys: str, **bounds: float) -> "Component":
        """Make params design variables. `comp.free("r_o", lo=0.01, hi=0.04)` also sets the bounds of every named param."""
        for k in keys:
            p = self.params[k]
            p.free = True
            for b in ("lo", "hi", "scale"):
                if b in bounds:
                    setattr(p, b, bounds[b])
        return self

    def fix(self, **values: Any) -> "Component":
        """Fix params at a value: `comp.fix(r_o=0.0175)`. `comp.fix("kv")` (no value) keeps the value it has."""
        for k, v in values.items():
            self.params[k].value = v
            self.params[k].free = False
        return self

    def hold(self, *keys: str) -> "Component":
        for k in keys:
            self.params[k].free = False
        return self

    def free_params(self) -> List[str]:
        return [k for k, p in self.params.items() if p.free]

    def placeholders(self) -> List[str]:
        return [f"{self.name}.{k}" for k, p in self.params.items() if p.placeholder]

    def copy(self) -> "Component":
        return Component.from_json(self.to_json())

    def to_json(self) -> Dict[str, Any]:
        return {"kind": self.KIND, "name": self.name, "params": {k: p.to_json() for k, p in self.params.items()}}

    @classmethod
    def from_json(cls, d: Dict[str, Any]) -> "Component":
        sub = REGISTRY[d["kind"]]
        obj = sub.__new__(sub)
        Component.__init__(obj, d["name"], **{k: Param.from_json(v) for k, v in d["params"].items()})
        return obj

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r}, free={self.free_params()})"


class Spec(Component):
    """A plain set of params with no behaviour: limits, aerodynamic constants, the control requirement."""
    KIND = "spec"


# ===================================================================================================== 2. the components
class Material(Component):
    """A tube material. Params: E_Pa (tension, the bending modulus), E_c_Pa (compression, for local buckling),
    density_kg_m3, tensile_strength_Pa, compressive_strength_Pa, G_Pa, buckling_knockdown."""
    KIND = "material"

    def with_E(self, E_Pa: float, name: Optional[str] = None) -> "Material":
        """A copy with another bending modulus. E_c keeps the ratio E_c / E of this material."""
        m = self.copy()
        ratio = m["E_c_Pa"] / m["E_Pa"]
        m.name = name or m.name
        m.params["E_Pa"].value = float(E_Pa)
        m.params["E_c_Pa"].value = float(E_Pa) * ratio
        return m


class Tube(Component):
    """
    A lift boom: a round carbon tube clamped to the wing at x = wing mid-chord + dx, a rotor at each end, at +/- a from
    the clamp. Params:
      r_o, t        outer radius and wall (m)                                 y   lateral position of the boom (m)
      dx            clamp shift (m)                                           a   hub distance from the clamp (m)
      overhang_m    tube length beyond each hub                               mount_offset_m   thrust line to the tube axis
      clamp_kg      mass of the clamp at the wing                             material         name of the Material component
      min_wall_m, r_over_t_max, tip_slope_max_deg                             limits of the tube
      resonance_margin, resonance_side   f1 stays outside 1P hover +/- margin; "below" or "above" the band
    The beam formulas are the static methods below. They work on numbers and on CasADi expressions.
    """
    KIND = "tube"

    @staticmethod
    def section(r_o, t):
        """Area and second moment of the thin tube section."""
        r_i = r_o - t
        return math.pi * (r_o ** 2 - r_i ** 2), 0.25 * math.pi * (r_o ** 4 - r_i ** 4)

    @staticmethod
    def buckling_stress(E_c, r_o, t, knockdown):
        """sigma_cr = 0.605 E_c t / r_mid x knockdown (local buckling of a thin tube in bending)."""
        return 0.605 * E_c * t / (r_o - 0.5 * t) * knockdown

    @staticmethod
    def f1_hz(E, I, a, m_tip, m_arm):
        """First bending frequency of the cantilever of length a with a tip mass. m_eff = m_tip + 0.236 m_arm (Rayleigh)."""
        import aerosandbox.numpy as anp
        return anp.sqrt(3.0 * E * I / (a ** 3 * (m_tip + 0.236 * m_arm))) / (2.0 * math.pi)


class Rotor(Component):
    """
    The lift rotor: a Proptimiser blade design scaled in radius. Params:
      design, reference_radius_m, design_aircraft   Proptimiser design and the radius of the design file; the aircraft work
                                                    folder that holds the design file and the state file
      scale (free)       R / reference radius     cant (free)   tilt of each rotor about its radial axis (rad)
      blade_diameter_m, blade_pitch_m             the base blade (the pitch of the scaled blade keeps P/D)
      mass_kg, pitch_m                            a bought propeller: its mass and pitch (None: the carbon prop fit and P/D)
      prop_g_a_in2, prop_g_b_in                   AIAA 2016-0581 Eq. 5, carbon: m = a D^2 + b D (g, D in inch)
      tip_clearance_m, tip_mach_max, coaxial_*    clearances, tip Mach limit, coaxial pair (spacing, power factor)
      table_*, momentum_*                         the samples of the CT/CP table (levels L1 to L3) and of the momentum constants
    """
    KIND = "rotor"

    def mass_kg_of(self, D_m):
        """Propeller mass: the bought propeller, or the carbon fit of AIAA 2016-0581 Eq. 5."""
        if self.get("mass_kg") is not None:
            return float(self["mass_kg"])
        d_in = D_m / 0.0254
        return (self.num("prop_g_a_in2") * d_in ** 2 + self.num("prop_g_b_in") * d_in) / 1000.0


class CruiseRotor(Component):
    """The cruise (nose) propeller. Fixed in Rosella: the Currawong nose motor and propeller. Params: design,
    design_aircraft, table_omega_rad_s, table_J, table_fit_J_max, table_poly_degree. Motor numbers come from the airframe."""
    KIND = "cruise_rotor"


class Motor(Component):
    """
    The lift motor. Params: kv (rpm/V, free), q_cap (N m the motor holds for the 180 s peak current, free), survey (the CSV
    of data/), kv_min, kv_max, mass_min_g, mass_max_g (the rows of the survey that the fit uses), and optional maker
    values mass_kg, rm_ohm, i0_A (None: the survey fit gives them).
    """
    KIND = "motor"


class ESC(Component):
    """Params: g_per_A (AIAA 2016-0581 Eq. 2), peak_factor (ESC current over the peak motor current), re_ohm, duty_max, and
    optional mass_kg and current_A of a bought ESC."""
    KIND = "esc"


class Battery(Component):
    """
    Params: cells_s, cap_Ah (free), x_m (free: x of the pack centre), cell_nominal_V, cell_end_V, cell_resistance_mohm,
    c_rate_max, usable_fraction, eq4_p1, eq4_p2 (AIAA 2016-0581 Eq. 4), cal_cells_s, cal_capacity_Ah, cal_mass_kg
    (the calibration pack), optional mass_kg of a bought pack.
    """
    KIND = "battery"

    def mass_kg_of(self, cells_s, cap_Ah):
        """Eq. 4 times the calibration to the pack: m = k (p1 S + p2) C (g, C in mAh)."""
        if self.get("mass_kg") is not None:
            return float(self["mass_kg"])
        p1, p2 = self.num("eq4_p1"), self.num("eq4_p2")
        eq4_cal = (p1 * self.num("cal_cells_s") + p2) * self.num("cal_capacity_Ah") * 1000.0
        k_cal = self.num("cal_mass_kg") * 1000.0 / eq4_cal
        return k_cal * (p1 * cells_s + p2) * cap_Ah * 1000.0 / 1000.0


class Cables(Component):
    """Params: current_density_A_m2, insulation_factor, run_extra_m."""
    KIND = "cables"


class Fuselage(Component):
    """
    The new fuselage: a superellipse body from the nose to the tail boom joint. Params: stations, width_m, height_m,
    superellipse_n, z_centre_m, nose_behind_hub_m, mass_kg_per_m2, bay_x_m ([lo, hi] of the battery centre), battery_Wh_per_L.
    """
    KIND = "fuselage"

    def frames(self, x_hub: float, x_joint: float) -> List[np.ndarray]:
        """The right-half frames (x, y, z) from the nose to the tail boom joint at x_joint."""
        n = int(self["stations"])
        x0 = x_hub + self["nose_behind_hub_m"]
        frames = []
        for x in np.linspace(x0, x_joint, n):
            t = (x - x0) / (x_joint - x0)
            # Nose rises to the full section at 25 % of the length, holds it to 65 %, tapers to the tail boom joint.
            if t < 0.25:
                k = math.sin(0.5 * math.pi * t / 0.25) ** 0.7
            elif t <= 0.65:
                k = 1.0
            else:
                k = max(0.02, math.cos(0.5 * math.pi * (t - 0.65) / 0.35) ** 0.8)
            w, h = 0.5 * self.num("width_m") * k, 0.5 * self.num("height_m") * k
            th = np.linspace(0.0, math.pi, 17)
            e = 2.0 / self["superellipse_n"]
            y = w * np.abs(np.sin(th)) ** e
            z = float(self["z_centre_m"]) + h * np.sign(np.cos(th)) * np.abs(np.cos(th)) ** e
            frames.append(np.column_stack([np.full_like(y, x), y, z]))
        return frames

    def area_m2(self, frames: List[np.ndarray]) -> float:
        """Wetted area, summed over the frames."""
        tot = 0.0
        for f0, f1 in zip(frames[:-1], frames[1:]):
            p0 = 2.0 * np.linalg.norm(np.diff(f0[:, 1:], axis=0), axis=1).sum()
            p1 = 2.0 * np.linalg.norm(np.diff(f1[:, 1:], axis=0), axis=1).sum()
            tot += 0.5 * (p0 + p1) * (f1[0, 0] - f0[0, 0])
        return float(tot)


class PointMass(Component):
    """A mass at a place. Params: mass_kg, x_m, y_m, z_m. `x_from_cg` (m) puts the mass at x_cg + x_from_cg in place of x_m.
    `power_W` is the electrical power of an avionics item."""
    KIND = "point_mass"


class Airframe(Component):
    """The fixed airframe taken from another aircraft of the source tree: its wing, tail and tail boom. Params: base (the
    aircraft folder), static_margin_target (CG = neutral point less this fraction of the MAC), cg_nose_prop_m (the CG lies
    this far behind the nose propeller hub). The derived numbers are in `airframe_model`."""
    KIND = "airframe"


class Control(Component):
    """Hover control requirement. Params: bandwidth_rad_s and bandwidth_length_m (Froude-scaled attitude bandwidth),
    amplitude_rad, margin, yaw_rad_s2, idle_thrust_fraction, k_int (coaxial power factor)."""
    KIND = "control"


# ==================================================================================================== 3. the fidelity level
GROUPS_L0 = ("mass", "cg", "energy", "tw")
GROUPS_L1 = GROUPS_L0 + ("elec",)
GROUPS_ALL = GROUPS_L1 + ("structure", "stiffness", "clear", "control")


@dataclass(frozen=True)
class Level:
    """A fidelity level. `lift` and `cruise`: the rotor model (momentum, table or bemt). `bemt`: the states that use the
    full-space BEMT in spite of that. `groups`: the constraint groups that are on."""
    name: str
    lift: str
    cruise: str
    bemt: Tuple[str, ...]
    groups: Tuple[str, ...]
    note: str = ""


LEVELS: Dict[str, Level] = {
    "L0": Level("L0", "momentum", "momentum", (), GROUPS_L0, "momentum rotor; mass, CG, energy, MTOW, T/W thrust (tip Mach)"),
    "L1": Level("L1", "table", "table", (), GROUPS_L1, "table rotor; adds motor, ESC, duty, current, C-rate"),
    "L2": Level("L2", "table", "table", (), GROUPS_ALL, "table rotor; adds structure, stiffness, clearances, control"),
    "L3": Level("L3", "table", "table", ("H_TO_f", "H_TO_r"), GROUPS_ALL, "full-space BEMT for the H_TO states, table elsewhere"),
    "L4": Level("L4", "bemt", "bemt", (), GROUPS_ALL, "full-space BEMT for every state"),
}


def level(x: Any) -> Level:
    """A Level from its name ("L0" to "L4") or from a Level."""
    return x if isinstance(x, Level) else LEVELS[x]


def parse_levels(spec: str) -> List[str]:
    """"L0..L4" or "L2" or "L0,L1,L2" -> list of level names."""
    spec = spec.replace(" ", "")
    if ".." in spec:
        a, b = spec.split("..")
        return [f"L{k}" for k in range(int(a[1:]), int(b[1:]) + 1)]
    return spec.split(",")


# ================================================================================================= 4. the motor model
class MotorModel:
    """
    The motor fitted on data/motor_survey.csv (log-linear least squares), three relations:
        m  = exp(a0) kv^a1 q_cap^a2        q_cap = (Imax - I0) / Kv_rad, the torque the motor holds for the 180 s peak current
        Rm = exp(b0) kv^b1 m^b2            (the maker states the phase resistance as given in the CSV note)
        I0 = exp(c0) kv^c1 m^c2
    Kv is in rpm/V. Maker values of the component (mass_kg, rm_ohm, i0_A) replace the fit.
    """

    def __init__(self, path: Path, kv_range=(60.0, 450.0), m_range=(150.0, 1600.0)):
        rows = list(csv.DictReader(Path(path).open(encoding="utf-8")))
        data = []
        for r in rows:
            try:
                kv, m, rm, i0, imax = (float(r[k]) for k in ("kv_rpm_per_V", "mass_g", "rm_mohm", "i0_A", "imax_A"))
            except ValueError:
                continue
            if kv_range[0] <= kv <= kv_range[1] and m_range[0] <= m <= m_range[1]:
                data.append((kv, m, rm, i0, imax, r["model"]))
        self.n = len(data)
        a = np.array([d[:5] for d in data])
        kv, m, rm, i0, imax = a.T
        q_cap = (imax - i0) / (kv * 2 * math.pi / 60.0)
        self.models = [d[5] for d in data]
        self.q_range = (float(q_cap.min()), float(q_cap.max()))
        self.mass_fit, self.mass_rms = self._fit(m, [kv, q_cap])
        self.rm_fit, self.rm_rms = self._fit(rm / 1000.0, [kv, m])
        self.i0_fit, self.i0_rms = self._fit(i0, [kv, m])
        self.maker: Dict[str, Optional[float]] = {}

    @staticmethod
    def _fit(y, xs):
        A = np.column_stack([np.ones(len(y))] + [np.log(x) for x in xs])
        coef, *_ = np.linalg.lstsq(A, np.log(y), rcond=None)
        rms = float(np.sqrt(np.mean((A @ coef - np.log(y)) ** 2)))          # RMS of the log error (fraction)
        return coef, rms

    def mass_g(self, kv, q_cap):
        import aerosandbox.numpy as anp
        if self.maker.get("mass_kg") is not None:
            return self.maker["mass_kg"] * 1000.0
        c = self.mass_fit
        return anp.exp(c[0]) * kv ** c[1] * q_cap ** c[2]

    def rm_ohm(self, kv, m_g):
        import aerosandbox.numpy as anp
        if self.maker.get("rm_ohm") is not None:
            return self.maker["rm_ohm"]
        c = self.rm_fit
        return anp.exp(c[0]) * kv ** c[1] * m_g ** c[2]

    def i0_A(self, kv, m_g):
        import aerosandbox.numpy as anp
        if self.maker.get("i0_A") is not None:
            return self.maker["i0_A"]
        c = self.i0_fit
        return anp.exp(c[0]) * kv ** c[1] * m_g ** c[2]

    def summary(self) -> Dict[str, Any]:
        return {"rows": self.n, "mass": list(map(float, self.mass_fit)), "mass_rms_log": self.mass_rms,
                "rm": list(map(float, self.rm_fit)), "rm_rms_log": self.rm_rms,
                "i0": list(map(float, self.i0_fit)), "i0_rms_log": self.i0_rms, "q_cap_range_Nm": self.q_range}


def motor_model(motor: Motor, lvl: Any = "L4") -> MotorModel:
    """The motor model of a Motor component. Every level uses the survey fit; the maker values of the component replace
    its mass, resistance and idle current. A level with a motor curve of a maker part would plug in here."""
    path = Path(motor["survey"])
    path = path if path.is_absolute() else HERE / path
    mm = MotorModel(path, (motor.num("kv_min"), motor.num("kv_max")), (motor.num("mass_min_g"), motor.num("mass_max_g")))
    mm.maker = {k: (None if motor.get(k) is None else float(motor[k])) for k in ("mass_kg", "rm_ohm", "i0_A")}
    return mm


# ================================================================================================== 5. the rotor models
_MODELS: Dict[str, Any] = {}
_CONST: Dict[str, Any] = {}


def proptimiser_home(aircraft: str, designs: Iterable[Tuple[str, str]]) -> Path:
    """work/aerosandbox/<aircraft>/proptimiser: the design file and the state file of each (design, source aircraft) copied by
    hand from the work folder of the source aircraft (Proptimiser reads one home folder)."""
    import shutil
    home = work_dir(aircraft) / "proptimiser"
    for name, src in designs:
        for sub, ext in (("designs", ".yaml"), ("propellers", ".state.json")):
            dst = home / sub / (name + ext)
            if not dst.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(work_dir(src) / "proptimiser" / sub / (name + ext), dst)
    return home


def prop_model(home: Path, design: str):
    """The CasADi Proptimiser model of a design in a Proptimiser home folder."""
    key = f"{home}|{design}"
    if key not in _MODELS:
        os.environ["PROPTIMISER_HOME"] = str(home)
        from proptimiser.casadi_prop import PropellerModel
        from proptimiser.init import Propeller
        _MODELS[key] = PropellerModel.from_propeller(Propeller.load(design), n_psi=1)
    return _MODELS[key]


def omega_guess(model, thrust_N, v_ax, scale=1.0):
    """A shaft speed (rad/s) that gives about thrust_N: T is close to linear in omega^2, so two numeric BEMT solves at 400 and
    700 rad/s fix the line, and a third solve refines it."""
    pts = []
    for w in (400.0, 700.0):
        try:
            pts.append((w, model.solve(w, v_ax, 0.0, 30.0, scale=scale)[0]))
        except RuntimeError:
            return 500.0
    (w1, t1), (w2, t2) = pts
    w = math.sqrt(max(w1 ** 2 + (thrust_N - t1) * (w2 ** 2 - w1 ** 2) / (t2 - t1), 50.0 ** 2))
    try:
        t3 = model.solve(w, v_ax, 0.0, 30.0, scale=scale)[0]
        w = math.sqrt(max(w1 ** 2 + (thrust_N - t3) * (w2 ** 2 - w1 ** 2) / (t2 - t1) + (w ** 2 - w1 ** 2), 50.0 ** 2))
    except RuntimeError:
        pass
    return float(min(max(w, 100.0), 850.0))


def _poly_fit(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float]:
    """Least squares fit y = X c. Returns c and the RMS of (fit - y) over mean |y| (fraction)."""
    c, *_ = np.linalg.lstsq(X, y, rcond=None)
    return c, float(np.sqrt(np.mean((X @ c - y) ** 2)) / np.mean(np.abs(y)))


def _json_cache(path: Path, key: Dict[str, Any], make: Callable[[], Any]):
    """Samples cached as JSON. A cache with another key is made again."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        if d.get("key") == key:
            return d["samples"]
    except (OSError, ValueError):
        pass
    samples = make()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"key": key, "samples": samples}), encoding="utf-8")
    return samples


class LiftTable:
    """CT(M_tip, J, ln s) and CP(M_tip, J, ln s) of the lift blade from numeric Proptimiser solves (cached in work/.../tables).
    T = CT rho n^2 D^4 and P = CP rho n^3 D^5 with n in rev/s. The same function works on numbers and on CasADi expressions."""

    def __init__(self, rotor: Rotor, home: Path, tables: Path):
        R0, self.R0 = float(rotor["reference_radius_m"]), float(rotor["reference_radius_m"])
        self.deg = int(rotor["table_poly_degree"])
        key = {"design": rotor["design"], "omega": rotor["table_omega_rad_s"], "scale": rotor["table_scale"],
               "v_x": rotor["table_v_x_m_s"]}
        model = prop_model(home, rotor["design"])

        def make():
            out = []
            for s in key["scale"]:
                for w in key["omega"]:
                    for V in key["v_x"]:
                        try:
                            T, Q, _ = model.solve(w, V, 0.0, 30.0, scale=s)
                            out.append([w, V, s, T, Q])
                        except RuntimeError:
                            print(f"  lift table: BEMT failed at omega {w} V {V} scale {s}", flush=True)
            return out
        self.samples = np.array(_json_cache(tables / "lift_samples.json", key, make))
        w, V, s, T, Q = self.samples.T
        n, D = w / (2 * math.pi), 2 * R0 * s
        CT, CP = T / (RHO0 * n ** 2 * D ** 4), Q * w / (RHO0 * n ** 3 * D ** 5)
        self.pw = [(i, j) for i in range(self.deg + 1) for j in range(self.deg + 1 - i)]
        X = np.column_stack(self.feats(w * R0 * s / A0, V / (n * D), np.log(s)))
        (self.c_ct, self.rms_ct), (self.c_cp, self.rms_cp) = _poly_fit(X, CT), _poly_fit(X, CP)

    def feats(self, M, J, ls):
        return [M ** i * J ** j for i, j in self.pw] + [ls + 0.0 * M, ls * M]

    def ct_cp(self, M, J, ls):
        f = self.feats(M, J, ls)
        return sum(float(c) * x for c, x in zip(self.c_ct, f)), sum(float(c) * x for c, x in zip(self.c_cp, f))

    def loads(self, omega, V, s, ls=None):
        """T, Q, P of one rotor at shaft speed omega (rad/s), axial speed V and scale s."""
        import aerosandbox.numpy as anp
        ls = anp.log(s) if ls is None else ls
        n, D = omega / (2 * math.pi), 2 * self.R0 * s
        CT, CP = self.ct_cp(omega * self.R0 * s / A0, V / (n * D), ls)
        P = CP * RHO0 * n ** 3 * D ** 5
        return CT * RHO0 * n ** 2 * D ** 4, P / omega, P


class CruiseTable:
    """CT(J, M_tip) and CP(J, M_tip) of the cruise blade, fitted over J up to fit_J_max."""

    def __init__(self, rotor: CruiseRotor, diameter_m: float, home: Path, tables: Path):
        self.D, self.deg = diameter_m, int(rotor["table_poly_degree"])
        key = {"design": rotor["design"], "omega": rotor["table_omega_rad_s"], "J": rotor["table_J"], "D": diameter_m}
        model = prop_model(home, rotor["design"])

        def make():
            out = []
            for w in key["omega"]:
                for J in key["J"]:
                    V = J * w / (2 * math.pi) * diameter_m
                    try:
                        T, Q, _ = model.solve(w, V, 0.0, 15.0)
                        out.append([w, V, T, Q])
                    except RuntimeError:
                        print(f"  cruise table: BEMT failed at omega {w} J {J}", flush=True)
            return out
        self.samples = np.array(_json_cache(tables / "cruise_samples.json", key, make))
        w, V, T, Q = self.samples.T
        n = w / (2 * math.pi)
        J, CT, CP = V / (n * diameter_m), T / (RHO0 * n ** 2 * diameter_m ** 4), Q * w / (RHO0 * n ** 3 * diameter_m ** 5)
        m = J <= float(rotor["table_fit_J_max"]) + 1e-9
        self.J_range = (float(J[m].min()), float(J[m].max()))
        X = np.column_stack(self.feats(J[m], w[m] * 0.5 * diameter_m / A0))
        (self.c_ct, self.rms_ct), (self.c_cp, self.rms_cp) = _poly_fit(X, CT[m]), _poly_fit(X, CP[m])

    def feats(self, J, M):
        return [J ** i for i in range(self.deg + 1)] + [M, M * J]

    def loads(self, omega, V):
        n = omega / (2 * math.pi)
        f = self.feats(V / (n * self.D), omega * 0.5 * self.D / A0)
        CT, CP = (sum(float(c) * x for c, x in zip(cc, f)) for cc in (self.c_ct, self.c_cp))
        P = CP * RHO0 * n ** 3 * self.D ** 5
        return CT * RHO0 * n ** 2 * self.D ** 4, P / omega, P


class RotorModel:
    """
    A rotor at one flight state, at one fidelity. `add(ctx, name, target, V, T_est, V0, s)` adds the rotor to the problem `ctx`
    (optimise.Problem: `ctx.opti`, `ctx.var`, `ctx.init`) and returns omega, T, Q, P_shaft as expressions of its variables.
      momentum  no variable: omega from the constant CT (lift) or the constant J (cruise), P from the momentum theory
      table     variable omega, T from the fitted CT and CP, equality T = target
      bemt      variable omega and the inflow variables of Proptimiser (add_to), equality T = target
    `s` is the geometric scale (an expression) for the lift rotor, and 1.0 for the cruise rotor.
    """

    def __init__(self, kind: str, role: str, rotor: Component, home: Path, tables: Path, work: Path, diameter_m: Optional[float] = None):
        self.kind, self.role, self.rotor, self.home, self.tables = kind, role, rotor, home, tables
        self.lift = role == "lift"
        self.R0 = float(rotor["reference_radius_m"]) if self.lift else 0.5 * float(diameter_m)
        self.design = rotor["design"]
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = prop_model(self.home, self.design)
        return self._model

    def table(self):
        key = f"{self.role}_table|{self.home}"
        if key not in _CONST:
            _CONST[key] = (LiftTable(self.rotor, self.home, self.tables) if self.lift
                           else CruiseTable(self.rotor, 2.0 * self.R0, self.home, self.tables))
        return _CONST[key]

    def momentum(self) -> Dict[str, float]:
        """FM and the hover CT of the base blade (numeric solve at the momentum scale and speed), and the cruise propulsive
        efficiency and advance ratio of the cruise blade (numeric solve at 17 m/s and 18 N). Computed once."""
        key = f"momentum|{self.role}|{self.home}"
        if key not in _CONST:
            if self.lift:
                R0, w = self.R0, float(self.rotor["momentum_omega_rad_s"])
                T, Q, _ = self.model.solve(w, 0.0, 0.0, 30.0, scale=float(self.rotor["momentum_scale"]))
                A, n, D = math.pi * R0 ** 2, w / (2 * math.pi), 2 * R0
                _CONST[key] = {"FM": T ** 1.5 / math.sqrt(2 * RHO0 * A) / (Q * w), "CT0": T / (RHO0 * n ** 2 * D ** 4),
                               "T_hover_N": T}
            else:
                wc = omega_guess(self.model, 18.0, 17.0, 1.0)
                Tc, Qc, _ = self.model.solve(wc, 17.0, 0.0, 15.0)
                _CONST[key] = {"eta_cruise": Tc * 17.0 / (Qc * wc), "J_cruise": 17.0 / (wc / (2 * math.pi) * 2.0 * self.R0)}
        return _CONST[key]

    def add(self, ctx, name: str, target, V, T_est: float, V0: float, s=1.0, R=None) -> Dict[str, Any]:
        import aerosandbox.numpy as anp
        o = ctx.opti
        lift = self.lift
        R = (self.R0 * s) if R is None else R
        s0 = ctx.start("scale", 1.0) if lift else 1.0
        ts = 30.0 if lift else 15.0
        D = 2.0 * R
        if self.kind == "momentum":
            mc = self.momentum()
            if lift:
                P = target * (0.5 * V + anp.sqrt((0.5 * V) ** 2 + target / (2.0 * RHO0 * math.pi * R ** 2))) / mc["FM"]
                w = 2.0 * math.pi * anp.sqrt(target / (mc["CT0"] * RHO0)) / D ** 2
            else:
                P = target * V / mc["eta_cruise"]
                w = 2.0 * math.pi * V / (mc["J_cruise"] * D)
            return {"omega": w, "T": target, "Q": P / w, "P_shaft": P}
        model = self.model                                              # Proptimiser loads only for the table and BEMT levels
        lo, hi = {("lift", "table"): (250.0, 800.0), ("cruise", "table"): (400.0, 800.0),
                  ("lift", "bemt"): (100.0, 800.0), ("cruise", "bemt"): (150.0, 900.0)}[(self.role, self.kind)]
        key = ("wguess", self.design, round(T_est, 1), round(float(V0), 1), round(s0, 3))
        w0 = ctx.init.get("w_" + name)
        if w0 is None:
            if key not in _CONST:
                _CONST[key] = omega_guess(model, T_est, float(V0), s0)
            w0 = _CONST[key]
        w0 = min(max(float(w0), lo), hi)
        w = ctx.state("w_" + name, w0, lo, hi, scale=300.0)
        if self.kind == "table":
            T, Q, P = self.table().loads(w, V, s) if lift else self.table().loads(w, V)
        else:
            out = model.add_to(o, w, V, 0.0, ts, scale=s)
            for get_w in (lambda: w0, lambda: omega_guess(model, T_est, float(V0), s0)):
                try:
                    model.warm_start(o, out, get_w(), float(V0), 0.0, ts, scale=s0)
                    break
                except RuntimeError:
                    continue
            T, Q, P = out.thrust_N, out.torque_Nm, out.shaft_power_W
        o.subject_to(T / T_est == target / T_est)
        return {"omega": w, "T": T, "Q": Q, "P_shaft": P}


def rotor_model(rotor: Component, lvl: Any, state: str = "", role: Optional[str] = None, aircraft: str = "rosella",
                diameter_m: Optional[float] = None, designs: Iterable[Tuple[str, str]] = ()) -> RotorModel:
    """
    The model of `rotor` at the level `lvl` for the flight state `state` (for example "H_TO_f"). The kind follows the level:
    the `lift` or `cruise` entry of the level, and "bemt" for the states the level lists in `bemt`.
    rotor: a Rotor (role lift) or a CruiseRotor (role cruise; give its diameter_m). designs: (design, source aircraft) pairs
    for the Proptimiser home folder of this aircraft.
    """
    lv = level(lvl)
    role = role or ("lift" if isinstance(rotor, Rotor) else "cruise")
    kind = "bemt" if state in lv.bemt else getattr(lv, role)
    work = work_dir(aircraft)
    home = proptimiser_home(aircraft, list(designs) or [(rotor["design"], rotor["design_aircraft"])])
    return RotorModel(kind, role, rotor, home, work / "tables", work, diameter_m)


# ================================================================================================== 6. the airframe model
def _split_planform(pf: Dict[str, Any], etas: List[float]) -> Dict[str, Any]:
    """The planform with extra sections at the span fractions etas. A new section interpolates chord, x offset and twist
    along its panel, and takes the dihedral and the foil of the panel (the inner section). A straight panel keeps its shape."""
    secs = [dict(s) for s in pf["sections"]]
    tip = secs[-1]["y"]
    for eta in sorted(set(etas)):
        y = eta * tip
        if any(abs(s["y"] - y) < 1e-9 for s in secs):
            continue
        k = max(i for i, s in enumerate(secs) if s["y"] < y)
        a, b = secs[k], secs[k + 1]
        t = (y - a["y"]) / (b["y"] - a["y"])
        new = dict(a)
        for key in ("chord", "x_offset", "twist_deg"):
            new[key] = a[key] + t * (b[key] - a[key])
        new["y"] = y
        secs.insert(k + 1, new)
    return {**pf, "sections": secs}


def _controls_of(doc: Dict[str, Any], parent: str) -> List[Dict[str, Any]]:
    """The control surfaces of a wing for AeroSandbox. A left and right pair with one shape is one antisymmetric surface."""
    from aeroplan import adh_doc
    groups: Dict[Tuple, Dict[str, Any]] = {}
    for _, item, _ in adh_doc.iter_nodes(doc):
        cs = (item.get("muas") or {}).get("control_surface")
        if not cs or cs["parent"] != parent:
            continue
        key = (tuple(cs["eta_span"]), cs["hinge_x_over_c"])
        g = groups.setdefault(key, {"eta": list(cs["eta_span"]), "hinge_x_over_c": cs["hinge_x_over_c"], "names": [],
                                    "sides": set()})
        g["names"].append(item["muas"]["instance"])
        g["sides"].add(cs.get("side", "both"))
    out = []
    for g in groups.values():
        pair = g["sides"] == {"left", "right"}
        name = g["names"][0].rsplit("_", 1)[0] if pair else g["names"][0]
        out.append({"name": name, "symmetric": not pair, "eta": g["eta"], "hinge_x_over_c": g["hinge_x_over_c"]})
    return out


def surface_spec(doc: Dict[str, Any], inst: str) -> Dict[str, Any]:
    """A lifting surface of the ADH document as a tool-neutral dict (sections, controls, foils) for `build_airplane`."""
    from aeroplan import adh_doc
    from aeroplan.geometry import _edges, foils_of, planform_wing
    item = adh_doc.find(doc, inst)
    pf = item["muas"]["planform"]
    controls = _controls_of(doc, inst)
    pf2 = _split_planform(pf, [e for c in controls for e in c["eta"]])
    le, te = _edges(planform_wing(pf2))
    tip = pf2["sections"][-1]["y"]
    sections = []
    for sec, a, b in zip(pf2["sections"], le, te):
        here = [{"name": c["name"], "symmetric": c["symmetric"], "hinge_x_over_c": c["hinge_x_over_c"]}
                for c in controls if c["eta"][0] * tip - 1e-9 <= sec["y"] < c["eta"][1] * tip - 1e-9]
        # AeroSandbox ignores the trailing edge point: the angle of the chord line (section twist and the pitch
        # incidence ry_deg of the surface) must go in as the twist. A fin has its span along z: its twist stays.
        twist = float(sec["twist_deg"]) if pf["kind"] == "FIN" else math.degrees(math.atan2(a[2] - b[2], b[0] - a[0]))
        sections.append({"xyz_le": [float(v) for v in a], "chord": float(np.linalg.norm(b - a)),
                         "twist_deg": twist, "foil": sec["foil"], "controls": here})
    mirror = pf.get("symmetric", True) and (pf["kind"] != "FIN" or pf.get("two_sided", True))
    return {"name": inst, "mirror": bool(mirror), "sections": sections,
            "foils": {k: v.tolist() for k, v in foils_of(item).items()}}


def build_airplane(spec: Dict[str, Any]):
    """An asb.Airplane from the tool-neutral spec: reference, surfaces, fuselages (frames of the right half) and propulsion."""
    import aerosandbox as asb

    foils: Dict[str, Any] = {}
    surfaces = []
    for s in spec["surfaces"]:
        xsecs = []
        for sec in s["sections"]:
            name = sec["foil"]
            if name not in foils:
                foils[name] = asb.Airfoil(name=name, coordinates=np.asarray(s["foils"][name], float))
            controls = [asb.ControlSurface(name=c["name"], symmetric=c["symmetric"], hinge_point=c["hinge_x_over_c"],
                                           trailing_edge=True, deflection=0.0) for c in sec.get("controls", [])]
            xsecs.append(asb.WingXSec(xyz_le=sec["xyz_le"], chord=sec["chord"], twist=sec["twist_deg"],
                                      airfoil=foils[name], control_surfaces=controls))
        surfaces.append(asb.Wing(name=s["name"], symmetric=bool(s["mirror"]), xsecs=xsecs))
    fuselages = []
    for body in spec.get("fuselages") or []:
        xsecs = []
        for f in body["frames"]:
            f = np.asarray(f, float)
            zmin, zmax = f[:, 2].min(), f[:, 2].max()
            xsecs.append(asb.FuselageXSec(xyz_c=[float(f[0, 0]), 0.0, float(0.5 * (zmin + zmax))],
                                          width=float(2.0 * np.abs(f[:, 1]).max()), height=float(zmax - zmin),
                                          shape=2.0))
        fuselages.append(asb.Fuselage(name=body["name"], xsecs=xsecs))
    prop = spec["propulsion"]
    propulsors = [asb.Propulsor(name="propeller", xyz_c=prop["hub"], xyz_normal=prop["thrust_axis"],
                                radius=0.5 * prop["diameter_m"])]
    ref = spec["reference"]
    return asb.Airplane(name=spec["name"], xyz_ref=ref["xyz_ref"], wings=surfaces, fuselages=fuselages,
                        propulsors=propulsors, s_ref=ref["s_m2"], b_ref=ref["b_m"], c_ref=ref["c_m"])


class AirframeModel:
    """The fixed airframe of Rosella at one fidelity: the wing, tail and tail boom of the base aircraft, the numbers taken from
    them (positions, masses of the kept items), the neutral point (vortex lattice and the body term of AeroBuildup) and the
    polar (AeroBuildup). Made by `airframe_model`."""

    def __init__(self, airframe: Airframe, fuselage: Fuselage, root: Path = ROOT):
        from aeroplan import adh_doc, source_tree
        from aeroplan.geometry import body_frames
        self.comp, self.fus = airframe, fuselage
        acft = source_tree.read(root / "aircraft" / airframe["base"])
        doc = acft.doc
        air = adh_doc.node(doc, "1.2")["muas"]
        self.ref = air["reference"]
        self.s_ref, self.b_ref, self.c_ref = (air["reference"][k]["value"] for k in ("s_ref", "b_ref", "c_ref"))
        pm = {p["tag"]: p for p in air["point_masses"]}
        self.points = pm
        self.wing_pts = [p for t, p in pm.items() if t.startswith("WINGS")]
        self.tail_pts = [p for t, p in pm.items() if t.startswith("TAIL-S")]
        self.m_wing = sum(p["mass"]["value"] for p in self.wing_pts)
        self.m_tail = sum(p["mass"]["value"] for p in self.tail_pts)
        self.m_tail_boom = pm["TAIL-BOOM"]["mass"]["value"]
        self.m_avionics = pm["AVIONICS-REST"]["mass"]["value"]
        self.surfaces = {n: surface_spec(doc, n) for n in ("wing_main", "htail", "fin")}
        self.htail_le_x = float(min(s_["xyz_le"][0] for s_ in self.surfaces["htail"]["sections"]))      # planform LE of the htail
        self.tail_boom_frames = [f.tolist() for f in body_frames(adh_doc.find(doc, "tail_boom")["geometry"]["body"])]
        self.tail_boom_z = float(np.array(self.tail_boom_frames[0])[:, 2].mean())   # axis height at the joint end (lift booms are level with it)
        prop = adh_doc.find(doc, "prop_cruise")["muas"]
        self.cruise_hub_base = prop["propeller"]["hub"]["xyz"]
        ps = prop["propulsion_system"]
        m = ps["motor"]
        self.cruise = {"kv_rad_s_V": m["kv"]["value"], "i0_A": m["i0"]["value"], "kappa": m["kappa"],
                       "r_tot_ohm": m["r_tot"]["value"], "mass_kg": m["mass"]["value"], "imax_A": m["imax_continuous"]["value"],
                       "diameter_m": prop["propeller"]["diameter"]["value"]}
        self.cruise_offsets = {k: pm[t]["position"]["xyz"][0] - self.cruise_hub_base[0] for k, t in
                               (("motor", "PROPULSION-MOTOR"), ("esc", "PROPULSION-ESC"), ("prop", "PROPULSION-PROP"),
                                ("rest", "PROPULSION-REST"))}
        self.m_cruise_esc = pm["PROPULSION-ESC"]["mass"]["value"]
        self.m_cruise_prop = pm["PROPULSION-PROP"]["mass"]["value"]
        self.m_cruise_rest = pm["PROPULSION-REST"]["mass"]["value"]
        self.neutral_point = self._neutral_point()
        self.wing_le_x, self.wing_te_x = self._wing_edges()
        self.x_cg = self.neutral_point - float(airframe["static_margin_target"]) * self.c_ref
        self.x_hub = self.x_cg - float(airframe["cg_nose_prop_m"])
        self.polar = self._polar()

    def _wing_edges(self):
        """Linear fits of the wing LE and TE x against y over the inner 1 m (where the booms sit)."""
        sec = self.surfaces["wing_main"]["sections"]
        y = np.array([s["xyz_le"][1] for s in sec])
        le = np.array([s["xyz_le"][0] for s in sec])
        te = le + np.array([s["chord"] for s in sec])
        m = y <= 1.0
        return (np.polyfit(y[m], le[m], 1), np.polyfit(y[m], te[m], 1))

    def x_cg_guess(self):
        return getattr(self, "x_cg", 0.12)

    def new_fuselage_frames(self) -> List[List[List[float]]]:
        """The new fuselage. The nose follows the hub x. Before the hub x is known (the neutral point run) the guess is -0.65."""
        x_hub = self.x_hub if hasattr(self, "x_hub") else -0.65
        return [f.tolist() for f in self.fus.frames(x_hub, self.tail_boom_frames[0][0][0])]

    def _build(self, fuselages: bool):
        spec = {"name": "Rosella", "reference": {"s_m2": self.s_ref, "b_m": self.b_ref, "c_m": self.c_ref,
                                                 "xyz_ref": [self.x_cg_guess(), 0.0, 0.0]},
                "surfaces": [self.surfaces[n] for n in ("wing_main", "htail", "fin")],
                "fuselages": ([{"name": "fuselage", "frames": self.new_fuselage_frames()},
                               {"name": "tail_boom", "frames": self.tail_boom_frames}] if fuselages else []),
                "propulsion": {"hub": [self.x_hub if hasattr(self, "x_hub") else -0.65, 0.0, -0.035],
                               "thrust_axis": [-1.0, 0.0, 0.0], "diameter_m": self.cruise["diameter_m"]}}
        return build_airplane(spec)

    def _neutral_point(self):
        """x of the neutral point, alpha 0 and 4 deg: the vortex lattice of the wing, htail and fin, plus the body term
        (fuselage and tail boom) of the AeroBuildup body model. The VLM has no body, and the body moves the NP forward
        by about 10 mm (Currawong check, 2026-10-18)."""
        import aerosandbox as asb
        plane = self._build(fuselages=False)
        full = self._build(fuselages=True)
        bodies = asb.Airplane(name="bodies", xyz_ref=full.xyz_ref, fuselages=full.fuselages,
                              s_ref=full.s_ref, c_ref=full.c_ref, b_ref=full.b_ref)
        out = []
        for a in (0.0, 4.0):
            op = asb.OperatingPoint(atmosphere=asb.Atmosphere(altitude=0.0), velocity=17.0, alpha=a)
            r = asb.VortexLatticeMethod(plane, op, spanwise_resolution=16, chordwise_resolution=12, align_trailing_vortices_with_wind=False).run()
            b = asb.AeroBuildup(bodies, op).run()
            out.append((float(np.ravel(r["CL"])[0]) + float(np.ravel(b["CL"])[0]),
                        float(np.ravel(r["Cm"])[0]) + float(np.ravel(b["Cm"])[0])))
        dCL, dCm = (out[1][0] - out[0][0]), (out[1][1] - out[0][1])
        return float(plane.xyz_ref[0] - self.c_ref * dCm / dCL)

    def _polar(self):
        """AeroBuildup polar of the airframe with the new fuselage: CD = CD0 + k CL^2 over CL 0.2 to 0.9, and CL at 12 deg."""
        import aerosandbox as asb
        plane = self._build(fuselages=True)
        alphas = np.arange(-2.0, 13.0, 1.0)
        cl, cd = [], []
        for a in alphas:
            op = asb.OperatingPoint(atmosphere=asb.Atmosphere(altitude=53.0), velocity=17.0, alpha=float(a))
            r = asb.AeroBuildup(plane, op).run()
            cl.append(float(np.ravel(r["CL"])[0]))
            cd.append(float(np.ravel(r["CD"])[0]))
        cl, cd = np.array(cl), np.array(cd)
        m = (cl > 0.2) & (cl < 0.9)
        k, cd0 = np.polyfit(cl[m] ** 2, cd[m], 1)
        return {"cd0": float(cd0), "k": float(k), "cl_max": float(cl[-1]), "alpha_max_deg": float(alphas[-1]),
                "alphas_deg": alphas.tolist(), "cl": cl.tolist(), "cd": cd.tolist()}

    def fuselage_area(self):
        return self.fus.area_m2([np.array(f) for f in self.new_fuselage_frames()])

    def fuselage_length(self):
        fr = self.new_fuselage_frames()
        return float(fr[-1][0][0] - fr[0][0][0])

    def fuselage_mid_x(self):
        fr = self.new_fuselage_frames()
        return float(0.5 * (fr[-1][0][0] + fr[0][0][0]))

    def chord_at(self, y):
        return (self.wing_te_x[0] - self.wing_le_x[0]) * y + (self.wing_te_x[1] - self.wing_le_x[1])

    def le_x(self, y):
        return self.wing_le_x[0] * y + self.wing_le_x[1]

    def te_x(self, y):
        return self.wing_te_x[0] * y + self.wing_te_x[1]

    def summary(self) -> Dict[str, Any]:
        return {"c_ref_m": self.c_ref, "htail_le_x_m": self.htail_le_x, "neutral_point_m": self.neutral_point,
                "x_cg_m": self.x_cg, "x_nose_hub_m": self.x_hub,
                "polar": {k: self.polar[k] for k in ("cd0", "k", "cl_max")}}


def airframe_model(airframe: Airframe, lvl: Any = "L4", fuselage: Optional[Fuselage] = None, root: Path = ROOT) -> AirframeModel:
    """The airframe at the level `lvl`. Every level uses the vortex lattice neutral point and the AeroBuildup polar; a higher
    level (a polar from a CFD run, a full vortex lattice polar) would replace the polar here."""
    if fuselage is None:
        raise ValueError("airframe_model needs the Fuselage component: the body term of the neutral point depends on it")
    return AirframeModel(airframe, fuselage, root)


# ============================================================================================== 7. the electric chain
def electric_chain(torque_Nm, omega_rad_s, duty, motor, v_bus_V):
    """
    The motor and ESC chain of Propalyser (estimate/chain.py): a first-order DC motor behind an ESC that works as a
    chopper. Works on numbers and on CasADi expressions.

        I_motor = I0 + (Q + Q0) * Kv                    Kv in rad/s per volt
        V_term  = omega / (kappa * Kv) + R_tot * I_motor
        residual = duty * V_bus - V_term                (zero at the solution)
        I_bat   = duty * I_motor,  P_bat = V_bus * I_bat

    motor: kv_rad_s_V, i0_A, kappa, r_tot_ohm, q0_Nm.
    """
    kv = motor["kv_rad_s_V"]
    i_motor = motor["i0_A"] + (torque_Nm + motor.get("q0_Nm", 0.0)) * kv
    v_term = omega_rad_s / (motor["kappa"] * kv) + motor["r_tot_ohm"] * i_motor
    return {"i_motor_A": i_motor, "v_term_V": v_term, "residual_V": duty * v_bus_V - v_term,
            "i_bat_A": duty * i_motor, "p_bat_W": v_bus_V * duty * i_motor, "p_motor_in_W": v_term * i_motor}


# ============================================================================================= 8. blade check (Jung et al. 2021)
# Jung et al. 2021, Unmanned Systems 9(4) 321-332, DOI 10.1142/S2301385021500163 (CC BY 4.0). The data are in
# data/jung2021_blades.csv and data/jung2021_fit.json (SI units). A check only: it compares a scaled blade with scanned blades.
DATA = HERE / "data"


def jung_blades(path=None) -> Dict[str, Dict[str, Any]]:
    """{blade: {D_m, r_over_R, c_m, beta_rad, digitised}} of the scanned blades, as numpy arrays."""
    path = Path(path) if path else DATA / "jung2021_blades.csv"
    with open(path, newline="") as f:
        rows = list(csv.DictReader(r for r in f if not r.startswith("#")))
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        b = out.setdefault(row["blade"], {"D_m": float(row["D_m"]), "r_over_R": [], "c_m": [], "beta_rad": [],
                                          "digitised": row["digitised"].strip().lower() == "true"})
        b["r_over_R"].append(float(row["r_over_R"]))
        b["c_m"].append(float(row["c_m"]))
        b["beta_rad"].append(float(row["beta_rad"]))
    for b in out.values():
        for k in ("r_over_R", "c_m", "beta_rad"):
            b[k] = np.array(b[k])
    return out


def jung_c_max(D_m: float, path=None) -> float:
    """Maximum chord in m from the Fig. 10 regression."""
    p = json.loads(Path(path or DATA / "jung2021_fit.json").read_text())["c_max_fit"]
    return p["slope"] * D_m + p["intercept_m"]


def _jung_curves(blades, name):
    b = blades[name]
    return b["r_over_R"], b["c_m"] / (b["D_m"] / 2.0), b["beta_rad"]


def jung_compare(r_over_R, c_m, beta_rad, D_m, reference="Tmotor_29", at=(0.25, 0.5, 0.75, 0.95), blades=None) -> Dict[str, Any]:
    """Differences of a blade against a Jung curve (interpolated in r/R) and the c_max fit. Returns a dict: c_max_m, c_max_fit_m,
    c_max_ratio, and rows of (r/R, c/R, c/R ref, d(c/R), beta deg, beta ref deg, d beta deg)."""
    blades = blades or jung_blades()
    r = np.asarray(r_over_R, float)
    cR = np.asarray(c_m, float) / (D_m / 2.0)
    br, cr, bt = _jung_curves(blades, reference)
    rows = []
    for x in at:
        c0 = float(np.interp(x, r, cR))
        b0 = float(np.degrees(np.interp(x, r, beta_rad)))
        c1 = float(np.interp(x, br, cr))
        b1 = float(np.degrees(np.interp(x, br, bt)))
        rows.append((x, c0, c1, c0 - c1, b0, b1, b0 - b1))
    cm = float(np.max(c_m))
    fit = float(jung_c_max(D_m))
    return {"c_max_m": cm, "c_max_fit_m": fit, "c_max_ratio": cm / fit, "r_at_c_max": float(r[int(np.argmax(c_m))]),
            "reference": reference, "rows": rows}


def jung_plot(ax_chord, ax_twist, r_over_R, c_m, beta_rad, D_m, label="blade", blades=None) -> None:
    """Draw c/R and twist (deg) of a blade over the Jung T-motor points."""
    blades = blades or jung_blades()
    for name, mk in (("Tmotor_18", "s"), ("Tmotor_29", "o"), ("Tmotor_40", "^")):
        br, cr, bt = _jung_curves(blades, name)
        ax_chord.plot(br, cr, mk, mfc="none", label=name.replace("_", " ") + " (Jung)")
        ax_twist.plot(br, np.degrees(bt), mk, mfc="none", label=name.replace("_", " ") + " (Jung)")
    ax_chord.plot(r_over_R, np.asarray(c_m) / (D_m / 2.0), "k-", label=label)
    ax_twist.plot(r_over_R, np.degrees(beta_rad), "k-", label=label)
    ax_chord.set_xlabel("r/R")
    ax_chord.set_ylabel("c/R")
    ax_chord.legend(fontsize=7)
    ax_twist.set_xlabel("r/R")
    ax_twist.set_ylabel("twist (deg)")


def scaled_blade(rotor: Rotor, scale: float, aircraft: str = "rosella") -> Dict[str, Any]:
    """The chord (m) and twist (rad) of the lift blade at the geometric scale `scale` (R = scale x reference radius). The blade
    state is the Proptimiser state file of the design: chord and twist on its stations, hub radius 0.025 m (the design file)."""
    home = proptimiser_home(aircraft, [(rotor["design"], rotor["design_aircraft"])])
    state = json.loads((home / "propellers" / f"{rotor['design']}.state.json").read_text())
    R0 = float(rotor["reference_radius_m"])
    c, b = np.ravel(state["c"]), np.ravel(state["beta"])
    x = np.linspace(0.025, R0, len(c)) / R0
    return {"r_over_R": x, "c_m": c * scale, "beta_rad": b, "D_m": 2.0 * R0 * scale}
