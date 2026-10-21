"""
Aircraft models. One class for each class of aircraft. A model holds components (component.py) and evaluates one flight
condition at a time, in the way Proptimiser `PropellerModel` evaluates one propeller state:

    model = QuadplaneModel("rosella", components, layout="H4")
    out = model.build(problem)                  # all conditions of the mission, in one optimisation problem
    out = model.add_to(problem, condition)      # one flight condition (needs model.design(problem) first)

`problem` is an `optimise.Problem` (an `asb.Opti` with named variables, limits and the level of the solve). The model calls
the level functions of component.py (`rotor_model`, `airframe_model`, `motor_model`), so one model runs at every fidelity.

  QuadplaneModel    lift rotors on two booms, a cruise propeller, a wing (Rosella). The Opti model of the sizing.
  FixedWingModel    a fixed-wing aircraft of the ADH tree: geometry, polar, cruise trim, static check (jobs of the spoke).
  MultirotorModel   a multirotor: body drag, and the segment analysis of Bershadsky, Haviland and Johnson (EMST).

`main()` runs a job in the AeroSandbox Python for the spoke: `python model.py job.json result.json`.
A model is saved with `model.save(path)` in `settings/<aircraft>.json` and read back with `AircraftModel.load(path)`.
"""
from __future__ import annotations

import json
import math
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from component import (A0, CU_RES, CU_RHO, G0, HERE, RHO0, ROOT, Airframe, Battery, Cables, Component, Control, CruiseRotor,
                       ESC, Fuselage, Material, Motor, PointMass, Rotor, Spec, Tube, airframe_model, build_airplane,
                       electric_chain, level, motor_model, rotor_model, work_dir)
from mission import FlightCondition, Mission

FORMAT = "aeroplan-asb-model/1"
SETTINGS = HERE / "settings"

#: design variable name -> (component, param). The names are the keys of `design` in a Result.
DESIGN_VARS = {"t_boom": ("boom", "t"), "r_boom": ("boom", "r_o"), "y_b": ("boom", "y"), "dx": ("boom", "dx"),
               "a": ("boom", "a"), "scale": ("rotor", "scale"), "kv": ("motor", "kv"), "q_cap": ("motor", "q_cap"),
               "cant": ("rotor", "cant"), "cap_Ah": ("battery", "cap_Ah"), "x_batt": ("battery", "x_m")}


# ============================================================================================================ the base
class AircraftModel:
    """Components by key, the layout, and the file of the aircraft."""
    KIND = "aircraft"

    def __init__(self, name: str, components: Dict[str, Component], **config: Any):
        self.name = name
        self.c: Dict[str, Component] = dict(components)
        self.config = dict(config)
        self.af = None                                  # the AirframeModel, made by `derive`
        self.result_summary: Dict[str, Any] = {}

    # -- the file of the aircraft
    def to_json(self) -> Dict[str, Any]:
        return {"format": FORMAT, "aircraft": self.name, "model": self.KIND, "config": self.config,
                "components": {k: c.to_json() for k, c in self.c.items()}, "result": self.result_summary}

    def save(self, path: Optional[Path] = None) -> Path:
        """Write settings/<aircraft>.json: the components with every param, and the summary of the last result."""
        path = Path(path) if path else SETTINGS / f"{self.name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=1) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def load(path: Any) -> "AircraftModel":
        """Read a model file. `path` is a file, or an aircraft name (settings/<name>.json)."""
        p = Path(path)
        if not p.suffix:
            p = SETTINGS / f"{path}.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("format") != FORMAT:
            raise ValueError(f"{p}: format {d.get('format')!r}, not {FORMAT!r}")
        comps = {k: Component.from_json(v) for k, v in d["components"].items()}
        cls = {"quadplane": QuadplaneModel}[d["model"]]
        m = cls(d["aircraft"], comps, **d.get("config", {}))
        m.result_summary = d.get("result", {})
        return m

    # -- params
    def params(self) -> List[Tuple[str, str, Any]]:
        """(component key, param name, Param) of every param of every component."""
        return [(ck, pk, p) for ck, c in self.c.items() for pk, p in c.params.items()]

    def free_params(self) -> List[str]:
        return [f"{ck}.{pk}" for ck, pk, p in self.params() if p.free]

    def placeholders(self) -> List[str]:
        return [x for c in self.c.values() for x in c.placeholders()]

    def free(self, *paths: str, **bounds: float) -> "AircraftModel":
        """Make params free by path: `model.free("rotor.scale", "motor.kv")`."""
        for path in paths:
            ck, pk = path.split(".")
            self.c[ck].free(pk, **bounds)
        return self

    def fix(self, **values: Any) -> "AircraftModel":
        """Fix params by path with `__` for the dot: `model.fix(boom__r_o=0.0175, boom__t=0.001)`."""
        for path, v in values.items():
            ck, pk = path.split("__")
            self.c[ck].fix(**{pk: v})
        return self

    def hold(self, *paths: str) -> "AircraftModel":
        """Fix params at their present value."""
        for path in paths:
            ck, pk = path.split(".")
            self.c[ck].hold(pk)
        return self

    def copy(self) -> "AircraftModel":
        m = type(self)(self.name, {k: c.copy() for k, c in self.c.items()}, **self.config)
        m.af = self.af
        m.result_summary = dict(self.result_summary)
        return m


# =========================================================================================================== quadplane
def _lim(p: Any, lo: Optional[float], hi: Optional[float]):
    return (p.lo if p.lo is not None else lo), (p.hi if p.hi is not None else hi)


class QuadplaneModel(AircraftModel):
    """
    A quadplane: the base airframe (Currawong), a new fuselage, two lift booms with a rotor at each end (layout H4: one rotor
    on each end, H8: a coaxial pair on each end), and the nose propeller for cruise. Components (keys):
      limits, mission, airframe, fuselage, boom_material, boom, rotor, cruise_rotor, motor, esc, battery, cables,
      avionics, landing_gear, cargo, camera, cruise_aero, control
    Design variables (the params that are `free`): see DESIGN_VARS. The layout and the cell count are `config`.
    Equations: Bershadsky, Haviland, Johnson, AIAA 2016-0581 (masses, motor chain), the beam and control rules in the
    comments below. The frame is x aft, y right, z up.
    """
    KIND = "quadplane"

    def __init__(self, name: str, components: Dict[str, Component], layout: str = "H4", **config: Any):
        super().__init__(name, components, layout=layout, **config)
        self.layout = layout
        self.n_per = 2 if layout == "H8" else 1
        self.N = 4 * self.n_per
        self.d: Optional[SimpleNamespace] = None

    # -- helpers
    def derive(self, lvl: Any = "L4"):
        """The airframe model (neutral point, polar): made once for this airframe and fuselage."""
        if self.af is None:
            self.af = airframe_model(self.c["airframe"], lvl, self.c["fuselage"])
        return self.af

    def _rotor(self, ctx, role: str, state: str):
        if role == "lift":
            return rotor_model(self.c["rotor"], ctx.level, state, "lift", self.name)
        cr = self.c["cruise_rotor"]
        return rotor_model(cr, ctx.level, state, "cruise", self.name, diameter_m=self.af.cruise["diameter_m"])

    # -- the design: variables, masses, boom, wiring, battery, mass list and CG
    def design(self, ctx) -> SimpleNamespace:
        import aerosandbox.numpy as anp
        c, air, o = self.c, self.derive(ctx.level), ctx.opti
        boom, rot, mot, esc, bat, cab, lim = (c[k] for k in ("boom", "rotor", "motor", "esc", "battery", "cables", "limits"))
        mat, fz, ctl = c["boom_material"], c["fuselage"], c["control"]
        d = SimpleNamespace(air=air, opti=o)
        d.S, d.N, d.n_per = int(bat["cells_s"]), self.N, self.n_per
        d.V_cell, d.V_end = bat.num("cell_nominal_V"), bat.num("cell_end_V")
        R_ref = rot.num("reference_radius_m")
        mm = motor_model(mot, ctx.level)
        d.motor_fit = mm

        # ---- design variables (the order fixes the order of the Opti variables)
        d.t = ctx.design("t_boom", boom.p("t"), lo=boom.num("min_wall_m"), hi=0.005)
        d.r_o = ctx.design("r_boom", boom.p("r_o"))
        d.y_b = ctx.design("y_b", boom.p("y"))
        d.dx = ctx.design("dx", boom.p("dx"))
        d.a = ctx.design("a", boom.p("a"))
        d.s = ctx.design("scale", rot.p("scale"))
        d.kv = ctx.design("kv", mot.p("kv"))
        d.q_cap = ctx.design("q_cap", mot.p("q_cap"))
        d.cant = ctx.design("cant", rot.p("cant"))
        d.cap = ctx.design("cap_Ah", bat.p("cap_Ah"))
        d.x_bat = ctx.design("x_batt", bat.p("x_m"))
        d.R = R_ref * d.s
        d.D = 2.0 * d.R
        d.x_cg = air.x_cg
        d.R_ref = R_ref

        # ---- motor, prop
        d.m_motor_g = mm.mass_g(d.kv, d.q_cap)
        d.rm = mm.rm_ohm(d.kv, d.m_motor_g)
        d.i0 = mm.i0_A(d.kv, d.m_motor_g)
        d.m_motor = d.m_motor_g / 1000.0
        d.m_prop = rot.mass_kg_of(d.D)
        d.kv_rad = d.kv * 2.0 * math.pi / 60.0
        d.m_mount = mot.num("mount_kg")
        d.m_clamp = boom.num("clamp_kg")

        # ---- boom
        d.over = boom.num("overhang_m")
        d.L_boom = 2.0 * d.a + 2.0 * d.over
        d.r_i = d.r_o - d.t
        d.A_sec, d.I_sec = Tube.section(d.r_o, d.t)
        d.rho_boom = mat.num("density_kg_m3")
        d.m_boom_each = d.rho_boom * d.A_sec * d.L_boom
        d.m_boom = 2.0 * d.m_boom_each
        d.x_c = 0.5 * (air.te_x(0.0) + air.le_x(0.0)) + d.dx
        d.x_f, d.x_r = d.x_c - d.a, d.x_c + d.a
        d.z_b = air.tail_boom_z                              # user 2026-10-17: lift booms level with the tail boom
        d.z_rotor = d.z_b + boom.num("mount_offset_m")       # the rotor plane sits one mount offset above the boom axis

        # ---- cables, ESC, battery
        d.I_pk = ctx.state("I_pk", 60.0, 5.0, 250.0, scale=50.0)
        d.A_cu = d.I_pk / cab.num("current_density_A_m2")

        def run_len(xh):
            return anp.sqrt((xh - d.x_bat) ** 2 + 1e-4) + d.y_b + d.over + abs(d.z_b) + cab.num("run_extra_m")
        d.L_runs = [run_len(d.x_f), run_len(d.x_r)]
        d.m_wire = sum(2 * 2.0 * d.n_per * L * CU_RHO * d.A_cu for L in d.L_runs) * cab.num("insulation_factor")
        d.R_w = [CU_RES * 2.0 * L / d.A_cu for L in d.L_runs]                 # out and back, one motor
        d.R_e = esc.num("re_ohm")
        d.m_esc = esc["mass_kg"] if esc.get("mass_kg") is not None else esc.num("g_per_A") / 1000.0 * esc.num("peak_factor") * d.I_pk
        d.m_batt = bat.mass_kg_of(d.S, d.cap)
        d.R_b = d.S * (bat.num("cell_resistance_mohm") / 1000.0) * 4.5 / d.cap

        # ---- mass list (name, mass, x, y, z, own inertia ixx, iyy, izz)
        d.m_fuse = air.fuselage_area() * fz.num("mass_kg_per_m2")
        d.m_lift_unit = d.m_motor + d.m_prop + d.m_esc + d.m_mount
        items: List[Tuple] = []

        def add(name, m, x, y, z, own=(0.0, 0.0, 0.0)):
            items.append((name, m, x, y, z) + tuple(own))

        for p in air.wing_pts:
            add("wing", p["mass"]["value"], *p["position"]["xyz"])
        for p in air.tail_pts:
            add("tail", p["mass"]["value"], *p["position"]["xyz"])
        tb = air.points["TAIL-BOOM"]
        add("tail_boom", air.m_tail_boom, tb["position"]["xyz"][0], 0.0, 0.0,
            (0.0, air.m_tail_boom * 0.92 ** 2 / 12.0, air.m_tail_boom * 0.92 ** 2 / 12.0))
        add("avionics", air.m_avionics, air.points["AVIONICS-REST"]["position"]["xyz"][0], 0.0, 0.0)
        av = c["avionics"]
        add("avionics_vtol", av.num("mass_kg"), d.x_cg, 0.0, 0.0)
        Lf = air.fuselage_length()
        add("fuselage", d.m_fuse, air.fuselage_mid_x(), 0.0, float(fz["z_centre_m"]), (0.0, d.m_fuse * Lf ** 2 / 12.0, d.m_fuse * Lf ** 2 / 12.0))
        cg_, cm_, gear = c["cargo"], c["camera"], c["landing_gear"]
        add("payload_cargo", cg_.num("mass_kg"), d.x_cg + cg_.num("x_from_cg"), 0.0, 0.0)
        add("payload_camera", cm_.num("mass_kg"), cm_.num("x_m"), 0.0, cm_.num("z_m"))
        add("landing_gear", gear.num("mass_kg"), gear.num("x_m"), 0.0, gear.num("z_m"))
        for k in ("motor", "esc", "prop", "rest"):
            m_k = {"motor": air.cruise["mass_kg"], "esc": air.m_cruise_esc, "prop": air.m_cruise_prop, "rest": air.m_cruise_rest}[k]
            add("cruise_" + k, m_k, air.x_hub + air.cruise_offsets[k], 0.0, -0.035)
        add("battery", d.m_batt, d.x_bat, 0.0, 0.0, (d.m_batt * 0.02 / 12.0, d.m_batt * 0.13 / 12.0, d.m_batt * 0.13 / 12.0))
        for side in (-1, 1):
            add("boom", d.m_boom_each, d.x_c, side * d.y_b, d.z_b, (0.0, d.m_boom_each * d.L_boom ** 2 / 12.0, d.m_boom_each * d.L_boom ** 2 / 12.0))
            add("boom_clamp", d.m_clamp, d.x_c, side * d.y_b, d.z_b)
            add("lift_front", d.n_per * d.m_lift_unit, d.x_f, side * d.y_b, d.z_rotor)
            add("lift_rear", d.n_per * d.m_lift_unit, d.x_r, side * d.y_b, d.z_rotor)
        add("cables", d.m_wire, d.x_c, 0.0, 0.5 * d.z_b)
        d.M = sum(i[1] for i in items)
        d.items = items
        ctx.limit("mtow_kg", d.M, hi=lim.num("mtow_kg"), group="mass")
        mx = sum(i[1] * i[2] for i in items)
        o.subject_to((mx - d.x_cg * d.M) / 0.1 == 0)                 # CG: polynomial form, scaled by 0.1 kg m
        ctx.cons["cg_x_m"], ctx.cgroup["cg_x_m"], ctx.cscale["cg_x_m"] = (mx / d.M, d.x_cg, d.x_cg), "cg", 1e-2
        d.Ixx = sum(i[5] + i[1] * (i[3] ** 2 + i[4] ** 2) for i in items)
        d.Iyy = sum(i[6] + i[1] * ((i[2] - d.x_cg) ** 2 + i[4] ** 2) for i in items)
        d.Izz = sum(i[7] + i[1] * ((i[2] - d.x_cg) ** 2 + i[3] ** 2) for i in items)

        # ---- hover thrust of one rotor at the front and the rear end (moment balance about the CG)
        d.W = d.M * G0
        d.share_f = (d.x_r - d.x_cg) / (d.x_r - d.x_f)
        d.k_int = ctl.num("k_int") if d.n_per == 2 else 1.0
        d.W_L = (d.M - cg_.num("mass_kg")) * G0
        d.states, d.rotors = {}, {}
        d.mat = mat
        self.d = d
        return d

    # -- one flight condition
    def add_to(self, ctx, cond: FlightCondition) -> Any:
        """Add one flight condition to the problem. Hover, climb and max: the two lift rotors (front and rear end).
        Cruise: the nose propeller. Needs `design` first. Returns the states (lift) or the cruise state (cruise)."""
        if self.d is None or ctx.opti is not self.d.opti:
            raise RuntimeError("call design(problem) before add_to(problem, condition)")
        if cond.mode in ("hover", "climb", "max"):
            return self._lift_condition(ctx, cond)
        return self._cruise_condition(ctx, cond)

    def end_thrust(self, weight_N):
        import aerosandbox.numpy as anp
        d = self.d
        return [weight_N * 0.5 * d.share_f / d.n_per / anp.cos(d.cant), weight_N * 0.5 * (1.0 - d.share_f) / d.n_per / anp.cos(d.cant)]

    def _lift_rotor(self, ctx, name: str, thrust, v_ax, end: int, T_est: float):
        """A lift rotor at one state: shaft speed, thrust and the motor and wire chain. T_est (N) is the thrust of the first guess
        (it scales the thrust equality and starts the shaft speed)."""
        d = self.d
        el_tip = self.c["rotor"].num("tip_mach_max")
        rm_ = self._rotor(ctx, "lift", name)
        r_out = rm_.add(ctx, name, thrust, v_ax, T_est, v_ax, s=d.s, R=d.R)
        w = r_out["omega"]
        I = r_out["Q"] * d.kv_rad + d.i0
        Vm = w / d.kv_rad + d.rm * I
        Pe = Vm * I + (d.R_e + d.R_w[end]) * I ** 2
        d.rotors[name] = {"omega": w, "Q": r_out["Q"], "P_shaft": r_out["P_shaft"], "T": r_out["T"], "I": I, "Vm": Vm, "Pe": Pe, "end": end}
        ctx.limit("tip_mach_" + name, w * d.R, hi=el_tip * A0, scale=100.0, group="tw")
        return d.rotors[name]

    def _lift_condition(self, ctx, cond: FlightCondition):
        d = self.d
        lim = self.c["limits"]
        tw = lim.num("thrust_to_weight")
        weight = {"hover": d.W if cond.payload else d.W_L, "climb": d.W, "max": d.W * cond.thrust_factor}[cond.mode]
        ths = self.end_thrust(weight)
        T_est = ctx.start("M", 14.8) * G0 / self.N
        T_est *= tw if cond.mode == "max" else (0.96 if not cond.payload else 1.0)
        v_ax = cond.speed_m_s if cond.mode == "climb" else 0.0
        states = [self._lift_rotor(ctx, f"{cond.name}_{k}", ths[i], v_ax, i, T_est) for i, k in enumerate(("f", "r"))]
        d.states[cond.name] = states
        return states

    def _cruise_condition(self, ctx, cond: FlightCondition):
        import aerosandbox.numpy as anp
        d, air, c = self.d, self.d.air, self.c
        ca, el_esc, bat = c["cruise_aero"], c["esc"], c["battery"]
        cp, pol, S_w = air.cruise, air.polar, air.s_ref
        name = "lap" if cond.name == "F_LAP" else "map"
        V = d.V_lap if name == "lap" else d.V_map
        n2 = 1.0 if name == "lap" else d.n2_map
        V0 = ctx.start("V_lap", 17.0) if name == "lap" else ctx.start("V_map", 18.0)
        q = 0.5 * RHO0 * V ** 2
        CL2 = (d.M * G0) ** 2 * n2 / (q * S_w) ** 2
        D_ = q * (S_w * (pol["cd0"] + pol["k"] * CL2) + d.cda_extra)
        r_out = self._rotor(ctx, "cruise", "cr_" + name).add(ctx, "cr_" + name, D_, V, 18.0, V0)
        w = r_out["omega"]
        Kv = cp["kv_rad_s_V"]
        I = cp["i0_A"] + r_out["Q"] * Kv
        Vm = w / (cp["kappa"] * Kv) + cp["r_tot_ohm"] * I
        Pe = Vm * I + c["avionics"].num("power_W")
        Ib = Pe / (d.S * d.V_cell)
        Pb = Pe + d.R_b * Ib ** 2
        duty = Vm / (d.S * d.V_cell - d.R_b * Ib)
        ctx.limit("cruise_duty_" + name, duty, hi=el_esc.num("duty_max"), group="elec")
        ctx.limit("cruise_current_" + name, I, hi=cp["imax_A"], scale=10.0, group="elec")
        ctx.limit("cruise_tip_mach_" + name, w * 0.5 * cp["diameter_m"], hi=0.85 * A0, scale=100.0, group="tw")
        return {"V": V, "drag_N": D_, "omega": w, "P": Pb, "eta_total": r_out["T"] * V / Pb, "CL": anp.sqrt(CL2),
                "I": I, "thrust": r_out["T"], "Q": r_out["Q"]}

    # -- all of the mission in one problem
    def build(self, ctx) -> Dict[str, Any]:
        """The whole problem: design, every condition of the mission, the energy, the structure, the clearances, the control
        and the bay. Returns the output expressions (names, rotors, energy and so on) for the report."""
        import aerosandbox.numpy as anp
        c, o = self.c, ctx.opti
        self.d = None
        d = self.design(ctx)
        air, lim, mis, el_esc, bat = d.air, c["limits"], c["mission"], c["esc"], c["battery"]
        boom, rot, ca, ctl, fz = c["boom"], c["rotor"], c["cruise_aero"], c["control"], c["fuselage"]
        S, N, n_per = d.S, d.N, d.n_per
        conds = {x.name: x for x in mis.conditions(lim.num("thrust_to_weight"))}

        # ---- the four lift states (shaft speed variables w_<state>), in the order H_TO, C_TO, H_L, MAX
        for nm in ("H_TO", "C_TO", "H_L", "MAX"):
            self.add_to(ctx, conds[nm])
        states = d.states

        def battery_power(rts, Vc):
            Pe = 2.0 * n_per * sum(rt["Pe"] for rt in rts) * d.k_int + c["avionics"].num("power_W")
            Ib = Pe / (S * Vc)
            return Pe + d.R_b * Ib ** 2, Ib

        P = {k: battery_power(states[k], d.V_cell)[0] for k in ("H_TO", "C_TO", "H_L")}
        P_max, I_b_max = battery_power(states["MAX"], d.V_end)

        # ---- MAX: motor torque, current, duty, C-rate
        V_bus = S * d.V_end - d.R_b * I_b_max
        for rt, nm in zip(states["MAX"], ("front", "rear")):
            ctx.limit("motor_torque_" + nm, rt["Q"], hi=d.q_cap, scale=2.0, group="elec")
            ctx.limit("motor_current_" + nm, rt["I"], hi=d.I_pk, scale=50.0, group="elec")
            duty = (rt["omega"] / d.kv_rad + (d.rm + d.R_e + d.R_w[rt["end"]]) * rt["I"]) / V_bus
            ctx.limit("duty_" + nm, duty, hi=el_esc.num("duty_max"), group="elec")
        ctx.limit("c_rate_max", I_b_max / d.cap, hi=bat.num("c_rate_max"), scale=10.0, group="elec")
        if esc_current := c["esc"].get("current_A"):                 # the ESC of the parts list carries the peak current
            ctx.limit("esc_current_A", el_esc.num("peak_factor") * d.I_pk, hi=float(esc_current), scale=10.0, group="elec")
        Qh = 0.5 * (states["H_TO"][0]["Q"] + states["H_TO"][1]["Q"])
        Th = d.W / N / anp.cos(d.cant)

        # ---- cruise (lift props stopped; the nose prop works)
        d.cda = {"boom": 2.0 * ca.num("boom_form_factor") * ca.num("boom_cf") * (2.0 * math.pi * d.r_o) * d.L_boom,
                 "nacelles": N * ca.num("nacelle_cda_m2"),
                 "stopped_props": N * ca.num("stopped_prop_cda_per_r2") * d.R ** 2}
        d.cda_extra = d.cda["boom"] + d.cda["nacelles"] + d.cda["stopped_props"]
        cl_max = air.polar["cl_max"] * ca.num("cl_max_usable_factor")
        d.V_lap = ctx.state("V_lap", 17.0, 12.0, 30.0, scale=15.0)
        d.Vs = anp.sqrt(2.0 * d.W / (RHO0 * air.s_ref * cl_max))
        ctx.limit("stall_margin_lap", d.V_lap, lo=ca.num("stall_margin") * d.Vs, scale=10.0, group="energy")
        lap = self.add_to(ctx, conds["F_LAP"])
        d.V_map = ctx.state("V_map", 18.0, 12.0, 40.0, scale=15.0)
        ctx.limit("stall_margin_map", d.V_map, lo=ca.num("stall_margin") * d.Vs, scale=10.0, group="energy")
        sv = mis.survey(ca.num("map_turn_radius_m"))
        d.n2_map = (1.0 - sv["turn_frac"]) + sv["turn_frac"] * sv["n_turn"] ** 2
        mapc = self.add_to(ctx, conds["F_MAP"])

        # ---- energy (J)
        segs = mis.segments(d.V_lap, d.V_map, ca.num("map_turn_radius_m"), d.M * G0, lap["eta_total"])
        power = dict(P, F_LAP=lap["P"], F_MAP=mapc["P"])
        seg_J, t = mis.energy(power, segs)
        E_total = sum(seg_J.values()) / 3600.0
        E_nom = S * d.V_cell * d.cap
        ctx.limit("energy_Wh", E_total, hi=bat.num("usable_fraction") * E_nom, scale=100.0, group="energy")

        # ---- structure: each boom end is a cantilever of length a from the clamp
        m_tip = n_per * d.m_lift_unit
        m_arm = d.m_boom_each * d.a / d.L_boom
        SF, n_g = lim.num("safety_factor"), lim.num("load_factor")
        mat = d.mat
        strength = min(mat.num("tensile_strength_Pa"), mat.num("compressive_strength_Pa"))
        E_ax, E_c = mat.num("E_Pa"), mat.num("E_c_Pa")
        sigma_cr = Tube.buckling_stress(E_c, d.r_o, d.t, mat.num("buckling_knockdown"))
        mo_off = boom.num("mount_offset_m")
        struct = []
        for rt, nm in zip(states["MAX"], ("front", "rear")):
            for lc, F in (("T", n_per * rt["T"]), ("g", n_g * G0 * m_tip)):     # T_max, then the 3 g inertia load of the tip mass
                Qe = n_per * rt["Q"]
                Mb = SF * anp.sqrt((F * d.a + n_g * G0 * m_arm * d.a / 2.0) ** 2 + Qe ** 2)
                sigma = Mb / d.I_sec * d.r_o
                tau = SF * F * mo_off * d.r_o / (2.0 * d.I_sec)
                vm = anp.sqrt(sigma ** 2 + 3.0 * tau ** 2)
                slope = F * d.a ** 2 / (2.0 * E_ax * d.I_sec)
                ctx.limit(f"boom_stress_Pa_{nm}_{lc}", vm, hi=strength, scale=1e8, group="structure")
                ctx.limit(f"boom_buckling_Pa_{nm}_{lc}", sigma, hi=sigma_cr, scale=1e8, group="structure")
                ctx.limit(f"boom_tip_slope_deg_{nm}_{lc}", slope * 180.0 / math.pi, hi=boom.num("tip_slope_max_deg"), group="structure")
                struct.append({"F_N": F, "sigma_Pa": sigma, "von_mises_Pa": vm, "slope_deg": slope * 180.0 / math.pi})
        ctx.limit("boom_r_over_t", d.r_o / d.t, hi=boom.num("r_over_t_max"), scale=10.0, group="structure")
        f1 = Tube.f1_hz(E_ax, d.I_sec, d.a, m_tip, m_arm)
        freq_hover = [states["H_TO"][i]["omega"] / (2.0 * math.pi) for i in (0, 1)]       # 1P at the front and the rear end
        # Resonance check: f1 stays out of the band 1P hover +/- margin (take-off and landing mass). "below": f1 under the band,
        # so every speed from hover to full throttle is above the boom mode. "above": f1 over the band.
        mg, side = boom.num("resonance_margin"), boom["resonance_side"]
        if side not in ("below", "above"):
            raise ValueError("boom.resonance_side must be below or above")
        for state, tag in (("H_TO", "hover"), ("H_L", "landing")):
            for i, nm in enumerate(("front", "rear")):
                fh = states[state][i]["omega"] / (2.0 * math.pi)
                kw = {"hi": (1.0 - mg) * fh} if side == "below" else {"lo": (1.0 + mg) * fh}
                ctx.limit(f"boom_f1_over_1P_{tag}_{nm}", f1, scale=10.0, group="stiffness", **kw)

        # ---- clearances (plan view; the discs lie above the wing plane)
        gap = rot.num("tip_clearance_m")
        ctx.limit("clear_fuselage_m", d.y_b - d.R - 0.5 * fz.num("width_m"), lo=gap, scale=0.01, group="clear")
        ctx.limit("clear_front_to_wing_LE_m", air.le_x(d.y_b) - (d.x_f + d.R), lo=gap, scale=0.01, group="clear")
        ctx.limit("clear_rear_to_wing_TE_m", (d.x_r - d.R) - air.te_x(d.y_b), lo=gap, scale=0.01, group="clear")
        ctx.limit("clear_rear_to_htail_m", air.htail_le_x - (d.x_r + d.R), lo=gap, scale=0.01, group="clear")
        ctx.limit("clear_prop_to_prop_m", 2.0 * d.a - 2.0 * d.R, lo=gap, scale=0.01, group="clear")

        # ---- control authority (hover thrust between idle and T_max; handling-quality bandwidth, Froude scaled)
        L_hub = anp.sqrt((2.0 * d.y_b) ** 2 + (2.0 * d.a) ** 2)
        w_bw = ctl.num("bandwidth_rad_s") * anp.sqrt(ctl.num("bandwidth_length_m") / L_hub)
        alpha_req = ctl.num("margin") * w_bw ** 2 * ctl.num("amplitude_rad")
        d_ = 1.0 - ctl.num("idle_thrust_fraction")
        dT = d_ * Th
        M_roll, M_pitch = N * d.y_b * dT, N * d.a * dT
        # Yaw: the drag torque difference of the cw and ccw rotors, plus the tilt force. Each rotor tilts about its radial
        # axis (CG to hub), with its sign set by its spin, so the tilts give zero yaw moment in hover and add to the drag
        # torque when the controller changes the thrust (the tilt force is tangential: moment T sin(cant) rho).
        rho_f, rho_r = anp.sqrt(d.y_b ** 2 + (d.x_f - d.x_cg) ** 2), anp.sqrt(d.y_b ** 2 + (d.x_r - d.x_cg) ** 2)
        M_yaw = (N / 2.0) * Qh * ((1.0 + d_) ** 1.5 - (1.0 - d_) ** 1.5) + N * dT * anp.sin(d.cant) * 0.5 * (rho_f + rho_r)
        ctx.limit("control_roll_rad_s2", M_roll / d.Ixx, lo=alpha_req, scale=10.0, group="control")
        ctx.limit("control_pitch_rad_s2", M_pitch / d.Iyy, lo=alpha_req, scale=10.0, group="control")
        ctx.limit("control_yaw_rad_s2", M_yaw / d.Izz, lo=ctl.num("yaw_rad_s2"), scale=10.0, group="control")
        ctl_out = {"alpha_req": alpha_req, "w_bw": w_bw, "L_hub": L_hub, "roll": M_roll / d.Ixx, "pitch": M_pitch / d.Iyy, "yaw": M_yaw / d.Izz}

        # ---- the battery bay
        bay = fz["bay_x_m"]
        V_bat_L = E_nom / fz.num("battery_Wh_per_L")
        ctx.limit("bay_volume_L", V_bat_L, hi=(bay[1] - bay[0]) * fz.num("width_m") * fz.num("height_m") * 0.4 * 1000.0, scale=1.0, group="mass")

        names = dict(M=d.M, m_motor=d.m_motor, m_prop=d.m_prop, m_esc=d.m_esc, m_wire=d.m_wire, m_batt=d.m_batt, m_boom=d.m_boom,
                     rm=d.rm, i0=d.i0, I_pk=d.I_pk, R_b=d.R_b, Th=Th, Qh=Qh, W=d.W, share_f=d.share_f, x_f=d.x_f, x_r=d.x_r,
                     x_c=d.x_c, L_boom=d.L_boom, V_lap=d.V_lap, V_map=d.V_map, Vs=d.Vs, m_fuse=d.m_fuse, A_cu=d.A_cu, R=d.R,
                     D=d.D, kv_rad=d.kv_rad, r_i=d.r_i, sigma_cr=sigma_cr, L_run_f=d.L_runs[0], L_run_r=d.L_runs[1],
                     R_w_f=d.R_w[0], R_w_r=d.R_w[1])
        return {"R": d.R, "names": names, "E_total": E_total, "E_nom": E_nom, "seg_J": seg_J, "t": t,
                "inertia": (d.Ixx, d.Iyy, d.Izz), "ctl": ctl_out, "lap": lap, "map": mapc, "cda": d.cda,
                "P": P, "P_max": P_max, "I_b_max": I_b_max, "V_bus": V_bus, "f1": f1, "freq_hover": freq_hover,
                "struct": struct, "rotors": d.rotors, "items": d.items, "objective": E_total}

    # -- the numbers of the model that are not expressions
    def static_report(self, R_m: float) -> Dict[str, Any]:
        """c_ref, boom z, rotor z, the coaxial spacing, the boom material and the propeller pitch."""
        c, air = self.c, self.af
        rot, mat = c["rotor"], c["boom_material"]
        out = {"c_ref_m": float(air.c_ref), "boom_z_m": float(air.tail_boom_z),
               "rotor_z_m": float(air.tail_boom_z + c["boom"].num("mount_offset_m")),
               "spacing_m": (rot.num("coaxial_spacing_over_D") * 2.0 * R_m) if self.n_per == 2 else None,
               "boom_material": {"E_Pa": mat.num("E_Pa"), "E_c_Pa": mat.num("E_c_Pa"), "rho_kg_m3": mat.num("density_kg_m3")}}
        if rot.get("pitch_m") is not None:
            out["pitch_m"], out["pitch_note"] = float(rot["pitch_m"]), "input of the parts list"
        else:
            out["pitch_m"] = rot.num("blade_pitch_m") / rot.num("blade_diameter_m") * 2.0 * R_m
            out["pitch_note"] = "no pitch given: P/D of the base blade (%s), scaled" % rot["design"]
        return out

    # -- the geometry for the plotter
    def geometry(self, v: Dict[str, float]) -> Dict[str, Any]:
        """The numbers the 3D view needs, from design values `v` (keys of DESIGN_VARS) and the airframe."""
        air = self.derive()
        boom, rot = self.c["boom"], self.c["rotor"]
        x_c = 0.5 * (air.te_x(0.0) + air.le_x(0.0)) + v["dx"]
        R = rot.num("reference_radius_m") * v["scale"]
        return {"x_c": x_c, "a": v["a"], "y_b": v["y_b"], "R": R, "r_o": v["r_boom"], "t": v["t_boom"], "cant": v["cant"],
                "z_b": air.tail_boom_z, "z_rotor": air.tail_boom_z + boom.num("mount_offset_m"),
                "overhang": boom.num("overhang_m"), "x_batt": v["x_batt"], "x_cg": air.x_cg,
                "n_per": self.n_per, "x_hub": air.x_hub}

    def airplane(self, v: Dict[str, float], booms: bool = True):
        """An asb.Airplane of the design `v`: the wing and tail of the base, the new fuselage, the tail boom and (booms=True) two
        lift booms as tubes. The lift rotors are not in it (AeroSandbox draws a disc with a vertical normal wrong): see
        `rotor_discs`."""
        import aerosandbox as asb
        air, g = self.derive(), self.geometry(v)
        spec = {"name": self.name, "reference": {"s_m2": air.s_ref, "b_m": air.b_ref, "c_m": air.c_ref, "xyz_ref": [air.x_cg, 0.0, 0.0]},
                "surfaces": [air.surfaces[n] for n in ("wing_main", "htail", "fin")],
                "fuselages": [{"name": "fuselage", "frames": air.new_fuselage_frames()},
                              {"name": "tail_boom", "frames": air.tail_boom_frames}],
                "propulsion": {"hub": [air.x_hub, 0.0, -0.035], "thrust_axis": [-1.0, 0.0, 0.0],
                               "diameter_m": air.cruise["diameter_m"]}}
        plane = build_airplane(spec)
        L = 2.0 * g["a"] + 2.0 * g["overhang"]
        for side, nm in (((-1, "boom_left"), (1, "boom_right")) if booms else ()):
            xs = np.linspace(g["x_c"] - 0.5 * L, g["x_c"] + 0.5 * L, 4)
            plane.fuselages.append(asb.Fuselage(name=nm, xsecs=[asb.FuselageXSec(xyz_c=[float(x), side * g["y_b"], g["z_b"]],
                                                                                   radius=g["r_o"]) for x in xs]))
        return plane

    def rotor_discs(self, v: Dict[str, float], n: int = 48) -> List[Dict[str, Any]]:
        """The lift rotors of the design `v` as discs: name, hub, thrust axis and the n points of the rim (an n x 3 array). Each
        rotor tilts about its radial axis (CG to hub) by the cant; the sign follows the spin, so the tilts cancel in hover.
        H8: the lower rotor of a pair sits one spacing (0.25 D) below the upper."""
        g = self.geometry(v)
        out = []
        for side, nm in ((-1, "left"), (1, "right")):
            for end, dxr in (("f", -g["a"]), ("r", g["a"])):
                x = g["x_c"] + dxr
                ry = side * g["y_b"]
                rho = math.hypot(x - g["x_cg"], g["y_b"])
                sgn = 1.0 if (side * (1 if end == "f" else -1)) > 0 else -1.0
                axis = np.array([-sgn * math.sin(g["cant"]) * ry / rho, sgn * math.sin(g["cant"]) * (x - g["x_cg"]) / rho, math.cos(g["cant"])])
                e1 = np.cross(axis, [1.0, 0.0, 0.0])
                e1 /= np.linalg.norm(e1)
                e2 = np.cross(axis, e1)
                th = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
                for k in range(g["n_per"]):
                    c = np.array([x, ry, g["z_rotor"] - k * 0.25 * 2.0 * g["R"]])
                    rim = c + g["R"] * (np.outer(np.cos(th), e1) + np.outer(np.sin(th), e2))
                    out.append({"name": f"lift_{nm}_{end}{k}", "centre": c, "axis": axis, "radius": g["R"], "rim": rim})
        return out


# ======================================================================================================= fixed wing
class FixedWingModel(AircraftModel):
    """
    A fixed-wing aircraft of the ADH tree, with one propeller. Four jobs, one flight condition each:
      geometry      three-view and 3D view of the AeroSandbox airplane, area, span and MAC
      polar         AeroBuildup polar over alpha at the cruise speed, against a reference polar (flow5)
      cruise_trim   level flight at the cruise speed: alpha, elevator, shaft speed and duty from one Opti problem
      static_check  full command at zero speed: the BEMT and the chain against the Propalyser table
    The model takes the spec of the spoke (spec_from_doc in spoke.py): surfaces, fuselages, mass, propulsion, flight.
    """
    KIND = "fixed_wing"

    def __init__(self, name: str, spec: Dict[str, Any]):
        super().__init__(name, {})
        self.spec = spec

    def airplane(self):
        return build_airplane(self.spec)

    def with_ref(self, xyz_ref):
        import copy
        plane = copy.copy(self.airplane())
        plane.xyz_ref = list(xyz_ref)
        return plane

    def aero(self, plane, speed, alpha_deg, altitude, deflections=None):
        import aerosandbox as asb
        pl = plane.with_control_deflections(deflections) if deflections else plane
        op = asb.OperatingPoint(atmosphere=asb.Atmosphere(altitude=altitude), velocity=speed, alpha=alpha_deg)
        return op, asb.AeroBuildup(airplane=pl, op_point=op).run()

    def _motor_chain(self):
        m, b = self.spec["propulsion"]["motor"], self.spec["propulsion"]["battery"]
        chain = dict(kv_rad_s_V=m["kv_rad_s_V"], i0_A=m["i0_A"], kappa=m["kappa"], r_tot_ohm=m["r_tot_ohm"], q0_Nm=m.get("q0_Nm", 0.0))
        return chain, float(b["v_nominal_V"])

    def _prop_model(self):
        if not _installed("proptimiser"):
            raise RuntimeError("Proptimiser is not installed in the AeroSandbox Python: run "
                               "`python -m aeroplan setup AeroSandbox --proptimiser <checkout>`")
        os.environ["PROPTIMISER_HOME"] = self.spec["propulsion"]["proptimiser_home"]
        from proptimiser.casadi_prop import PropellerModel
        from proptimiser.init import Propeller
        prop = Propeller.load(self.spec["propulsion"]["design"])
        return PropellerModel.from_propeller(prop, n_psi=1), prop

    def geometry(self, out_dir: Path, main_wing: str) -> Dict[str, Any]:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        plane = self.airplane()
        main = next(w for w in plane.wings if w.name == main_wing)
        res = {"s_m2": float(main.area()), "b_m": float(main.span()), "mac_m": float(main.mean_aerodynamic_chord()),
               "aspect_ratio": float(main.aspect_ratio())}
        files = []
        plane.draw_three_view(show=False)
        png = out / "three_view.png"
        plt.gcf().savefig(png, dpi=150)
        plt.close("all")
        files.append(str(png))
        try:
            fig = plane.draw(backend="plotly", show=False)
            html = out / "airplane_3d.html"
            fig.write_html(str(html), include_plotlyjs="cdn")
            files.append(str(html))
        except Exception as e:                     # the 3D view is a convenience
            res["html_error"] = str(e)
        return {"geometry": res, "files": files}

    def polar(self, out_dir: Path, alphas_deg: List[float], reference: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        spec, out = self.spec, Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        plane = self.with_ref(spec["mass"]["cg"])
        fl = spec["flight"]
        rows = []
        for a in alphas_deg:
            op, r = self.aero(plane, fl["speed_m_s"], a, fl["altitude_m"])
            rows.append({"alpha_deg": float(a), "CL": _f(r["CL"]), "CD": _f(r["CD"]), "Cm": _f(r["Cm"])})
        csv = out / "polar.csv"
        csv.write_text("alpha_deg,CL,CD,Cm\n" + "".join(f"{r['alpha_deg']},{r['CL']},{r['CD']},{r['Cm']}\n" for r in rows), encoding="utf-8")
        fig, ax = plt.subplots(1, 3, figsize=(13, 4))
        al = [r["alpha_deg"] for r in rows]
        for k, key in enumerate(("CL", "CD", "Cm")):
            ax[k].plot(al, [r[key] for r in rows], "o-", label="AeroSandbox AeroBuildup")
            if reference:
                ax[k].plot(reference["alpha_deg"], reference[key], "s--", label="flow5 (DAVE-ML in the ADH)")
            ax[k].set_xlabel("alpha [deg]")
            ax[k].set_ylabel(key)
            ax[k].grid(True)
        ax[0].legend()
        fig.tight_layout()
        png = out / "polar.png"
        fig.savefig(png, dpi=150)
        plt.close(fig)
        return {"rows": rows, "files": [str(csv), str(png)]}

    def cruise_trim(self) -> Dict[str, Any]:
        """Level flight at the cruise speed: alpha, elevator, shaft speed and duty from one Opti problem."""
        import aerosandbox as asb
        import aerosandbox.numpy as np_
        spec = self.spec
        plane = self.with_ref(spec["mass"]["cg"])
        fl = spec["flight"]
        V, W = fl["speed_m_s"], fl["weight_N"]
        atm = asb.Atmosphere(altitude=fl["altitude_m"])
        chain, v_bus = self._motor_chain()
        model, prop = self._prop_model()
        hub_z, cg_z = spec["propulsion"]["hub"][2], spec["mass"]["cg"][2]
        omega_max = 343.0 / (0.5 * spec["propulsion"]["diameter_m"])
        opti = asb.Opti()
        alpha = opti.variable(init_guess=3.0, lower_bound=-10.0, upper_bound=15.0)
        de = opti.variable(init_guess=0.0, lower_bound=-20.0, upper_bound=20.0)
        omega = opti.variable(init_guess=560.0, lower_bound=50.0, upper_bound=omega_max)
        duty = opti.variable(init_guess=0.5, lower_bound=0.01, upper_bound=1.0)
        op = asb.OperatingPoint(atmosphere=atm, velocity=V, alpha=alpha)
        r = asb.AeroBuildup(airplane=plane.with_control_deflections({"elevator": de}), op_point=op).run()
        thrust_scale = max(W / 12.0, 1.0)
        out = model.add_to(opti, omega, V * np_.cosd(alpha), 0.0, thrust_scale, rho_kg_m3=float(atm.density()),
                           mu_Pa_s=float(atm.dynamic_viscosity()), a_m_s=float(atm.speed_of_sound()))
        ch = electric_chain(out.torque_Nm, omega, duty, chain, v_bus)
        drag, lift = -r["F_w"][0], -r["F_w"][2]
        opti.subject_to([out.thrust_N * np_.cosd(alpha) - drag == 0,
                         lift + out.thrust_N * np_.sind(alpha) - W == 0,
                         r["M_b"][1] + out.thrust_N * (cg_z - hub_z) == 0,
                         ch["residual_V"] == 0])
        model.warm_start(opti, out, 560.0, V, 0.0, thrust_scale, float(atm.density()), float(atm.dynamic_viscosity()),
                         float(atm.speed_of_sound()))
        sol = opti.solve(verbose=False, max_iter=300)
        v = lambda x: float(sol(x))
        T, Q, w, d = v(out.thrust_N), v(out.torque_Nm), v(omega), v(duty)
        c = {k: v(x) for k, x in ch.items()}
        batt = spec["propulsion"]["battery"]
        energy_J = batt.get("capacity_As", 0.0) * v_bus
        result = {"speed_m_s": V, "weight_N": W, "alpha_deg": v(alpha), "elevator_deg": v(de), "omega_rad_s": w,
                  "rpm": w * 60 / (2 * math.pi), "duty": d, "thrust_N": T, "torque_Nm": Q, "p_shaft_W": Q * w,
                  "lift_N": v(lift), "drag_N": v(drag), "L_over_D": v(lift) / v(drag), "CL": v(r["CL"]), "CD": v(r["CD"]),
                  **c, "chain_efficiency": Q * w / c["p_bat_W"], "battery_energy_J": energy_J,
                  "endurance_min": (energy_J / c["p_bat_W"] / 60.0) if energy_J else None,
                  "motor_current_limit_A": spec["propulsion"]["motor"].get("imax_A")}
        return {"cruise_trim": result}

    def neutral_point(self, spanwise: int = 16, chordwise: int = 12, velocity: float = 17.0, alphas=(0.0, 4.0)) -> Dict[str, Any]:
        """The neutral point by the vortex lattice of the surfaces (wing, htail, fin, no body) plus the body term (fuselage and tail
        boom) of the AeroBuildup body model, at alpha 0 and 4 deg: x_np = x_ref - c_ref dCm/dCL. The VLM has no body, and the body
        moves the NP forward. The SpecSheet spoke reads the file that the AeroSandbox spoke writes from this result."""
        import aerosandbox as asb
        spec = self.spec
        ref = dict(spec["reference"], xyz_ref=[float(spec["reference"]["xyz_ref"][0]), 0.0, 0.0])      # the pitch reference is x of the MRP
        plane = build_airplane(dict(spec, fuselages=[], reference=ref))
        bodies = build_airplane(dict(spec, surfaces=[], reference=ref))
        out = []
        for a in alphas:
            op = asb.OperatingPoint(atmosphere=asb.Atmosphere(altitude=0.0), velocity=velocity, alpha=a)
            r = asb.VortexLatticeMethod(plane, op, spanwise_resolution=spanwise, chordwise_resolution=chordwise,
                                        align_trailing_vortices_with_wind=False).run()
            bd = asb.AeroBuildup(bodies, op).run()
            out.append((_f(r["CL"]) + _f(bd["CL"]), _f(r["Cm"]) + _f(bd["Cm"])))
        d_cl, d_cm = out[1][0] - out[0][0], out[1][1] - out[0][1]
        c_ref = spec["reference"]["c_m"]
        x_ref = float(plane.xyz_ref[0])
        return {"neutral_point": {
            "x_np_m": float(x_ref - c_ref * d_cm / d_cl), "mac_m": float(c_ref), "x_ref_m": x_ref,
            "method": "AeroSandbox VortexLatticeMethod (wing + htail + fin) plus AeroBuildup body term (fuselage, tail boom), alpha 0 and 4 deg, "
                      "x_np = x_ref - c_ref dCm/dCL",
            "panels": {"spanwise": spanwise, "chordwise": chordwise}, "velocity_m_s": velocity}}

    def static_check(self) -> Dict[str, Any]:
        """Full command at zero speed: the BEMT and the chain against the Propalyser Ct/Cp table and power at full command."""
        import aerosandbox as asb
        spec = self.spec
        chain, v_bus = self._motor_chain()
        model, prop = self._prop_model()
        atm = asb.Atmosphere(altitude=spec["flight"]["altitude_m"])
        rho, mu, a = float(atm.density()), float(atm.dynamic_viscosity()), float(atm.speed_of_sound())
        D = spec["propulsion"]["diameter_m"]
        opti = asb.Opti()
        omega = opti.variable(init_guess=600.0, lower_bound=50.0, upper_bound=343.0 / (0.5 * D))
        out = model.add_to(opti, omega, 0.0, 0.0, 30.0, rho, mu, a)
        ch = electric_chain(out.torque_Nm, omega, 1.0, chain, v_bus)
        opti.subject_to(ch["residual_V"] == 0)
        model.warm_start(opti, out, 600.0, 0.0, 0.0, 30.0, rho, mu, a)
        sol = opti.solve(verbose=False, max_iter=200)
        w, T, Q = float(sol(omega)), float(sol(out.thrust_N)), float(sol(out.torque_Nm))
        n = w / (2 * math.pi)
        tab = spec["propulsion"]["tables"]
        ct0, cp0 = float(np.interp(0.0, tab["J"], tab["CT"])), float(np.interp(0.0, tab["J"], tab["CP"]))
        T_tab, P_tab = ct0 * rho * n ** 2 * D ** 4, cp0 * rho * n ** 3 * D ** 5          # the Propalyser table at the same shaft speed
        n_pmax = (spec["propulsion"]["p_max_W"] / (cp0 * rho * D ** 5)) ** (1 / 3)
        res = {"omega_rad_s": w, "rpm": w * 60 / (2 * math.pi), "thrust_N": T, "torque_Nm": Q, "p_shaft_W": Q * w,
               "i_motor_A": float(sol(ch["i_motor_A"])), "p_bat_W": float(sol(ch["p_bat_W"])),
               "ct0_bemt": T / (rho * n ** 2 * D ** 4), "cp0_bemt": Q * w / (rho * n ** 3 * D ** 5),
               "ct0_table": ct0, "cp0_table": cp0, "thrust_table_same_omega_N": T_tab, "p_shaft_table_same_omega_W": P_tab,
               "p_max_propalyser_W": spec["propulsion"]["p_max_W"], "rpm_propalyser_table_at_pmax": n_pmax * 60.0,
               "rho_kg_m3": rho}
        return {"static_check": res}


# ====================================================================================================== multirotor
# Electric Multirotor Sizing Tool, segment analysis: Bershadsky, Haviland, Johnson, "Electric Multirotor UAV
# Propulsion System Sizing for Performance Prediction and Design Optimization", AIAA 2016-0581, section III.A.
#
#   Vs  = d s Vc - Id (Rb + Rw + Re + Rm)          eq. (9)   mean voltage at the motor coils
#   RPM = Kv Vs / G                                 eq. (10)  no-load speed
#   Id  = Nm (Q w / (etaM Vs) + I0) / etaE          eq. (11)  drive current
#   It  = Id + Ip + Ia                              eq. (12)  total current
#
# What differs from the paper, on purpose:
#   - The rotor load (thrust and torque against the shaft speed) comes from the CT/CP table of the propulsion dataset
#     (contract B, manufacturer basis). The paper uses a BEMT with a NACA 0015 section and names it its largest error
#     (section III.A.9).
#   - The motor and ESC chain is the Propalyser chain (electric_chain): I_motor = I0 + (Q + Q0) Kv and
#     V_term = w / (kappa Kv) + R I_motor. It replaces the two forms Q w / (etaM Vs) and Kv Vs / G, which describe the
#     same first-order motor with an efficiency etaM. The throttle d is the duty of the ESC chopper.
#   - Rm and Re act on the current of one motor. Rb and Rw act on the bus current. The paper writes one Id for all
#     motors. For Nm = 1 the two forms are equal.
#   - Nm = N identical rotors with the same speed (a symmetric vehicle in steady flight: no trim moment is solved).
# The paper sets the thrust to the weight (hover) or, in forward flight, loops on the tilt angle until the lift of the
# body and the thrust carry the weight (section III.A.3). Here the body has drag and no lift: the tilt loop solves
#   T sin(th) = Dh,  T cos(th) = W + Fv     (Dh: aerodynamic force against the flight direction, Fv: downward part).
OR_MOTOR_MASS = (4.0499, -0.5329)   # paper eq. (1), outrunner: m_motor [g] = 10^p1 Kv^p2, Kv in rpm/V
BATT_MASS = (0.026373, 2.0499e-05)  # paper eq. (4): m_batt [g] = (p1 s + p2) C, C in mAh, 1P


def isa_density(altitude_m):
    """ISA air density (kg/m^3) in the troposphere (ISO 2533): T = 288.15 - 0.0065 h, p = 101325 (T/288.15)^5.25588."""
    t = 288.15 - 0.0065 * altitude_m
    return 101325.0 * (t / 288.15) ** 5.25588 / (287.05287 * t)


def motor_mass_kg(kv_rpm_per_V):
    return 10.0 ** OR_MOTOR_MASS[0] * kv_rpm_per_V ** OR_MOTOR_MASS[1] / 1000.0


class MultirotorModel(AircraftModel):
    """
    A multirotor. The model is the flat dict `m` of the EMST functions (rotor table, motor chain, battery, drag). Each method
    evaluates one flight condition: `hover`, `climb`, `forward`, `full_throttle`. `scan` and `sensitivity` run them over a range.
    The EMST functions use numpy only. `drag` is the body drag job (AeroBuildup of the box and the arm tubes).
    """
    KIND = "multirotor"

    def __init__(self, name: str, m: Dict[str, Any], spec: Optional[Dict[str, Any]] = None):
        super().__init__(name, {})
        self.m = m
        self.spec = spec

    @classmethod
    def from_spec(cls, name: str, spec: Dict[str, Any], rho: float) -> "MultirotorModel":
        """The EMST model from a multirotor spec (spoke) and the air density (kg/m^3)."""
        p, e, d = spec["propulsion"], spec["electrical"], spec["drag"]
        mo, b = p["motor"], p["battery"]
        m = {"rho": rho, "n_rotors": len(spec["rotors"]), "diameter_m": p["diameter_m"], "mass_kg": spec["mass"]["mass_kg"],
             "tab": {k: list(v) for k, v in p["tables"].items()},
             "motor": {**{k: mo[k] for k in ("kv_rad_s_V", "i0_A", "kappa", "r_tot_ohm")}, "q0_Nm": mo.get("q0_Nm", 0.0)},
             "v_nominal_V": b["v_nominal_V"], "capacity_As": b["capacity_As"], "electrical": dict(e), "drag": dict(d),
             "throttle_map": p.get("throttle_map"), "p_max_W": p.get("p_max_W")}
        return cls(name, m, spec)

    # -- rotor and electric chain
    @staticmethod
    def rotor_coeffs(tab, j):
        """CT and CP of the table at the advance ratio j (held at the end values outside the table)."""
        return float(np.interp(j, tab["J"], tab["CT"])), float(np.interp(j, tab["J"], tab["CP"]))

    def rotor_load(self, n_rev_s, v_ax, m=None):
        """Thrust (N), shaft torque (N m), shaft power (W) and J of one rotor at n (rev/s) and axial inflow v_ax (m/s)."""
        m = m or self.m
        if m.get("live") is not None:                  # a live propeller model: see live_rotor
            return m["live"](n_rev_s, v_ax)
        d, rho = m["diameter_m"], m["rho"]
        j = v_ax / (n_rev_s * d)
        ct, cp = self.rotor_coeffs(m["tab"], j)
        thrust = ct * rho * n_rev_s ** 2 * d ** 4
        power = cp * rho * n_rev_s ** 3 * d ** 5
        return {"thrust_N": thrust, "torque_Nm": power / (2.0 * math.pi * n_rev_s), "p_shaft_W": power, "J": j, "CT": ct, "CP": cp}

    def solve_speed(self, thrust_N, v_ax, m=None, n_max=500.0):
        """The rotor speed (rev/s) at which one rotor gives `thrust_N` at the axial inflow v_ax. Bisection on the first
        crossing of the thrust curve. Raises ValueError when the table cannot give that thrust below n_max.
        With a live model in m["live"] the secant method runs on the live thrust (each call is slow, so the loop is short)."""
        m = m or self.m
        if m.get("live") is not None:
            return self._solve_speed_live(thrust_N, v_ax, m)
        f = lambda n: self.rotor_load(n, v_ax, m)["thrust_N"] - thrust_N
        grid = np.geomspace(0.5, n_max, 600)
        lo = grid[0]
        for hi in grid[1:]:
            if f(hi) >= 0.0:
                if f(lo) > 0.0:
                    break
                for _ in range(100):
                    mid = 0.5 * (lo + hi)
                    lo, hi = (mid, hi) if f(mid) < 0.0 else (lo, mid)
                return 0.5 * (lo + hi)
            lo = hi
        raise ValueError(f"the CT table gives no thrust of {thrust_N:.3f} N below {n_max:g} rev/s at an inflow of {v_ax:.3f} m/s")

    def _solve_speed_live(self, thrust_N, v_ax, m, rtol=1e-7, max_iter=30):
        """The rotor speed (rev/s) at which the live model gives `thrust_N`. Secant method. The first guess is the table
        solution, or momentum-free scaling T = 0.05 rho n^2 D^4 when the table cannot give the thrust."""
        f = lambda n: m["live"](n, v_ax)["thrust_N"] - thrust_N
        try:
            x0 = self.solve_speed(thrust_N, v_ax, {**m, "live": None})
        except ValueError:
            x0 = math.sqrt(thrust_N / (0.05 * m["rho"] * m["diameter_m"] ** 4))
        f0 = f(x0)
        x1 = x0 * math.sqrt(thrust_N / (thrust_N + f0)) if thrust_N + f0 > 0.0 else 1.1 * x0
        for _ in range(max_iter):
            f1 = f(x1)
            if abs(f1) <= rtol * thrust_N:
                return x1
            if f1 == f0:
                break
            x0, f0, x1 = x1, f1, x1 - f1 * (x1 - x0) / (f1 - f0)
        raise ValueError(f"the live propeller model gives no thrust of {thrust_N:.3f} N at an inflow of {v_ax:.3f} m/s (secant method did not converge)")

    @staticmethod
    def live_rotor(prop, rho):
        """A function (n rev/s, axial inflow m/s) -> rotor_load dict from the Proptimiser BEMT of one Propeller `prop`.
        Each call solves the BEMT (about 0.8 s)."""
        from proptimiser.casadi_prop import static_and_axial

        def fn(n_rev_s, v_ax):
            r = static_and_axial(prop, n_rev_s * 60.0, v_ax, rho=rho)
            return {"thrust_N": r.thrust_N, "torque_Nm": r.torque_Nm, "p_shaft_W": r.shaft_power_W, "J": r.J, "CT": r.CT, "CP": r.CP}
        return fn

    def electric_state(self, n_rev_s, torque_Nm, m=None):
        """The electrical state for N rotors at the speed n and the torque Q: eq. (9) to (12) with the Propalyser chain.
        Returns the duty, the currents, the voltages and the powers. `saturated` is True when the duty is above 1."""
        m = m or self.m
        mo, e, N = m["motor"], m["electrical"], m["n_rotors"]
        omega = 2.0 * math.pi * n_rev_s
        i_m = mo["i0_A"] + (torque_Nm + mo.get("q0_Nm", 0.0)) * mo["kv_rad_s_V"]
        r_m = mo["r_tot_ohm"] + e["re_ohm"]
        v_term = omega / (mo["kappa"] * mo["kv_rad_s_V"]) + r_m * i_m
        i_aux = e["ip_A"] + e["ia_A"]
        v0 = m["v_nominal_V"] - e["rb_ohm"] * i_aux                    # the pack under the auxiliary load
        a = N * i_m / e["eta_e"] * (e["rb_ohm"] + e["rw_ohm"])         # bus voltage drop per unit duty: V_bus = v0 - a d
        # duty * V_bus = V_term  ->  a d^2 - v0 d + V_term = 0
        if a == 0.0:
            duty = v_term / v0
        else:
            disc = v0 * v0 - 4.0 * a * v_term
            if disc < 0.0:
                raise ValueError("the battery cannot deliver this load (the resistances use the whole voltage)")
            duty = (v0 - math.sqrt(disc)) / (2.0 * a)
        i_d = N * duty * i_m / e["eta_e"]
        i_t = i_d + i_aux
        v_bus = v0 - (e["rb_ohm"] + e["rw_ohm"]) * i_d
        return {"duty": duty, "saturated": bool(duty > 1.0), "i_motor_A": i_m, "i_drive_A": i_d, "i_total_A": i_t,
                "v_term_V": v_term, "v_bus_V": v_bus, "p_motor_in_W": N * v_term * i_m, "p_bus_W": v_bus * i_d,
                "p_battery_W": m["v_nominal_V"] * i_t, "p_shaft_W": N * torque_Nm * omega,
                "chain_efficiency": N * torque_Nm * omega / (m["v_nominal_V"] * i_t)}

    def throttle_command(self, p_shaft_each_W, m=None):
        """The ESC command at which the static throttle map of the propulsion dataset gives this shaft power per rotor, or
        None without a map. A static map: an approximation in flight."""
        m = m or self.m
        tm = m.get("throttle_map")
        if not tm or not m.get("p_max_W"):
            return None
        return float(np.interp(p_shaft_each_W / m["p_max_W"], tm["power_fraction"], tm["esc_command_norm"]))

    def _segment(self, name, speed, climb, theta, thrust_total, v_ax, m):
        N = m["n_rotors"]
        n = self.solve_speed(thrust_total / N, v_ax, m)
        r = self.rotor_load(n, v_ax, m)
        el = self.electric_state(n, r["torque_Nm"], m)
        endurance_min = m["electrical"]["discharge_fraction"] * m["capacity_As"] / el["i_total_A"] / 60.0
        return {"name": name, "speed_m_s": speed, "climb_rate_m_s": climb, "tilt_deg": math.degrees(theta),
                "thrust_total_N": thrust_total, "thrust_each_N": thrust_total / N, "axial_inflow_m_s": v_ax,
                "rev_s": n, "rpm": n * 60.0, "J": r["J"], "CT": r["CT"], "CP": r["CP"], "torque_Nm": r["torque_Nm"],
                "p_shaft_each_W": r["p_shaft_W"], "esc_command_equiv": self.throttle_command(r["p_shaft_W"], m), **el,
                "endurance_min": endurance_min, "range_km": speed * endurance_min * 60.0 / 1000.0}

    def body_force(self, u, v, w, n_sum, m=None):
        """The body drag of the aero dataset (src/aeroplan/multirotor_aero.py): forces on the body, body axes FRD."""
        m = m or self.m
        d = m["drag"]
        q = 0.5 * m["rho"] * d["S_ref_m2"]
        k = d["k_rotor_drag_kg"]
        return (-q * d["CDx"] * u * abs(u) - k * n_sum * u, -q * d["CDy"] * v * abs(v) - k * n_sum * v, -q * d["CDz"] * w * abs(w))

    # -- one flight condition each
    def hover(self, m=None):
        """Hover: T = W (paper section III.A.1)."""
        m = m or self.m
        return self._segment("hover", 0.0, 0.0, 0.0, m["mass_kg"] * G0, 0.0, m)

    def climb(self, rate, m=None):
        """Vertical climb at a steady rate: the axial inflow is the climb rate, the thrust carries the weight and the body drag."""
        m = m or self.m
        fz = self.body_force(0.0, 0.0, -rate, 0.0, m)[2]            # w < 0 in FRD: the body moves up, the force is down
        return self._segment("climb", 0.0, rate, 0.0, m["mass_kg"] * G0 + fz, rate, m)

    def forward(self, speed, m=None, tol=1e-12, max_iter=500):
        """Level forward flight at `speed`: the loop on the tilt angle th of the thrust axis from the vertical
        (paper section III.A.3). The body is pitched nose down by th. The rotors see the axial inflow V sin(th)."""
        m = m or self.m
        if speed == 0.0:
            return self.hover(m)
        W, N = m["mass_kg"] * G0, m["n_rotors"]
        th, n_sum = 0.0, N * self.solve_speed(W / N, 0.0, m)
        for _ in range(max_iter):
            u, w = speed * math.cos(th), -speed * math.sin(th)
            fx, _, fz = self.body_force(u, 0.0, w, n_sum, m)
            d_h = -(fx * math.cos(th) - fz * math.sin(th))               # aerodynamic force against the flight direction
            f_v = fx * math.sin(th) + fz * math.cos(th)                  # aerodynamic force downward
            th_new, thrust = math.atan2(d_h, W + f_v), math.hypot(d_h, W + f_v)
            n_new = N * self.solve_speed(thrust / N, speed * math.sin(th_new), m)
            done = abs(th_new - th) < tol and abs(n_new - n_sum) < 1e-9
            th, n_sum = th_new, n_new
            if done:
                break
        else:
            raise ValueError(f"the tilt loop did not converge at {speed} m/s")
        seg = self._segment("forward", speed, 0.0, th, thrust, speed * math.sin(th_new), m)
        seg["body_drag_N"] = d_h
        return seg

    def full_throttle(self, m=None):
        """Static thrust at full throttle (duty 1, V = 0) with the battery sag, and the thrust-to-weight ratio."""
        m = m or self.m
        mo, e, N = m["motor"], m["electrical"], m["n_rotors"]
        v0 = m["v_nominal_V"] - e["rb_ohm"] * (e["ip_A"] + e["ia_A"])

        def resid(n):
            r = self.rotor_load(n, 0.0, m)
            i_m = mo["i0_A"] + (r["torque_Nm"] + mo.get("q0_Nm", 0.0)) * mo["kv_rad_s_V"]
            v_bus = v0 - (e["rb_ohm"] + e["rw_ohm"]) * N * i_m / e["eta_e"]
            return v_bus - (2.0 * math.pi * n / (mo["kappa"] * mo["kv_rad_s_V"]) + (mo["r_tot_ohm"] + e["re_ohm"]) * i_m)

        lo, hi = 1.0, 500.0
        if resid(lo) <= 0.0:
            raise ValueError("the chain cannot turn the rotor at full throttle")
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if resid(mid) > 0.0 else (lo, mid)
        n = 0.5 * (lo + hi)
        r = self.rotor_load(n, 0.0, m)
        el = self.electric_state(n, r["torque_Nm"], m)
        return {"rev_s": n, "rpm": n * 60.0, "thrust_each_N": r["thrust_N"], "thrust_total_N": N * r["thrust_N"],
                "thrust_to_weight": N * r["thrust_N"] / (m["mass_kg"] * G0), "p_shaft_each_W": r["p_shaft_W"],
                "i_motor_A": el["i_motor_A"], "i_total_A": el["i_total_A"], "duty_check": el["duty"]}

    # -- ranges of conditions
    def segments(self, climb_rate, speeds):
        return [self.hover(), self.climb(climb_rate)] + [self.forward(v) for v in speeds]

    def scan(self, v_max, step):
        """Hover and forward flight from 0 to v_max (m/s). The best speeds for endurance and range (paper section III.A.4)."""
        rows = [self.forward(float(v)) for v in np.arange(0.0, v_max + 0.5 * step, step)]
        return {"rows": rows, "best_endurance": max(rows, key=lambda r: r["endurance_min"]),
                "best_range": max(rows, key=lambda r: r["range_km"])}

    def sensitivity(self, cells_s, step=0.01):
        """Central differences of the hover endurance (min) with the motor Kv, the rotor diameter, the mass and the battery
        capacity (paper section III.A.5): the analyser runs again with x(1 + h) and x(1 - h). The Kv change moves the
        motor mass by eq. (1) and the capacity change moves the battery mass by eq. (4); the diameter change moves no mass
        (the constant p3 of eq. (5) is not in the source text)."""
        import copy
        m = self.m
        base = self.hover()["endurance_min"]
        out = {"base_endurance_min": base, "step": step, "parameters": {}}

        def run(name, x0, change):
            ends = []
            for sgn in (+1.0, -1.0):
                mm = copy.deepcopy(m)
                change(mm, x0 * (1.0 + sgn * step), x0)
                ends.append(self.hover(mm)["endurance_min"])
            d_dx = (ends[0] - ends[1]) / (2.0 * step * x0)
            out["parameters"][name] = {"x0": x0, "d_endurance_min_per_unit": d_dx, "percent_per_percent": d_dx * x0 / base}

        def kv(mm, x, x0):
            mm["motor"]["kv_rad_s_V"] = x * 2.0 * math.pi / 60.0
            mm["mass_kg"] += mm["n_rotors"] * (motor_mass_kg(x) - motor_mass_kg(x0))

        def diameter(mm, x, x0):
            mm["diameter_m"] = x

        def mass(mm, x, x0):
            mm["mass_kg"] = x

        def capacity(mm, x, x0):                      # x in A s; 1 mAh = 3.6 A s
            mm["capacity_As"] = x
            mm["mass_kg"] += (x - x0) / 3.6 * (BATT_MASS[0] * cells_s + BATT_MASS[1]) / 1000.0

        run("kv_rpm_per_V", m["motor"]["kv_rad_s_V"] * 60.0 / (2.0 * math.pi), kv)
        run("diameter_m", m["diameter_m"], diameter)
        run("mass_kg", m["mass_kg"], mass)
        run("capacity_As", m["capacity_As"], capacity)
        return out

    def live(self, designs: List[str], home: str, climb_rate: float) -> Dict[str, Any]:
        """Hover and vertical climb with the live Proptimiser BEMT in place of the CT/CP table. One Propeller for each rotor
        (reused for both segments). The first design is the main case; the table result of the same segments comes back as the
        maker check."""
        if not _installed("proptimiser"):
            raise RuntimeError("Proptimiser is not installed in the AeroSandbox Python: run "
                               "`python -m aeroplan setup AeroSandbox --proptimiser <checkout>`")
        os.environ["PROPTIMISER_HOME"] = home
        from proptimiser.init import Propeller
        m = self.m
        W = m["mass_kg"] * G0
        table = {"hover": self.hover(), "climb": self.climb(climb_rate)}
        out = {"rho_kg_m3": m["rho"], "n_rotors": m["n_rotors"], "table": table, "designs": {}}
        for design in designs:
            props = [Propeller.load(design) for _ in range(m["n_rotors"])]
            fns = [self.live_rotor(p, m["rho"]) for p in props]
            fz = self.body_force(0.0, 0.0, -climb_rate, 0.0)[2]
            out["designs"][design] = {"hover": self._live_segment("hover", 0.0, W, fns), "climb": self._live_segment("climb", climb_rate, W + fz, fns)}
        return out

    def _live_segment(self, name, climb, thrust_total, fns):
        """One vertical segment (hover or climb) with one live model for each rotor. The rotor speed is solved with the first
        model. Every rotor is then evaluated at that speed and inflow. The electrical state uses the mean torque."""
        m = self.m
        N = m["n_rotors"]
        if len(fns) != N:
            raise ValueError(f"{len(fns)} live rotor models for {N} rotors")
        seg = self._segment(name, 0.0, climb, 0.0, thrust_total, climb, {**m, "live": fns[0]})
        loads = [fn(seg["rev_s"], climb) for fn in fns]
        mean_q = sum(r["torque_Nm"] for r in loads) / N
        el = self.electric_state(seg["rev_s"], mean_q)
        seg.update(el)
        seg["endurance_min"] = m["electrical"]["discharge_fraction"] * m["capacity_As"] / el["i_total_A"] / 60.0
        seg["rotors"] = [{"thrust_N": r["thrust_N"], "p_shaft_W": r["p_shaft_W"], "torque_Nm": r["torque_Nm"]} for r in loads]
        seg["thrust_each_N"] = sum(r["thrust_N"] for r in loads) / N
        seg["p_shaft_each_W"] = sum(r["p_shaft_W"] for r in loads) / N
        return seg

    # -- body drag: AeroBuildup of the box and the arm tubes, with the Hoerner hand check
    def drag_airplane(self):
        """The body box and the arm tubes as AeroSandbox fuselages (the airplane has no wing). The box is a superellipse
        (shape 10) that spans the box edges. An arm is a round tube with its cross sections along its path, listed in
        rising x (AeroSandbox fuselages run along x)."""
        import aerosandbox as asb
        spec = self.spec
        body = spec["body"]
        bx = body["box"]
        lx, ly, lz = bx["size"]
        cx, cy, cz = bx["centre"]
        n = int(spec["drag_job"].get("box_edge_sections", 5))
        fus = [asb.Fuselage(name="body", xsecs=[asb.FuselageXSec(xyz_c=[float(x), cy, cz], width=ly, height=lz, shape=10.0)
                                                for x in np.linspace(cx - lx / 2, cx + lx / 2, n)])]
        for i, arm in enumerate(body["arms"], 1):
            p0, p1 = sorted((np.asarray(arm["p0"], float), np.asarray(arm["p1"], float)), key=lambda p: p[0])
            if p1[0] - p0[0] <= 0.0:
                raise ValueError(f"arm {i} has no extent along x: AeroSandbox fuselages run along x")
            fus.append(asb.Fuselage(name=f"arm_{i}", xsecs=[asb.FuselageXSec(xyz_c=list(p0 + t * (p1 - p0)), radius=arm["radius_m"])
                                                           for t in np.linspace(0.0, 1.0, 5)]))
        props = [asb.Propulsor(name=f"rotor_{r['motor']}", xyz_c=r["hub"], xyz_normal=r["thrust_axis"], radius=0.5 * r["diameter_m"])
                 for r in spec["rotors"]]
        ref = spec["reference"]
        return asb.Airplane(name=spec["name"], xyz_ref=ref["xyz_ref"], fuselages=fus, propulsors=props, s_ref=ref["s_m2"],
                            b_ref=ref["b_m"], c_ref=ref["c_m"])

    @staticmethod
    def hoerner_cda(spec, h):
        """The hand check of the body drag: C_D A along each body axis from the crossflow drag of the bluff shapes
        (Hoerner, Fluid-Dynamic Drag, 1965, chapter 3). The box takes its flat-face coefficient on the face normal to the flow.
        A tube takes the cylinder crossflow coefficient on its projected area, with the independence principle: only the
        velocity component normal to the tube axis counts, so the force along the flow is C_d 2 r L (1 - a_i^2)^1.5 for a
        flow along axis i (a_i: the axis component of the tube direction)."""
        lx, ly, lz = spec["body"]["box"]["size"]
        out = {"x": h["cd_box_flat_face"] * ly * lz, "y": h["cd_box_flat_face"] * lx * lz, "z": h["cd_box_flat_face"] * lx * ly}
        for arm in spec["body"]["arms"]:
            v = np.asarray(arm["p1"], float) - np.asarray(arm["p0"], float)
            length = float(np.linalg.norm(v))
            a = v / length
            for i, ax in enumerate("xyz"):
                out[ax] += h["cd_cylinder_crossflow"] * 2.0 * arm["radius_m"] * length * (1.0 - a[i] ** 2) ** 1.5
        return out

    def drag(self) -> Dict[str, Any]:
        """Body drag of the multirotor (AeroBuildup of the box and the arm tubes). The flow runs along +x, -x, +y, -y, +z
        and -z of the body axes FRD (alpha and beta of the operating point). C_D A of an axis is the mean of the two
        directions of the force component along the flow: |F_b,i| / q. C_Di = C_D A / S_ref. AeroBuildup also gives a force
        along x for a pure side or vertical flow (a slender-body term of the fuselage model): it is not used.

        AeroBuildup is a slender-body method: it has no pressure drag on the flat front face of a bluff box. The hand check
        (hoerner_cda) has it. `drag_job.combine` picks the C_D A of each axis: asb, hoerner, or max (the larger one; the
        default, because a too small drag area is the unsafe error)."""
        import aerosandbox as asb
        spec = self.spec
        cfg = spec["drag_job"]
        plane = self.drag_airplane()
        atm = asb.Atmosphere(altitude=cfg["altitude_m"])
        rho, speed = float(atm.density()), cfg["speed_m_s"]
        q = 0.5 * rho * speed ** 2
        flows = {"+x": (0.0, 0.0, 0), "-x": (0.0, 180.0, 0), "+y": (0.0, 90.0, 1), "-y": (0.0, -90.0, 1),
                 "+z": (90.0, 0.0, 2), "-z": (-90.0, 0.0, 2)}
        cda = {}
        for key, (alpha, beta, i) in flows.items():
            op = asb.OperatingPoint(atmosphere=atm, velocity=speed, alpha=alpha, beta=beta)
            r = asb.AeroBuildup(airplane=plane, op_point=op).run()
            cda[key] = abs(_f(r["F_b"][i])) / q
            if not math.isfinite(cda[key]):
                raise RuntimeError(f"AeroBuildup gave no force for the flow {key}")
        mean = {ax: 0.5 * (cda["+" + ax] + cda["-" + ax]) for ax in "xyz"}
        s_ref = spec["reference"]["s_m2"]
        hoerner = self.hoerner_cda(spec, cfg["hoerner"])
        combine = cfg.get("combine", "max")
        pick = {"asb": lambda a, h: a, "hoerner": lambda a, h: h, "max": max}[combine]
        used = {ax: pick(mean[ax], hoerner[ax]) for ax in "xyz"}
        return {"speed_m_s": speed, "rho_kg_m3": rho, "S_ref_m2": s_ref, "CdA_by_direction_m2": cda, "CdA_asb_m2": mean,
                "hoerner_CdA_m2": hoerner, "combine": combine, "CdA_m2": used,
                "CD": {"CDx": used["x"] / s_ref, "CDy": used["y"] / s_ref, "CDz": used["z"] / s_ref},
                "asb_over_hoerner": {ax: mean[ax] / hoerner[ax] for ax in "xyz"},
                "asymmetry": {ax: abs(cda["+" + ax] - cda["-" + ax]) / mean[ax] for ax in "xyz"}}


# ========================================================================================================= the jobs
def _f(x):
    return float(np.ravel(x)[0])


def _installed(name):
    import importlib.metadata as md
    try:
        md.version(name)
        return True
    except md.PackageNotFoundError:
        return False


def job_version(job):
    import importlib.metadata as md
    import aerosandbox
    import casadi
    have = lambda name: f"{name} {md.version(name)}" if _installed(name) else f"no {name}"
    return {"version": f"aerosandbox {aerosandbox.__version__}, casadi {casadi.__version__}, {have('proptimiser')}, {have('jax')}"}


def job_chain(job):
    """electric_chain at numbers (tests and checks)."""
    out = electric_chain(job["torque_Nm"], job["omega_rad_s"], job["duty"], job["motor"], job["v_bus_V"])
    return {k: float(v) for k, v in out.items()}


def job_library_check(job):
    """The chain at kappa 1 and Q0 0 against the first-order motor of the AeroSandbox library (test)."""
    from aerosandbox.library.propulsion_electric import motor_electric_performance
    m = dict(job["motor"], kappa=1.0, q0_Nm=0.0)
    ours = electric_chain(job["torque_Nm"], job["omega_rad_s"], 1.0, m, job["v_bus_V"])
    lib = motor_electric_performance(rpm=job["omega_rad_s"] * 60 / (2 * math.pi), torque=job["torque_Nm"],
                                     kv=m["kv_rad_s_V"] * 60 / (2 * math.pi), resistance=m["r_tot_ohm"], no_load_current=m["i0_A"])
    return {"v_term_V": float(ours["v_term_V"]), "i_motor_A": float(ours["i_motor_A"]),
            "library_voltage_V": float(lib["voltage"]), "library_current_A": float(lib["current"])}


def job_synthetic_design(job):
    """Write a small Proptimiser design (default blade) into the Proptimiser home of the job (test)."""
    os.environ["PROPTIMISER_HOME"] = job["home"]
    from proptimiser.init import Inputs, Propeller
    Path(job["home"], "designs").mkdir(parents=True, exist_ok=True)
    Path(job["home"], "propellers").mkdir(parents=True, exist_ok=True)
    prop = Propeller.default(inputs=Inputs(coeff_method=3, n_r=8, n_psi=1, V_x=[job["V_x"], 0.8], V_yz=[0.0, 0.0]),
                             c=job["chord_m"], beta_deg=job["beta_deg"])
    prop.save(job["name"], overwrite=True)
    return {"saved": job["name"]}


def job_geometry(job):
    return FixedWingModel("fixed_wing", job["spec"]).geometry(job["out_dir"], job["main_wing"])


def job_polar(job):
    return FixedWingModel("fixed_wing", job["spec"]).polar(job["out_dir"], job["alpha_deg"], job.get("reference"))


def job_cruise_trim(job):
    return FixedWingModel("fixed_wing", job["spec"]).cruise_trim()


def job_neutral_point(job):
    return FixedWingModel("fixed_wing", job["spec"]).neutral_point()


def job_static_check(job):
    return FixedWingModel("fixed_wing", job["spec"]).static_check()


def _rho_of(job):
    spec = job["spec"]
    return float(job.get("rho_kg_m3") or isa_density(spec["analysis"]["altitude_m"]))


def job_multirotor_drag(job):
    return {"multirotor_drag": MultirotorModel("multirotor", {}, job["spec"]).drag()}


def job_emst_segments(job):
    """Hover, climb and forward flight (the tilt loop), and the full-throttle limit. Paper section III.A."""
    spec = job["spec"]
    a = spec["analysis"]
    mr = MultirotorModel.from_spec("multirotor", spec, _rho_of(job))
    m = mr.m
    return {"emst_segments": {"rho_kg_m3": m["rho"], "mass_kg": m["mass_kg"], "weight_N": m["mass_kg"] * G0, "n_rotors": m["n_rotors"],
                              "segments": mr.segments(a["climb_rate_m_s"], a["forward_speeds_m_s"]), "full_throttle": mr.full_throttle()}}


def job_emst_live(job):
    spec = job["spec"]
    mr = MultirotorModel.from_spec("multirotor", spec, _rho_of(job))
    return {"emst_live": mr.live(spec["live"]["designs"], spec["live"]["home"], spec["analysis"]["climb_rate_m_s"])}


def job_emst_endurance(job):
    """Endurance and range against the airspeed, with the best speeds (paper section III.A.4)."""
    a = job["spec"]["analysis"]
    return {"emst_endurance": MultirotorModel.from_spec("multirotor", job["spec"], _rho_of(job)).scan(a["scan_max_m_s"], a["scan_step_m_s"])}


def job_emst_sensitivity(job):
    """Central differences of the hover endurance (paper section III.A.5)."""
    spec = job["spec"]
    mr = MultirotorModel.from_spec("multirotor", spec, _rho_of(job))
    return {"emst_sensitivity": mr.sensitivity(spec["propulsion"]["battery"]["cells_s"], spec["analysis"]["sensitivity_step"])}


JOBS = {"version": job_version, "chain": job_chain, "library_check": job_library_check,
        "synthetic_design": job_synthetic_design, "geometry": job_geometry, "polar": job_polar,
        "cruise_trim": job_cruise_trim, "static_check": job_static_check, "neutral_point": job_neutral_point,
        "multirotor_drag": job_multirotor_drag, "emst_segments": job_emst_segments, "emst_endurance": job_emst_endurance,
        "emst_sensitivity": job_emst_sensitivity, "emst_live": job_emst_live}


def main(argv):
    job_file, result_file = Path(argv[1]), Path(argv[2])
    try:
        job = json.loads(job_file.read_text(encoding="utf-8"))
        res = {"ok": True, **JOBS[job["job"]](job)}
    except Exception as e:
        res = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
    result_file.write_text(json.dumps(res), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
