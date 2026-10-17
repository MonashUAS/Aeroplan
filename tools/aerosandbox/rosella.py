"""
Rosella: propulsion sizing of a VTOL quadplane in AeroSandbox. One script, no other module of the repository is changed.

    python rosella.py optimise [--config H4] [--cells 12] [--out DIR] [--upto L4]   the ladder, result of the highest level
    python rosella.py ladder [--config H4] [--cells 12] [--upto L2] [--multistart 5] [--from L3]
    python rosella.py rotor-check                      table, BEMT and momentum shaft power at 22.4 N hover thrust
    python rosella.py evaluate NAME [--file F] [--out DIR] [--level L4]   NAME is a block of settings/rosella.manual.json
    python rosella.py order-sheet [--case H4_12S] [--out DIR]

Run it with the AeroSandbox Python (tools/aerosandbox/.venv). It needs aerosandbox, casadi, proptimiser (with the geometric
scale, Proptimiser 711ef86), numpy, pyyaml and aeroplan (to read aircraft/currawong).

Model (design frame: x aft, y right, z up, metres, kilograms, seconds):
  Airframe   the Currawong V1 wing, tail and tail boom, a new fuselage (superellipse body), two lift booms parallel to x at
             y = +/-y_b. Each boom is clamped to the wing at x_c = x_wing_mid + dx and carries a rotor at each end, at
             x_c -/+ a. H4: one rotor on each end. H8: a coaxial pair on each end (same booms).
  Masses     Currawong items that Rosella keeps, plus new items. Motor, ESC, carbon propeller, cables and battery follow
             Bershadsky, Haviland, Johnson, AIAA 2016-0581 (Eq. 1 to 5), the motor refitted on data/motor_survey.csv.
  Rotor      Proptimiser BEMT (NeuralFoil sections) in the full-space Opti form (levels L3, L4), a fitted CT and CP table (L1 to L3)
             or momentum theory (L0). The radius is a geometric scale s = R / R_ref. See the ladder command.
  Electric   the motor chain of AIAA 2016-0581 Eq. 9 to 11 for every rotor, one set of identical motors and ESCs.
  Mission    six conditions: H_TO, C_TO, F_LAP, F_MAP, H_L and MAX (settings/rosella.yaml, section mission).
  Structure  each boom end is a cantilever from the clamp: stress, local buckling, tip slope and the first bending frequency.
  Control    hover moments with thrust in [idle, T_max] against the angular acceleration the handling-quality bandwidth needs.
  CG         x_cg = x_np - SM_target * MAC with x_np from a vortex lattice run. The battery x and the boom shift dx close it.

Every number that is a stand-in carries `placeholder: true` in the settings. The script lists the ones that matter in the
report (`placeholders` in each result file).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))                           # `import aeroplan` and `tools.aerosandbox` from the checkout
sys.path.insert(0, str(HERE))

G0 = 9.80665
RHO0 = 1.225                                            # kg/m3, ISA sea level (the air of the Proptimiser tables)
MU0 = 1.789e-5                                          # Pa s
CU_RHO, CU_RES = 8960.0, 1.724e-8                       # copper density (kg/m3) and resistivity (Ohm m, 20 C)
WORK = ROOT / "work" / "aerosandbox" / "rosella"


# ======================================================================================================== 0. settings
def settings(path: Optional[Path] = None) -> Dict[str, Any]:
    import yaml
    return yaml.safe_load((path or HERE / "settings" / "rosella.yaml").read_text(encoding="utf-8"))


def apply_sets(st: Dict[str, Any], sets: Optional[List[str]]) -> Dict[str, Any]:
    """Change settings for one run, for example `cruise_aero.map_speed_m_s=19`. A number entry with a `value` key changes its
    value. The run reports the change in the result (`settings_changed`). The YAML file stays as it is."""
    import yaml
    for s in sets or []:
        path, _, text = s.partition("=")
        keys = path.split(".")
        node = st
        for k in keys[:-1]:
            node = node[k]
        new = yaml.safe_load(text)
        if isinstance(node[keys[-1]], dict) and "value" in node[keys[-1]]:
            node[keys[-1]]["value"] = new
        else:
            node[keys[-1]] = new
    st["_changed"] = list(sets or [])
    return st


def val(block: Any, key: Optional[str] = None) -> float:
    """The number of a `{value, source}` settings entry (or of the entry itself when it is a number)."""
    b = block[key] if key is not None else block
    return float(b["value"] if isinstance(b, dict) else b)


def placeholders(st: Dict[str, Any], prefix: str = "") -> List[str]:
    """The settings paths marked placeholder: true or with value null."""
    out: List[str] = []
    if isinstance(st, dict):
        if st.get("placeholder") is True:
            out.append(prefix.rstrip("."))
        for k, v in st.items():
            out += placeholders(v, f"{prefix}{k}.")
    return out


def boom_material(mat: Dict[str, Any], E_GPa: Optional[float] = None, rho_kg_m3: Optional[float] = None) -> Dict[str, float]:
    """The boom material numbers {E, E_c, rho} (Pa, Pa, kg/m3). E_GPa and rho_kg_m3 replace the settings. The compression
    modulus keeps the ratio E_c / E of the settings."""
    E0 = val(mat, "E_axial_Pa")
    E = E0 if E_GPa is None else float(E_GPa) * 1e9
    return {"E": E, "E_c": val(mat, "E_axial_compression_Pa") * E / E0,
            "rho": val(mat, "density_kg_m3") if rho_kg_m3 is None else float(rho_kg_m3)}


def passes(c: Dict[str, Any]) -> bool:
    """True when a constraint of the report holds: margin >= -1e-6 (inequality) or >= -1e-4 (equality)."""
    return bool(c["margin"] >= (-1e-4 if c.get("equality") else -1e-6))


# ================================================================================================ 1. component models
class MotorFit:
    """
    The motor fitted on data/motor_survey.csv (log-linear least squares), three relations:
        m  = exp(a0) kv^a1 q_cap^a2        q_cap = (Imax - I0) / Kv_rad, the torque the motor holds for the 180 s peak current
        Rm = exp(b0) kv^b1 m^b2            (the maker states the phase resistance as given in the CSV note)
        I0 = exp(c0) kv^c1 m^c2
    Kv is in rpm/V. AIAA 2016-0581 Eq. 1 (m = 10^p1 Kv^p2, g) is kept for the cross-check.
    """

    def __init__(self, path: Path, kv_range=(60.0, 450.0), m_range=(150.0, 1600.0)):
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
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

    @staticmethod
    def _fit(y, xs):
        A = np.column_stack([np.ones(len(y))] + [np.log(x) for x in xs])
        coef, *_ = np.linalg.lstsq(A, np.log(y), rcond=None)
        rms = float(np.sqrt(np.mean((A @ coef - np.log(y)) ** 2)))          # RMS of the log error (fraction)
        return coef, rms

    def mass_g(self, kv, q_cap):
        import aerosandbox.numpy as anp
        c = self.mass_fit
        return anp.exp(c[0]) * kv ** c[1] * q_cap ** c[2]

    def rm_ohm(self, kv, m_g):
        import aerosandbox.numpy as anp
        c = self.rm_fit
        return anp.exp(c[0]) * kv ** c[1] * m_g ** c[2]

    def i0_A(self, kv, m_g):
        import aerosandbox.numpy as anp
        c = self.i0_fit
        return anp.exp(c[0]) * kv ** c[1] * m_g ** c[2]

    def summary(self) -> Dict[str, Any]:
        return {"rows": self.n, "mass": list(map(float, self.mass_fit)), "mass_rms_log": self.mass_rms,
                "rm": list(map(float, self.rm_fit)), "rm_rms_log": self.rm_rms,
                "i0": list(map(float, self.i0_fit)), "i0_rms_log": self.i0_rms, "q_cap_range_Nm": self.q_range}


def bershadsky_motor_g(kv, p1=4.0499, p2=-0.5329):
    return 10.0 ** p1 * kv ** p2


def carbon_prop_g(diameter_m, st):
    """AIAA 2016-0581 Eq. 5 for carbon: m = p1 D^2 + p2 D (g, D in inch)."""
    b = st["bershadsky"]["carbon_prop_g"]
    d_in = diameter_m / 0.0254
    return b["a_in2"] * d_in ** 2 + b["b_in"] * d_in


def battery_mass_kg(cells_s, cap_Ah, st):
    """AIAA 2016-0581 Eq. 4 times the calibration to the NXE 6S 4500 pack: m = k (p1 S + p2) C (g, C in mAh)."""
    b = st["bershadsky"]["battery_g"]
    nxe = st["battery"]["nxe_6s_4500"]
    eq4_nxe = (b["p1"] * 6 + b["p2"]) * 4500.0
    k_cal = val(nxe["mass_kg"]) * 1000.0 / eq4_nxe
    return k_cal * (b["p1"] * cells_s + b["p2"]) * cap_Ah * 1000.0 / 1000.0


# ========================================================================================================= 2. airframe
class Airframe:
    """The fixed airframe of Rosella: Currawong wing, tail and tail boom, the new fuselage, and the numbers taken from them
    (positions, masses of the kept items, the neutral point, the polar)."""

    def __init__(self, st: Dict[str, Any], cache: Optional[Path] = None):
        self.st = st
        from aeroplan import adh_doc, source_tree
        from aeroplan.geometry import body_frames
        import spec as asb_spec
        acft = source_tree.read(ROOT / "aircraft" / st["base"])
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
        self.surfaces = {n: asb_spec._surface_spec(doc, n) for n in ("wing_main", "htail", "fin")}
        self.htail_le_x = float(min(s_["xyz_le"][0] for s_ in self.surfaces["htail"]["sections"]))      # planform LE of the htail
        self.tail_boom_frames = [f.tolist() for f in body_frames(adh_doc.find(doc, "tail_boom")["geometry"]["body"])]
        self.tail_boom_z = float(np.array(self.tail_boom_frames[0])[:, 2].mean())   # axis height at the joint end (lift booms are level with it)
        self.fuselage_frames = [f.tolist() for f in body_frames(adh_doc.find(doc, "fuselage")["geometry"]["body"])]
        prop = adh_doc.find(doc, "prop_cruise")["muas"]
        self.cruise_hub_currawong = prop["propeller"]["hub"]["xyz"]
        ps = prop["propulsion_system"]
        m = ps["motor"]
        self.cruise = {"kv_rad_s_V": m["kv"]["value"], "i0_A": m["i0"]["value"], "kappa": m["kappa"],
                       "r_tot_ohm": m["r_tot"]["value"], "mass_kg": m["mass"]["value"], "imax_A": m["imax_continuous"]["value"],
                       "diameter_m": prop["propeller"]["diameter"]["value"]}
        self.cruise_offsets = {k: pm[t]["position"]["xyz"][0] - self.cruise_hub_currawong[0] for k, t in
                               (("motor", "PROPULSION-MOTOR"), ("esc", "PROPULSION-ESC"), ("prop", "PROPULSION-PROP"),
                                ("rest", "PROPULSION-REST"))}
        self.m_cruise_esc = pm["PROPULSION-ESC"]["mass"]["value"]
        self.m_cruise_prop = pm["PROPULSION-PROP"]["mass"]["value"]
        self.m_cruise_rest = pm["PROPULSION-REST"]["mass"]["value"]
        self.neutral_point = self._neutral_point(cache)
        self.wing_le_x, self.wing_te_x = self._wing_edges()
        sm = val(st["limits"]["static_margin_target"])
        self.x_cg = self.neutral_point - sm * self.c_ref
        self.x_hub = self.x_cg - val(st["limits"]["cg_nose_prop_m"])
        self.polar = self._polar(cache)

    # -- geometry helpers
    def _wing_edges(self):
        """Linear fits of the wing LE and TE x against y over the inner 1 m (where the booms sit)."""
        sec = self.surfaces["wing_main"]["sections"]
        y = np.array([s["xyz_le"][1] for s in sec])
        le = np.array([s["xyz_le"][0] for s in sec])
        te = le + np.array([s["chord"] for s in sec])
        m = y <= 1.0
        return (np.polyfit(y[m], le[m], 1), np.polyfit(y[m], te[m], 1))

    def _build(self, fuselages: bool):
        import aerosandbox as asb
        from asb_worker import build_airplane
        spec = {"name": "Rosella", "reference": {"s_m2": self.s_ref, "b_m": self.b_ref, "c_m": self.c_ref,
                                                 "xyz_ref": [self.x_cg_guess(), 0.0, 0.0]},
                "surfaces": [self.surfaces[n] for n in ("wing_main", "htail", "fin")],
                "fuselages": ([{"name": "fuselage", "frames": self.new_fuselage_frames()},
                               {"name": "tail_boom", "frames": self.tail_boom_frames}] if fuselages else []),
                "propulsion": {"hub": [self.x_hub if hasattr(self, "x_hub") else -0.65, 0.0, -0.035],
                               "thrust_axis": [-1.0, 0.0, 0.0], "diameter_m": self.cruise["diameter_m"]}}
        return build_airplane(spec)

    def x_cg_guess(self):
        return getattr(self, "x_cg", 0.12)

    def new_fuselage_frames(self):
        """The new fuselage: a superellipse body from the nose to the tail boom joint. The size is the bay (settings)."""
        fz = self.st["fuselage"]
        n = int(fz["stations"])
        x0 = (self.x_hub if hasattr(self, "x_hub") else -0.65) + fz["nose_behind_hub_m"]
        x1 = self.tail_boom_frames[0][0][0]
        xs = np.linspace(x0, x1, n)
        frames = []
        for x in xs:
            t = (x - x0) / (x1 - x0)
            # Nose rises to the full section at 25 % of the length, holds it to 65 %, tapers to the tail boom joint.
            if t < 0.25:
                k = math.sin(0.5 * math.pi * t / 0.25) ** 0.7
            elif t <= 0.65:
                k = 1.0
            else:
                k = max(0.02, math.cos(0.5 * math.pi * (t - 0.65) / 0.35) ** 0.8)
            w, h = 0.5 * val(fz, "width_m") * k, 0.5 * val(fz, "height_m") * k
            th = np.linspace(0.0, math.pi, 17)
            e = 2.0 / fz["superellipse_n"]
            y = w * np.abs(np.sin(th)) ** e
            z = float(fz["z_centre_m"]) + h * np.sign(np.cos(th)) * np.abs(np.cos(th)) ** e
            frames.append([[x, float(yy), float(zz)] for yy, zz in zip(y, z)])
        return frames

    def _neutral_point(self, cache):
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

    def _polar(self, cache):
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
        """Wetted area of the new fuselage (m2), summed over the frames."""
        fr = [np.array(f) for f in self.new_fuselage_frames()]
        tot = 0.0
        for f0, f1 in zip(fr[:-1], fr[1:]):
            p0 = 2.0 * np.linalg.norm(np.diff(f0[:, 1:], axis=0), axis=1).sum()
            p1 = 2.0 * np.linalg.norm(np.diff(f1[:, 1:], axis=0), axis=1).sum()
            tot += 0.5 * (p0 + p1) * (f1[0, 0] - f0[0, 0])
        return float(tot)

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


# ========================================================================================================== 3. rotors
_MODELS: Dict[str, Any] = {}


def proptimiser_home() -> Path:
    """work/aerosandbox/rosella/proptimiser: the lift blade (Redback FLUXER, Fit C) and the cruise blade (Currawong V1) copied
    by hand from the work folders of those aircraft (Proptimiser reads one home folder)."""
    import shutil
    home = WORK / "proptimiser"
    for ac, names in (("redback", ["MAD_FLUXER_22x6_6"]), ("currawong", ["Currawong_V1"])):
        for n in names:
            for sub, ext in (("designs", ".yaml"), ("propellers", ".state.json")):
                dst = home / sub / (n + ext)
                if not dst.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / "work" / "aerosandbox" / ac / "proptimiser" / sub / (n + ext), dst)
    return home


def prop_model(design: str):
    """The CasADi Proptimiser model of a design from the Rosella home folder."""
    if design not in _MODELS:
        os.environ["PROPTIMISER_HOME"] = str(proptimiser_home())
        from proptimiser.casadi_prop import PropellerModel
        from proptimiser.init import Propeller
        _MODELS[design] = PropellerModel.from_propeller(Propeller.load(design), n_psi=1)
    return _MODELS[design]


def lift_model(st):
    return prop_model(st["proptimiser_design"])


def cruise_model(st):
    return prop_model(st["cruise_propulsion"]["proptimiser_design"])


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


# ------------------------------------------------------------------------------------------ rotor models for the ladder
TABLES = WORK / "tables"
A0 = 340.3                                              # m/s, speed of sound used for the tip Mach number
_CONST: Dict[str, Any] = {}


def _poly_fit(X: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float]:
    """Least squares fit y = X c. Returns c and the RMS of (fit - y) over mean |y| (fraction)."""
    c, *_ = np.linalg.lstsq(X, y, rcond=None)
    return c, float(np.sqrt(np.mean((X @ c - y) ** 2)) / np.mean(np.abs(y)))


def _json_cache(path: Path, key: Dict[str, Any], make):
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

    def __init__(self, st):
        tb, R0 = st["ladder"]["table"], float(st["proptimiser_reference_radius_m"])
        self.R0, self.deg = R0, int(val(tb, "poly_degree"))
        key = {"design": st["proptimiser_design"], "omega": tb["omega_rad_s"]["value"], "scale": tb["scale"]["value"],
               "v_x": tb["v_x_m_s"]["value"]}
        model = lift_model(st)

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
        self.samples = np.array(_json_cache(TABLES / "lift_samples.json", key, make))
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
    """CT(J, M_tip) and CP(J, M_tip) of the cruise blade (Currawong V1), fitted over J up to fit_J_max."""

    def __init__(self, st, diameter_m: float):
        tb = st["ladder"]["cruise_table"]
        self.D, self.deg = diameter_m, int(val(tb, "poly_degree"))
        key = {"design": st["cruise_propulsion"]["proptimiser_design"], "omega": tb["omega_rad_s"]["value"],
               "J": tb["J"]["value"], "D": diameter_m}
        model = cruise_model(st)

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
        self.samples = np.array(_json_cache(TABLES / "cruise_samples.json", key, make))
        w, V, T, Q = self.samples.T
        n = w / (2 * math.pi)
        J, CT, CP = V / (n * diameter_m), T / (RHO0 * n ** 2 * diameter_m ** 4), Q * w / (RHO0 * n ** 3 * diameter_m ** 5)
        m = J <= val(tb, "fit_J_max") + 1e-9
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


def lift_table(st) -> LiftTable:
    if "lift_table" not in _CONST:
        _CONST["lift_table"] = LiftTable(st)
    return _CONST["lift_table"]


def cruise_diameter(st) -> float:
    if "cruise_D" not in _CONST:
        from aeroplan import adh_doc, source_tree
        doc = source_tree.read(ROOT / "aircraft" / st["base"]).doc
        _CONST["cruise_D"] = float(adh_doc.find(doc, "prop_cruise")["muas"]["propeller"]["diameter"]["value"])
    return _CONST["cruise_D"]


def cruise_table(st) -> CruiseTable:
    if "cruise_table" not in _CONST:
        _CONST["cruise_table"] = CruiseTable(st, cruise_diameter(st))
    return _CONST["cruise_table"]


def momentum_constants(st) -> Dict[str, float]:
    """FM and the hover CT of the base blade (numeric solve at scale 1, about 435 rad/s, 0 m/s), and the cruise propulsive
    efficiency and advance ratio of Currawong_V1 (numeric solve at 17 m/s and 18 N). Computed once."""
    if "momentum" not in _CONST:
        mm = st["ladder"]["momentum"]
        R0, w = float(st["proptimiser_reference_radius_m"]), val(mm, "omega_rad_s")
        T, Q, _ = lift_model(st).solve(w, 0.0, 0.0, 30.0, scale=val(mm, "scale"))
        A, n, D = math.pi * R0 ** 2, w / (2 * math.pi), 2 * R0
        fm = T ** 1.5 / math.sqrt(2 * RHO0 * A) / (Q * w)
        ct0 = T / (RHO0 * n ** 2 * D ** 4)
        cm = cruise_model(st)
        wc = omega_guess(cm, 18.0, 17.0, 1.0)
        Tc, Qc, _ = cm.solve(wc, 17.0, 0.0, 15.0)
        _CONST["momentum"] = {"FM": fm, "CT0": ct0, "T_hover_N": T, "eta_cruise": Tc * 17.0 / (Qc * wc),
                              "J_cruise": 17.0 / (wc / (2 * math.pi) * cruise_diameter(st))}
    return _CONST["momentum"]


def rotor_check(st, thrust_N: float = 22.4) -> Dict[str, Any]:
    """Shaft power at scale 1 and thrust_N in hover: table fit against the numeric BEMT (and the momentum model)."""
    tb, model, R0 = lift_table(st), lift_model(st), float(st["proptimiser_reference_radius_m"])
    lo, hi = 150.0, 800.0
    for _ in range(60):                                  # bisection on the table thrust
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if tb.loads(mid, 0.0, 1.0)[0] < thrust_N else (lo, mid)
    w_t = 0.5 * (lo + hi)
    p_table = float(tb.loads(w_t, 0.0, 1.0)[2])
    w_b = omega_guess(model, thrust_N, 0.0, 1.0)
    for _ in range(3):
        Tb, Qb, _ = model.solve(w_b, 0.0, 0.0, 30.0)
        w_b *= math.sqrt(thrust_N / Tb)
    Tb, Qb, _ = model.solve(w_b, 0.0, 0.0, 30.0)
    mc = momentum_constants(st)
    p_mom = thrust_N ** 1.5 / math.sqrt(2 * RHO0 * math.pi * R0 ** 2) / mc["FM"]
    return {"thrust_N": thrust_N, "omega_table": w_t, "P_table_W": p_table, "omega_bemt": w_b, "T_bemt_N": Tb,
            "P_bemt_W": Qb * w_b, "P_momentum_W": p_mom, "table_over_bemt": p_table / (Qb * w_b),
            "momentum_over_bemt": p_mom / (Qb * w_b),
            "fit_rms": {"lift_CT": tb.rms_ct, "lift_CP": tb.rms_cp}}


# ================================================================================================== 4. the Opti problem
GROUPS_L0 = ("mass", "cg", "energy", "tw")
GROUPS_L1 = GROUPS_L0 + ("elec",)
GROUPS_ALL = GROUPS_L1 + ("structure", "stiffness", "clear", "control")
LEVELS: Dict[str, Dict[str, Any]] = {
    "L0": {"lift": "momentum", "cruise": "momentum", "bemt": (), "groups": GROUPS_L0},
    "L1": {"lift": "table", "cruise": "table", "bemt": (), "groups": GROUPS_L1},
    "L2": {"lift": "table", "cruise": "table", "bemt": (), "groups": GROUPS_ALL},
    "L3": {"lift": "table", "cruise": "table", "bemt": ("H_TO_f", "H_TO_r"), "groups": GROUPS_ALL},
    "L4": {"lift": "bemt", "cruise": "bemt", "bemt": (), "groups": GROUPS_ALL},
}


class Case:
    """One sizing problem: a configuration (H4, H8) and a cell count. build() sets up the Opti, solve() runs it.
    level: a key of LEVELS, or a dict with the same keys (rotor model of the lift and cruise rotors, the states that use
    the full-space BEMT in spite of that, and the constraint groups). feasibility: minimise the sum of slacks of the
    inequalities in place of the energy. init: start values by name (see init_from)."""

    DESIGN = ("t_boom", "r_boom", "y_b", "dx", "a", "scale", "kv", "q_cap", "cant", "cap_Ah", "x_batt")

    def __init__(self, st, air: Airframe, motor: MotorFit, config: str, cells_s: int,
                 fixed: Optional[Dict[str, float]] = None, overrides: Optional[Dict[str, Any]] = None,
                 level: Any = "L4", feasibility: bool = False, init: Optional[Dict[str, float]] = None):
        import aerosandbox as asb
        self.st, self.air, self.motor_fit = st, air, motor
        self.config, self.S = config, int(cells_s)
        self.fixed, self.ov = dict(fixed or {}), dict(overrides or {})
        self.level_name = level if isinstance(level, str) else "custom"
        self.level = dict(LEVELS[level] if isinstance(level, str) else level)
        self.feasibility = bool(feasibility)
        self.init = dict(init or {})
        self.n_per = 2 if config == "H8" else 1              # rotors at each of the 4 stations
        self.N = 4 * self.n_per
        self.opti = asb.Opti()
        self.v: Dict[str, Any] = {}                         # design variables (and parameters when fixed)
        self.named: Dict[str, Any] = {}                     # every Opti variable by name (design, I_pk, V_lap, w_<state>)
        self.bounds: Dict[str, Tuple[float, float]] = {}
        self.cons: Dict[str, Any] = {}                      # name -> (expression, lo, hi), the report
        self.cgroup: Dict[str, str] = {}
        self.cscale: Dict[str, float] = {}
        self.duals: Dict[str, List[Any]] = {}
        self.slacks: Dict[str, Any] = {}
        self.sol = None
        self.error = ""
        self.stats: Dict[str, Any] = {}

    # -- Opti helpers
    def var(self, name, init, lo, hi, scale=None, design=True):
        """An Opti variable by name. Start value: self.init[name] (clipped to the bounds) or init."""
        o = self.opti
        if name in self.fixed:
            x = o.parameter(float(self.fixed[name]))
        else:
            x0 = min(max(float(self.init.get(name, init)), lo), hi)
            x = o.variable(init_guess=x0, lower_bound=lo, upper_bound=hi, scale=scale or max(abs(init), 1e-3))
            self.named[name] = x
            self.bounds[name] = (lo, hi)
        if design:
            self.v[name] = x
        return x

    def start(self, name, default):
        """The numeric start value of a variable or fixed parameter."""
        return float(self.fixed[name]) if name in self.fixed else float(self.init.get(name, default))

    def limit(self, name, expr, lo=None, hi=None, scale=None, group="misc"):
        """Constrain lo <= expr <= hi when the group is on at this level, and keep it for the report. The constraint is
        scaled by `scale` (default: the size of the numeric bound). In the feasibility phase a slack >= 0 relaxes it."""
        o = self.opti
        if scale is None:
            b = [abs(x) for x in (lo, hi) if isinstance(x, (int, float)) and x != 0.0]
            scale = b[0] if b else 1.0
        self.cons[name], self.cgroup[name], self.cscale[name] = (expr, lo, hi), group, float(scale)
        if group not in self.level["groups"]:
            return
        sl = 0.0
        if self.feasibility:
            sl = o.variable(init_guess=0.05, lower_bound=0.0, scale=0.1)
            self.slacks[name] = sl
        d = []
        if lo is not None:
            d.append(o.subject_to(expr / scale >= lo / scale - sl))
        if hi is not None:
            d.append(o.subject_to(expr / scale <= hi / scale + sl))
        self.duals[name] = d

    def kind(self, role: str, state: str) -> str:
        """The rotor model of a state: momentum, table or bemt."""
        return "bemt" if state in self.level["bemt"] else self.level[role]

    def prop(self, role: str, name: str, target, V, T_est: float, V0: float) -> Dict[str, Any]:
        """
        One rotor at one state. role is "lift" or "cruise". target is the thrust (N) the rotor must give. V is the axial speed
        (number or expression), V0 its start value, T_est a number near the thrust (it only scales the equality).
        Returns omega, T, Q, P_shaft as expressions of the Opti variables (shaft speed w_<name> and the scale).
          momentum  no variable: omega from the constant CT (lift) or the constant J (cruise), P from the momentum theory
          table     variable omega, T from the fitted CT and CP, equality T = target
          bemt      variable omega and the inflow variables of Proptimiser (add_to), equality T = target
        """
        import aerosandbox.numpy as anp
        st, o = self.st, self.opti
        kind, lift = self.kind(role, name), role == "lift"
        if lift:
            s, R, s0, ts = self.v["scale"], self.R, self.start("scale", 1.0), 30.0
        else:
            s, R, s0, ts = 1.0, 0.5 * cruise_diameter(st), 1.0, 15.0
        D = 2.0 * R
        if kind == "momentum":
            mc = momentum_constants(st)
            if lift:
                P = target * (0.5 * V + anp.sqrt((0.5 * V) ** 2 + target / (2.0 * RHO0 * math.pi * R ** 2))) / mc["FM"]
                w = 2.0 * math.pi * anp.sqrt(target / (mc["CT0"] * RHO0)) / D ** 2
            else:
                P = target * V / mc["eta_cruise"]
                w = 2.0 * math.pi * V / (mc["J_cruise"] * D)
            return {"omega": w, "T": target, "Q": P / w, "P_shaft": P}
        model = lift_model(st) if lift else cruise_model(st)             # Proptimiser loads only for the table and BEMT levels
        lo, hi = {("lift", "table"): (250.0, 800.0), ("cruise", "table"): (400.0, 800.0),
                  ("lift", "bemt"): (100.0, 800.0), ("cruise", "bemt"): (150.0, 900.0)}[(role, kind)]
        key = ("wguess", st["proptimiser_design"] if lift else "cruise", round(T_est, 1), round(float(V0), 1), round(s0, 3))
        w0 = self.init.get("w_" + name)
        if w0 is None:
            if key not in _CONST:
                _CONST[key] = omega_guess(model, T_est, float(V0), s0)
            w0 = _CONST[key]
        w0 = min(max(float(w0), lo), hi)
        w = self.var("w_" + name, w0, lo, hi, scale=300.0, design=False)
        if kind == "table":
            T, Q, P = lift_table(st).loads(w, V, s) if lift else cruise_table(st).loads(w, V)
        else:
            if (st.get("solver") or {}).get("bemt_kernel", "mx") == "fast":
                import fast_bemt
                out = fast_bemt.add_to(model, o, w, V, ts, scale=s)
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

    # -- the model
    def build(self):
        import aerosandbox.numpy as anp
        st, air, o = self.st, self.air, self.opti
        S, N, n_per = self.S, self.N, self.n_per
        lim, mis, el, ca, sc = st["limits"], st["mission"], st["electrical"], st["cruise_aero"], st["structure"]
        mat = st["material"][st["material"]["design_choice"]]
        bm = st["bershadsky"]
        R_ref = float(st["proptimiser_reference_radius_m"])
        V_cell, V_end = val(el, "cell_nominal_V"), val(el, "cell_end_V")
        ov = self.ov
        bo = ov.get("boom") or boom_material(mat)

        # ---- design variables
        t = self.var("t_boom", 0.0015, val(st["structure"], "min_wall_m"), 0.005, scale=1e-3)
        r_o = self.var("r_boom", 0.020, 0.008, 0.045, scale=1e-2)
        y_b = self.var("y_b", 0.65, 0.35, 1.0)
        dx = self.var("dx", 0.0, -0.35, 0.35, scale=0.1)
        a = self.var("a", 0.50, 0.25, 1.0)
        rb = st["radius_bounds_m"]
        s = self.var("scale", 1.0, rb[0] / R_ref, rb[1] / R_ref)
        kv = self.var("kv", 150.0, 60.0, 450.0)
        q_cap = self.var("q_cap", 3.0, 0.5, 9.0)
        cant = self.var("cant", 0.05, 0.0, math.radians(10.0), scale=0.1)
        cap = self.var("cap_Ah", 14.0, 2.0, 60.0)
        bay = st["fuselage"]["bay_x_m"]["value"]
        x_bat = self.var("x_batt", 0.0, bay[0], bay[1], scale=0.1)
        R = R_ref * s
        D = 2.0 * R
        x_cg = air.x_cg
        self.R = R

        # ---- motor, prop
        mo = ov.get("motor", {})
        m_motor_g = mo["mass_kg"] * 1000.0 if "mass_kg" in mo else self.motor_fit.mass_g(kv, q_cap)
        rm = mo["rm_ohm"] if "rm_ohm" in mo else self.motor_fit.rm_ohm(kv, m_motor_g)
        i0 = mo["i0_A"] if "i0_A" in mo else self.motor_fit.i0_A(kv, m_motor_g)
        m_motor = m_motor_g / 1000.0
        m_prop = ov["prop"]["mass_kg"] if "mass_kg" in ov.get("prop", {}) else carbon_prop_g(D, st) / 1000.0
        kv_rad = kv * 2.0 * math.pi / 60.0
        m_mount = val(st["fixed_mass_kg"], "motor_mount_each")
        m_clamp = val(st["fixed_mass_kg"], "boom_clamp_each")

        # ---- boom
        over = val(sc, "overhang_m")
        L_boom = 2.0 * a + 2.0 * over
        r_i = r_o - t
        A_sec = math.pi * (r_o ** 2 - r_i ** 2)
        I_sec = 0.25 * math.pi * (r_o ** 4 - r_i ** 4)
        m_boom_each = bo["rho"] * A_sec * L_boom
        m_boom = 2.0 * m_boom_each
        x_c = 0.5 * (air.te_x(0.0) + air.le_x(0.0)) + dx
        x_f, x_r = x_c - a, x_c + a
        z_b = air.tail_boom_z                                     # user 2026-10-17: lift booms level with the tail boom
        z_rotor = z_b + val(sc, "mount_offset_m")                 # the rotor plane sits one mount offset above the boom axis
        self.z_rotor = z_rotor

        # ---- cables, ESC, battery
        I_pk = self.var("I_pk", 60.0, 5.0, 250.0, scale=50.0, design=False)
        A_cu = I_pk / val(el, "wire_current_density_A_m2")

        def run_len(xh):
            return anp.sqrt((xh - x_bat) ** 2 + 1e-4) + y_b + over + abs(z_b) + val(el, "run_extra_m")
        L_runs = [run_len(x_f), run_len(x_r)]
        m_wire = sum(2 * 2.0 * n_per * L * CU_RHO * A_cu for L in L_runs) * val(el, "wire_insulation_factor")
        R_w = [CU_RES * 2.0 * L / A_cu for L in L_runs]                       # out and back, one motor
        R_e = val(el, "re_ohm")
        m_esc = bm["esc_g_per_A"]["value"] / 1000.0 * val(bm, "esc_peak_factor") * I_pk
        if "mass_kg" in ov.get("esc", {}):
            m_esc = ov["esc"]["mass_kg"]
        m_batt = ov["battery"]["mass_kg"] if "mass_kg" in ov.get("battery", {}) else battery_mass_kg(S, cap, st)
        R_b = S * (val(st["battery"], "cell_resistance_mohm") / 1000.0) * 4.5 / cap

        # ---- mass list (name, mass, x, y, z, own inertia ixx, iyy, izz)
        fz, kc = st["fuselage"], st["kept_from_currawong"]
        m_fuse = air.fuselage_area() * val(fz, "mass_kg_per_m2")
        m_lift_unit = m_motor + m_prop + m_esc + m_mount
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
        add("avionics_vtol", val(st["fixed_mass_kg"], "avionics"), x_cg, 0.0, 0.0)
        Lf = air.fuselage_length()
        add("fuselage", m_fuse, air.fuselage_mid_x(), 0.0, float(fz["z_centre_m"]), (0.0, m_fuse * Lf ** 2 / 12.0, m_fuse * Lf ** 2 / 12.0))
        add("payload_cargo", val(mis["payload"], "cargo_kg"), x_cg + kc["cargo_x_from_cg_m"], 0.0, 0.0)
        add("payload_camera", val(mis["payload"], "camera_kg"), kc["camera_x_m"], 0.0, -0.05)
        add("landing_gear", val(kc, "landing_gear_kg"), kc["landing_gear_x_m"], 0.0, -0.10)
        for k in ("motor", "esc", "prop", "rest"):
            m_k = {"motor": air.cruise["mass_kg"], "esc": air.m_cruise_esc, "prop": air.m_cruise_prop, "rest": air.m_cruise_rest}[k]
            add("cruise_" + k, m_k, air.x_hub + air.cruise_offsets[k], 0.0, -0.035)
        add("battery", m_batt, x_bat, 0.0, 0.0, (m_batt * 0.02 / 12.0, m_batt * 0.13 / 12.0, m_batt * 0.13 / 12.0))
        for side in (-1, 1):
            add("boom", m_boom_each, x_c, side * y_b, z_b, (0.0, m_boom_each * L_boom ** 2 / 12.0, m_boom_each * L_boom ** 2 / 12.0))
            add("boom_clamp", m_clamp, x_c, side * y_b, z_b)
            add("lift_front", n_per * m_lift_unit, x_f, side * y_b, z_rotor)
            add("lift_rear", n_per * m_lift_unit, x_r, side * y_b, z_rotor)
        add("cables", m_wire, x_c, 0.0, 0.5 * z_b)
        M = sum(i[1] for i in items)
        self.M, self.items = M, items
        self.limit("mtow_kg", M, hi=val(lim, "mtow_kg"), group="mass")
        mx = sum(i[1] * i[2] for i in items)
        o.subject_to((mx - x_cg * M) / 0.1 == 0)                     # CG: polynomial form, scaled by 0.1 kg m
        self.cons["cg_x_m"], self.cgroup["cg_x_m"], self.cscale["cg_x_m"] = (mx / M, x_cg, x_cg), "cg", 1e-2
        Ixx = sum(i[5] + i[1] * (i[3] ** 2 + i[4] ** 2) for i in items)
        Iyy = sum(i[6] + i[1] * ((i[2] - x_cg) ** 2 + i[4] ** 2) for i in items)
        Izz = sum(i[7] + i[1] * ((i[2] - x_cg) ** 2 + i[3] ** 2) for i in items)
        self.inertia = (Ixx, Iyy, Izz)

        # ---- hover thrust of one rotor at the front and the rear end (moment balance about the CG)
        W = M * G0
        share_f = (x_r - x_cg) / (x_r - x_f)

        def end_thrust(weight_N):
            return [weight_N * 0.5 * share_f / n_per / anp.cos(cant), weight_N * 0.5 * (1.0 - share_f) / n_per / anp.cos(cant)]
        k_int = val(st["control"]["coaxial"], "k_int") if n_per == 2 else 1.0
        self.k_int = k_int
        self.rotors: Dict[str, Any] = {}

        def rotor(name, thrust, v_ax, end, T_est):
            """A lift rotor at one state: shaft speed, thrust and the motor and wire chain.
            T_est (N) is the thrust of the first guess (it scales the thrust equality and starts the shaft speed)."""
            r_out = self.prop("lift", name, thrust, v_ax, T_est, v_ax)
            w = r_out["omega"]
            I = r_out["Q"] * kv_rad + i0
            Vm = w / kv_rad + rm * I
            Pe = Vm * I + (R_e + R_w[end]) * I ** 2
            self.rotors[name] = {"omega": w, "Q": r_out["Q"], "P_shaft": r_out["P_shaft"], "T": r_out["T"],
                                 "I": I, "Vm": Vm, "Pe": Pe, "end": end}
            self.limit("tip_mach_" + name, w * R, hi=val(el, "tip_mach_max") * A0, scale=100.0, group="tw")
            return self.rotors[name]

        W_L = (M - val(mis["payload"], "cargo_kg")) * G0
        states = {}
        for cname, weight, v_ax in (("H_TO", W, 0.0), ("C_TO", W, val(mis["vtol"], "climb_rate_m_s")),
                                    ("H_L", W_L, 0.0), ("MAX", W * val(lim, "thrust_to_weight"), 0.0)):
            ths = end_thrust(weight)
            T_est = self.start("M", 14.8) * G0 / self.N
            T_est *= val(lim, "thrust_to_weight") if cname == "MAX" else (0.96 if cname == "H_L" else 1.0)
            states[cname] = [rotor(f"{cname}_{k}", ths[i], v_ax, i, T_est) for i, k in enumerate(("f", "r"))]
        self.states = states

        def battery_power(rts, Vc):
            Pe = 2.0 * n_per * sum(rt["Pe"] for rt in rts) * k_int + val(el, "avionics_power_W")
            Ib = Pe / (S * Vc)
            return Pe + R_b * Ib ** 2, Ib

        P = {c: battery_power(states[c], V_cell)[0] for c in ("H_TO", "C_TO", "H_L")}
        P_max, I_b_max = battery_power(states["MAX"], V_end)
        self.P, self.P_max = P, P_max

        # ---- MAX: motor torque, current, duty, C-rate
        V_bus = S * V_end - R_b * I_b_max
        for rt, nm in zip(states["MAX"], ("front", "rear")):
            self.limit("motor_torque_" + nm, rt["Q"], hi=q_cap, scale=2.0, group="elec")
            self.limit("motor_current_" + nm, rt["I"], hi=I_pk, scale=50.0, group="elec")
            duty = (rt["omega"] / kv_rad + (rm + R_e + R_w[rt["end"]]) * rt["I"]) / V_bus
            self.limit("duty_" + nm, duty, hi=val(el, "duty_max"), group="elec")
        self.limit("c_rate_max", I_b_max / cap, hi=val(el, "c_rate_max"), scale=10.0, group="elec")
        self.I_b_max, self.V_bus = I_b_max, V_bus
        if "current_A" in ov.get("esc", {}):                       # the ESC of the parts list carries the peak current
            self.limit("esc_current_A", val(bm, "esc_peak_factor") * I_pk, hi=float(ov["esc"]["current_A"]), scale=10.0, group="elec")
        Qh = 0.5 * (states["H_TO"][0]["Q"] + states["H_TO"][1]["Q"])
        Th = W / N / anp.cos(cant)

        # ---- cruise (lift props stopped; the nose prop works)
        S_w, pol = air.s_ref, air.polar
        cda_boom = 2.0 * val(ca, "boom_form_factor") * val(ca, "boom_cf") * (2.0 * math.pi * r_o) * L_boom
        cda_nac = N * val(ca, "nacelle_cda_m2")
        cda_prop = N * val(ca, "stopped_prop_cda_per_r2") * R ** 2
        self.cda = {"boom": cda_boom, "nacelles": cda_nac, "stopped_props": cda_prop}
        cda_extra = cda_boom + cda_nac + cda_prop
        cl_max = pol["cl_max"] * val(ca, "cl_max_usable_factor")
        cp = air.cruise

        def cruise_state(name, V, n2, V0):
            q = 0.5 * RHO0 * V ** 2
            CL2 = (M * G0) ** 2 * n2 / (q * S_w) ** 2
            D_ = q * (S_w * (pol["cd0"] + pol["k"] * CL2) + cda_extra)
            r_out = self.prop("cruise", "cr_" + name, D_, V, 18.0, V0)
            w = r_out["omega"]
            Kv = cp["kv_rad_s_V"]
            I = cp["i0_A"] + r_out["Q"] * Kv
            Vm = w / (cp["kappa"] * Kv) + cp["r_tot_ohm"] * I
            Pe = Vm * I + val(el, "avionics_power_W")
            Ib = Pe / (S * V_cell)
            Pb = Pe + R_b * Ib ** 2
            duty = Vm / (S * V_cell - R_b * Ib)
            self.limit("cruise_duty_" + name, duty, hi=val(el, "duty_max"), group="elec")
            self.limit("cruise_current_" + name, I, hi=cp["imax_A"], scale=10.0, group="elec")
            self.limit("cruise_tip_mach_" + name, w * 0.5 * cp["diameter_m"], hi=0.85 * A0, scale=100.0, group="tw")
            return {"V": V, "drag_N": D_, "omega": w, "P": Pb, "eta_total": r_out["T"] * V / Pb, "CL": anp.sqrt(CL2),
                    "I": I, "thrust": r_out["T"], "Q": r_out["Q"]}

        V_lap = self.var("V_lap", 17.0, 12.0, 30.0, scale=15.0, design=False)
        Vs = anp.sqrt(2.0 * W / (RHO0 * S_w * cl_max))
        self.limit("stall_margin_lap", V_lap, lo=val(ca, "stall_margin") * Vs, scale=10.0, group="energy")
        lap = cruise_state("lap", V_lap, 1.0, self.start("V_lap", 17.0))
        V_map = self.var("V_map", 18.0, 12.0, 40.0, scale=15.0, design=False)
        self.limit("stall_margin_map", V_map, lo=val(ca, "stall_margin") * Vs, scale=10.0, group="energy")
        sv = mis["survey"]
        turn_len = (sv["lines"] - 1) * math.pi * val(ca, "map_turn_radius_m")
        line_len = sv["lines"] * sv["line_length_m"]
        turn_frac = turn_len / (turn_len + line_len)
        n_turn = 1.0 / math.cos(math.radians(sv["turn_bank_deg"]))
        mapc = cruise_state("map", V_map, (1.0 - turn_frac) + turn_frac * n_turn ** 2, self.start("V_map", 18.0))
        self.lap, self.map_state = lap, mapc

        # ---- energy (J)
        trans_t = 2.0 * val(mis["vtol"], "transition_s")
        t_vclimb = mis["vtol"]["climb_m"] / mis["vtol"]["climb_rate_m_s"]
        dh = mis["climb"]["height_m"] - mis["vtol"]["climb_m"]
        t_fclimb = dh / mis["climb"]["rate_m_s"]
        dist = mis["transit_m"] + mis["lap"]["length_m"] * mis["lap"]["count"] + mis["rtl_m"]
        t_map = (line_len + turn_len) / V_map
        t_land = mis["vtol"]["climb_m"] / mis["vtol"]["descent_rate_m_s"]
        self.seg_J = {
            "vtol_takeoff_climb": P["C_TO"] * t_vclimb,
            "transitions": P["H_TO"] * trans_t,
            "fw_climb": lap["P"] * t_fclimb + M * G0 * dh / lap["eta_total"],
            "transit_laps_rtl": lap["P"] * dist / V_lap,
            "survey": mapc["P"] * t_map,
            "deploy_hover": P["H_L"] * mis["deployment_hover_s"],
            "landing": P["H_L"] * t_land,
            "reserve": P["H_L"] * val(lim, "reserve_hover_s"),
        }
        self.t = {"vtol_takeoff_climb": t_vclimb, "transitions": trans_t, "fw_climb": t_fclimb, "transit_laps_rtl": dist / V_lap,
                  "survey": t_map, "deploy_hover": mis["deployment_hover_s"], "landing": t_land, "reserve": val(lim, "reserve_hover_s")}
        self.E_total = sum(self.seg_J.values()) / 3600.0
        self.E_nom = S * V_cell * cap
        self.limit("energy_Wh", self.E_total, hi=val(lim, "battery_usable_fraction") * self.E_nom, scale=100.0, group="energy")

        # ---- structure: each boom end is a cantilever of length a from the clamp
        m_tip = n_per * m_lift_unit
        m_arm = m_boom_each * a / L_boom
        SF, n_g = val(lim, "safety_factor"), val(lim, "load_factor")
        strength = min(val(mat, "tensile_strength_Pa"), val(mat, "compressive_strength_Pa"))
        E_ax = bo["E"]
        r_mid = r_o - 0.5 * t
        sigma_cr = 0.605 * bo["E_c"] * t / r_mid * val(st["material"]["buckling_knockdown"])
        self.struct = []
        for rt, nm in zip(states["MAX"], ("front", "rear")):
            for lc, F in (("T", n_per * rt["T"]), ("g", n_g * G0 * m_tip)):     # T_max, then the 3 g inertia load of the tip mass
                Qe = n_per * rt["Q"]
                Mb = SF * anp.sqrt((F * a + n_g * G0 * m_arm * a / 2.0) ** 2 + Qe ** 2)
                sigma = Mb / I_sec * r_o
                tau = SF * F * val(sc, "mount_offset_m") * r_o / (2.0 * I_sec)
                vm = anp.sqrt(sigma ** 2 + 3.0 * tau ** 2)
                slope = F * a ** 2 / (2.0 * E_ax * I_sec)
                self.limit(f"boom_stress_Pa_{nm}_{lc}", vm, hi=strength, scale=1e8, group="structure")
                self.limit(f"boom_buckling_Pa_{nm}_{lc}", sigma, hi=sigma_cr, scale=1e8, group="structure")
                self.limit(f"boom_tip_slope_deg_{nm}_{lc}", slope * 180.0 / math.pi, hi=val(sc, "tip_slope_max_deg"), group="structure")
                self.struct.append({"F_N": F, "sigma_Pa": sigma, "von_mises_Pa": vm, "slope_deg": slope * 180.0 / math.pi})
        self.limit("boom_r_over_t", r_o / t, hi=val(sc, "r_over_t_max"), scale=10.0, group="structure")
        m_eff = m_tip + 0.236 * m_arm
        self.f1 = anp.sqrt(3.0 * E_ax * I_sec / (a ** 3 * m_eff)) / (2.0 * math.pi)
        self.freq_hover = [states["H_TO"][i]["omega"] / (2.0 * math.pi) for i in (0, 1)]       # 1P at the front and the rear end
        for fh, nm in zip(self.freq_hover, ("front", "rear")):
            self.limit("boom_f1_over_1P_hover_" + nm, self.f1, lo=val(sc, "stiffness_factor") * fh, scale=10.0, group="stiffness")

        # ---- clearances (plan view; the discs lie above the wing plane)
        gap = val(st["rotors"], "tip_clearance_m")
        self.limit("clear_fuselage_m", y_b - R - 0.5 * val(fz, "width_m"), lo=gap, scale=0.01, group="clear")
        self.limit("clear_front_to_wing_LE_m", air.le_x(y_b) - (x_f + R), lo=gap, scale=0.01, group="clear")
        self.limit("clear_rear_to_wing_TE_m", (x_r - R) - air.te_x(y_b), lo=gap, scale=0.01, group="clear")
        self.limit("clear_rear_to_htail_m", air.htail_le_x - (x_r + R), lo=gap, scale=0.01, group="clear")
        self.limit("clear_prop_to_prop_m", 2.0 * a - 2.0 * R, lo=gap, scale=0.01, group="clear")

        # ---- control authority (hover thrust between idle and T_max; handling-quality bandwidth, Froude scaled)
        L_hub = anp.sqrt((2.0 * y_b) ** 2 + (2.0 * a) ** 2)
        w_bw = val(st["control"]["attitude_bandwidth"], "full_scale_rad_s") * anp.sqrt(val(st["control"]["attitude_bandwidth"], "full_scale_length_m") / L_hub)
        alpha_req = val(st["control"], "margin") * w_bw ** 2 * val(st["control"], "attitude_amplitude_rad")
        idle = val(el, "idle_thrust_fraction")
        d_ = 1.0 - idle
        dT = d_ * Th
        M_roll, M_pitch = N * y_b * dT, N * a * dT
        # Yaw: the drag torque difference of the cw and ccw rotors, plus the tilt force. Each rotor tilts about its radial
        # axis (CG to hub), with its sign set by its spin, so the tilts give zero yaw moment in hover and add to the drag
        # torque when the controller changes the thrust (the tilt force is tangential: moment T sin(cant) rho).
        rho_f, rho_r = anp.sqrt(y_b ** 2 + (x_f - x_cg) ** 2), anp.sqrt(y_b ** 2 + (x_r - x_cg) ** 2)
        M_yaw = (N / 2.0) * Qh * ((1.0 + d_) ** 1.5 - (1.0 - d_) ** 1.5) + N * dT * anp.sin(cant) * 0.5 * (rho_f + rho_r)
        self.limit("control_roll_rad_s2", M_roll / Ixx, lo=alpha_req, scale=10.0, group="control")
        self.limit("control_pitch_rad_s2", M_pitch / Iyy, lo=alpha_req, scale=10.0, group="control")
        self.limit("control_yaw_rad_s2", M_yaw / Izz, lo=val(st["control"]["hover_control_power"], "yaw_rad_s2"), scale=10.0, group="control")
        self.ctl = {"alpha_req": alpha_req, "w_bw": w_bw, "L_hub": L_hub, "roll": M_roll / Ixx, "pitch": M_pitch / Iyy, "yaw": M_yaw / Izz}

        # ---- the battery bay
        self.V_bat_L = self.E_nom / val(fz, "battery_Wh_per_L")
        self.limit("bay_volume_L", self.V_bat_L, hi=(bay[1] - bay[0]) * val(fz, "width_m") * val(fz, "height_m") * 0.4 * 1000.0, scale=1.0, group="mass")

        self.boom = bo
        self.names = dict(M=M, m_motor=m_motor, m_prop=m_prop, m_esc=m_esc, m_wire=m_wire, m_batt=m_batt, m_boom=m_boom,
                          rm=rm, i0=i0, I_pk=I_pk, R_b=R_b, Th=Th, Qh=Qh, W=W, share_f=share_f, x_f=x_f, x_r=x_r, x_c=x_c,
                          L_boom=L_boom, V_lap=V_lap, V_map=V_map, Vs=Vs, m_fuse=m_fuse, A_cu=A_cu, R=R, D=D, kv_rad=kv_rad,
                          r_i=r_i, sigma_cr=sigma_cr, L_run_f=L_runs[0], L_run_r=L_runs[1], R_w_f=R_w[0], R_w_r=R_w[1])
        if self.feasibility and self.slacks:
            o.minimize(sum(self.slacks.values()))                      # elastic phase: the sum of the scaled slacks
        else:
            o.minimize(self.E_total / 100.0)
        return self

    # -- solve and read
    def solve(self, verbose=False, max_iter=300, max_runtime=1e20, options=None, attempts=1):
        """IPOPT with the exact Hessian. attempts > 1: a failed attempt hands its last iterate to the next one. The status is in
        self.stats (return_status, iter_count, success, seconds). The last iterate stays available for the report."""
        opts = {"ipopt.mu_strategy": "adaptive", "ipopt.tol": 1e-5, "ipopt.acceptable_tol": 1e-3,
                "ipopt.acceptable_iter": 5, "ipopt.bound_relax_factor": 1e-8}
        opts.update(options or {})
        t0, iters = time.time(), 0
        for k in range(attempts):
            try:
                self.sol = self.opti.solve(verbose=verbose, max_iter=max_iter, max_runtime=max_runtime, options=opts)
                self.error = ""
                st = self.sol.stats()
                self.stats = {"return_status": st.get("return_status"), "iter_count": iters + int(st.get("iter_count", 0)), "success": True}
                break
            except RuntimeError as e:
                self.error = str(e).splitlines()[0]
                self.sol = None
                try:
                    st = self.opti.debug.stats()
                except Exception:
                    st = {}
                iters += int(st.get("iter_count", 0) or 0)
                self.stats = {"return_status": st.get("return_status", "error"), "iter_count": iters, "success": False}
                try:
                    self.opti.set_initial(self.opti.x, self.opti.debug.value(self.opti.x))
                except Exception:
                    break
        self.stats["seconds"] = time.time() - t0
        return self.sol

    def value(self, x):
        if isinstance(x, (int, float)):
            return float(x)
        if self.sol is not None:
            return float(np.ravel(self.sol(x))[0])
        try:
            return float(np.ravel(self.opti.debug.value(x))[0])
        except RuntimeError:                              # the solver stopped before the first iterate: use the start values
            return float(np.ravel(self.opti.value(x, self.opti.initial()))[0])

    def _dual(self, d) -> float:
        """The multiplier of a constraint (0 when the solver gives none: a parametric constraint, or a failed solve)."""
        if d is None:
            return 0.0
        try:
            return float(np.ravel(self.sol.value(d))[0]) if self.sol is not None else float(np.ravel(self.opti.debug.value(d))[0])
        except Exception:
            return 0.0

    def report(self) -> Dict[str, Any]:
        """The numbers of the solution (the last iterate when the solve failed)."""
        g = self.value
        out: Dict[str, Any] = {"config": self.config, "cells_s": self.S, "converged": self.sol is not None, "error": self.error,
                               "design": {k: g(v) for k, v in self.v.items()}, "R_m": g(self.R), "D_m": 2.0 * g(self.R)}
        out["names"] = {k: g(v) for k, v in self.names.items()}
        status_word = _status_word(self)
        out["status_word"] = status_word
        out["ok"] = bool(status_word in OK_STATUS and self.stats.get("return_status") != "Infeasible_Problem_Detected")
        out["c_ref_m"] = float(self.air.c_ref)
        out["boom_z_m"] = float(self.air.tail_boom_z)
        out["rotor_z_m"] = float(self.z_rotor)
        out["spacing_m"] = (float(self.st["rotors"]["coaxial"]["spacing_over_D"]) * 2.0 * g(self.R)) if self.n_per == 2 else None
        out["boom_material"] = {"E_Pa": float(self.boom["E"]), "E_c_Pa": float(self.boom["E_c"]), "rho_kg_m3": float(self.boom["rho"])}
        pr = self.ov.get("prop", {})
        if "pitch_m" in pr:
            out["pitch_m"], out["pitch_note"] = float(pr["pitch_m"]), "input of the parts list"
        else:
            bl = self.st["proptimiser_blade"]
            out["pitch_m"] = float(bl["pitch_m"]) / float(bl["diameter_m"]) * 2.0 * g(self.R)
            out["pitch_note"] = "no pitch given: P/D of the base blade (%s), scaled" % self.st["proptimiser_design"]
        out["names"]["E_Wh"] = g(self.E_total)
        out["level"], out["feasibility_phase"], out["status"] = self.level_name, self.feasibility, dict(self.stats)
        out["constraints"] = {}
        for k, (e, lo, hi) in self.cons.items():
            c = {"value": g(e), "lo": None if lo is None else g(lo), "hi": None if hi is None else g(hi), "group": self.cgroup[k],
                 "enabled": self.cgroup[k] in self.level["groups"], "scale": self.cscale[k]}
            c["equality"] = c["lo"] is not None and c["lo"] == c["hi"]
            c["margin"] = margin(c) if not c["equality"] else -abs(c["value"] - c["lo"]) / max(abs(c["lo"]), 1e-9)
            lam = [abs(self._dual(d)) for d in self.duals.get(k, [])]
            c["dual_scaled"] = float(sum(lam)) if lam else None
            if lam and not self.feasibility:
                c["cost_Wh_per_unit"] = float(sum(lam)) * 100.0 / self.cscale[k]      # the objective is E / 100 Wh
            if k in self.slacks:
                c["slack"] = g(self.slacks[k])
            out["constraints"][k] = c
        out["slacks"] = {k: g(v) for k, v in self.slacks.items()}
        out["energy_Wh"] = {k: g(v) / 3600.0 for k, v in self.seg_J.items()}
        out["energy_total_Wh"], out["energy_nominal_Wh"] = g(self.E_total), g(self.E_nom)
        out["time_s"] = {k: g(v) for k, v in self.t.items()}
        out["inertia_kg_m2"] = {k: g(v) for k, v in zip(("ixx", "iyy", "izz"), self.inertia)}
        out["control"] = {k: g(v) for k, v in self.ctl.items()}
        out["cruise"] = {"lap": {k: g(v) for k, v in self.lap.items()}, "map": {k: g(v) for k, v in self.map_state.items()}}
        out["cda_m2"] = {k: g(v) for k, v in self.cda.items()}
        out["P_battery_W"] = {k: g(v) for k, v in self.P.items()} | {"MAX": g(self.P_max)}
        out["I_battery_max_A"], out["V_bus_max_V"] = g(self.I_b_max), g(self.V_bus)
        out["f1_Hz"], out["f_hover_1P_Hz"] = g(self.f1), max(g(f) for f in self.freq_hover)
        out["structure"] = [{k: g(v) for k, v in d.items()} for d in self.struct]
        out["rotors"] = {n: {"omega_rad_s": g(r["omega"]), "rpm": g(r["omega"]) * 60 / (2 * math.pi), "Q_Nm": g(r["Q"]),
                             "T_N": g(r["T"]), "P_shaft_W": g(r["P_shaft"]), "I_A": g(r["I"]), "Pe_W": g(r["Pe"])}
                         for n, r in self.rotors.items()}
        out["items"] = [{"name": i[0], "mass_kg": g(i[1]), "x": g(i[2]), "y": g(i[3]), "z": g(i[4])} for i in self.items]
        return out


# ======================================================================================================= 5. order sheet
def awg_of(area_m2: float) -> float:
    """The AWG number whose copper area is area_m2 (ASTM B258: d = 0.127 mm 92^((36-n)/39))."""
    d_mm = 2.0 * math.sqrt(area_m2 / math.pi) * 1000.0
    return 36.0 - 39.0 * math.log(d_mm / 0.127) / math.log(92.0)


def margin(c: Dict[str, Any]) -> float:
    """Fractional margin of a constraint: positive means it holds."""
    v, lo, hi = c["value"], c["lo"], c["hi"]
    m = []
    if hi is not None and not isinstance(hi, str):
        m.append((hi - v) / max(abs(hi), 1e-9))
    if lo is not None and not isinstance(lo, str):
        m.append((v - lo) / max(abs(lo), 1e-9))
    return min(m) if m else float("nan")


def indicative_note(rep: Dict[str, Any]) -> str:
    """"INDICATIVE ONLY: solver status <status>" when the solve is not ok, else an empty text. Old result files have no `ok`:
    for them the key `converged` decides."""
    if rep.get("ok", rep.get("converged", True)):
        return ""
    word = rep.get("status_word") or rep.get("ladder_status") or "failed"
    rs = rep["status"].get("return_status") if isinstance(rep.get("status"), dict) else None
    return f"INDICATIVE ONLY: solver status {word}" + (f" ({rs})" if rs else "")


def order_sheet(rep: Dict[str, Any], st: Dict[str, Any]) -> Tuple[str, List[List[str]]]:
    """The order sheet of one result: a markdown text and the rows of a CSV (section, item, value, unit, note)."""
    D_m = rep["D_m"] if "D_m" in rep else rep["D_in"] * 0.0254                    # old result files hold D_in
    d, n, mat = rep["design"], rep["names"], st["material"][st["material"]["design_choice"]]
    rows: List[List[str]] = []

    def row(sec, item, value, unit="", note=""):
        rows.append([sec, item, value if isinstance(value, str) else f"{value:.4g}", unit, note])

    r_o, t = d["r_boom"], d["t_boom"]
    row("boom", "outer diameter", 2000 * r_o, "mm")
    row("boom", "inner diameter", 2000 * (r_o - t), "mm")
    row("boom", "wall", 1000 * t, "mm")
    row("boom", "length each (cut)", 1000 * n["L_boom"], "mm", "quantity 2: one each side of the fuselage")
    row("boom", "material", st["material"]["design_choice"], "", "roll-wrapped carbon tube; E, strength: settings, material block")
    row("boom", "mass each", n["m_boom"] / 2, "kg")
    row("boom", "first bending frequency", rep["f1_Hz"], "Hz", f"hover 1P {rep['f_hover_1P_Hz']:.1f} Hz")
    row("boom", "stress margin (3 g or T_max, SF)", min(rep["constraints"][k]["margin"] for k in rep["constraints"] if k.startswith("boom_stress")), "fraction")
    row("boom", "buckling margin", min(rep["constraints"][k]["margin"] for k in rep["constraints"] if k.startswith("boom_buckling")), "fraction")
    row("boom", "lateral position y (each side)", d["y_b"], "m")
    row("boom", "clamp x (boom centre)", n["x_c"], "m", "design frame, x aft; wing root LE at 0")
    row("boom", "rotor x front / rear", f"{n['x_f']:.3f} / {n['x_r']:.3f}", "m")
    row("motor", "kV", d["kv"], "rpm/V")
    row("motor", "peak torque capacity", d["q_cap"], "N m", "180 s peak, from (Imax - I0)/Kv of the survey")
    row("motor", "peak current needed", n["I_pk"], "A")
    row("motor", "shaft power at T/W 2.5 (each)", max(rep["rotors"]["MAX_f"]["P_shaft_W"], rep["rotors"]["MAX_r"]["P_shaft_W"]), "W")
    row("motor", "mass budget", 1000 * n["m_motor"], "g", "fit on data/motor_survey.csv")
    row("motor", "phase resistance (fit)", 1000 * n["rm"], "mOhm")
    row("motor", "idle current (fit)", n["i0"], "A")
    row("motor", "quantity", str(4 if rep["config"] == "H4" else 8), "")
    bl = st["proptimiser_blade"]
    row("propeller", "diameter", 1000 * D_m, "mm")
    row("propeller", "pitch", 1000 * rep.get("pitch_m", float(bl["pitch_m"]) / float(bl["diameter_m"]) * D_m), "mm",
        rep.get("pitch_note", "P/D of the base blade, scaled") + ". The BEMT model keeps the blade P/D")
    row("propeller", "mass budget (carbon)", 1000 * n["m_prop"], "g", "AIAA 2016-0581 Eq. 5")
    row("propeller", "quantity", str(4 if rep["config"] == "H4" else 8), "",
        "H8: counter-rotating pairs, spacing %.0f mm" % (1000 * (rep.get("spacing_m") or float(st["rotors"]["coaxial"]["spacing_over_D"]) * D_m))
        if rep["config"] == "H8" else "")
    row("esc", "continuous current", st["bershadsky"]["esc_peak_factor"]["value"] * n["I_pk"], "A", "1.2 x the peak current")
    row("esc", "voltage", f"{rep['cells_s']}S", "")
    row("esc", "mass budget", 1000 * n["m_esc"], "g", "AIAA 2016-0581 Eq. 2")
    row("battery", "cells in series", str(rep["cells_s"]), "S")
    row("battery", "capacity", d["cap_Ah"], "Ah", "parallel strings as needed")
    row("battery", "nominal energy", rep["energy_nominal_Wh"], "Wh")
    row("battery", "mass budget", 1000 * n["m_batt"], "g", "AIAA 2016-0581 Eq. 4 times the NXE calibration")
    row("battery", "peak C-rate at T/W 2.5", rep["I_battery_max_A"] / d["cap_Ah"], "C")
    row("battery", "x of the battery centre", d["x_batt"], "m")
    area_mm2 = n["A_cu"] * 1e6
    row("cables", "copper area", area_mm2, "mm2", f"about AWG {awg_of(n['A_cu']):.1f} (silicone), {val(st['electrical'], 'wire_current_density_A_m2') / 1e6:g} A/mm2")
    row("cables", "run length to the front hubs", n["L_run_f"], "m", "battery to hub, one way")
    row("cables", "run length to the rear hubs", n["L_run_r"], "m")
    row("cables", "mass (all)", 1000 * n["m_wire"], "g")
    for nm, r in rep["rotors"].items():
        if nm.startswith("H_TO"):
            row("rotor", f"hover {nm[-1]}: speed / thrust / power", f"{r['rpm']:.0f} rpm / {r['T_N']:.1f} N / {r['P_shaft_W']:.0f} W", "")
    for k, v in rep["energy_Wh"].items():
        row("energy", k, v, "Wh", f"{rep['time_s'][k]:.0f} s")
    row("energy", "total", rep["energy_total_Wh"], "Wh")
    row("mass", "take-off mass", n["M"], "kg", f"limit {val(st['limits'], 'mtow_kg'):g} kg")
    for it in rep["items"]:
        pass
    row("cg", "x_cg", sum(i["mass_kg"] * i["x"] for i in rep["items"]) / n["M"], "m")
    for k, v in rep["inertia_kg_m2"].items():
        row("inertia", k, v, "kg m2")

    note = indicative_note(rep)
    md = [f"**{note}**", ""] if note else []
    md += [f"# Rosella order sheet: {rep['config']} {rep['cells_s']}S", ""]
    if not rep["converged"]:
        md += [f"**NOT CONVERGED**: {rep['error']}. These are the numbers of the last iterate.", ""]
    if rep.get("level_reached") and rep["level_reached"] != "L4":
        md += [f"**Level {rep['level_reached']} result**: the ladder did not reach L4. {rep.get('error', '')}", ""]
    sec = None
    for s_, item, value, unit, rnote in rows:
        if s_ != sec:
            md += ["", f"## {s_}", "", "| item | value | unit | note |", "|---|---|---|---|"]
            sec = s_
        md.append(f"| {item} | {value} | {unit} | {rnote} |")
    ph = rep.get("placeholders") or []
    md += ["", "## stand-ins in the settings", ""] + [f"- {p}" for p in ph]
    if note:
        rows.insert(0, ["status", "indicative only", note, "", ""])
    return "\n".join(md) + "\n", rows


# ======================================================================================================= 6. drivers
def case_name(config: str, cells: int) -> str:
    return f"{config}_{cells}S"


def finish(rep: Dict[str, Any], st, air, motor) -> Dict[str, Any]:
    """Add the settings stand-ins, the motor fit and the airframe numbers to a result."""
    rep["placeholders"] = placeholders(st)
    rep["motor_fit"] = motor.summary()
    rep["airframe"] = {"c_ref_m": air.c_ref, "htail_le_x_m": air.htail_le_x, "neutral_point_m": air.neutral_point, "x_cg_m": air.x_cg, "x_nose_hub_m": air.x_hub, "polar": {
        k: air.polar[k] for k in ("cd0", "k", "cl_max")}}
    return rep


def write_result(rep: Dict[str, Any], st, out_dir: Path, name: str) -> None:
    """The result JSON and the order sheet (markdown and CSV)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    md, rows = order_sheet(rep, st)
    (out_dir / f"{name}_order_sheet.md").write_text(md, encoding="utf-8")
    with (out_dir / f"{name}_order_sheet.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "item", "value", "unit", "note"])
        w.writerows(rows)


def run_case(st, air, motor, config, cells, out_dir: Path, fixed=None, overrides=None, name=None, verbose=False,
             level="L4", init=None) -> Dict[str, Any]:
    """One solve at one level (two attempts), no ladder. Used by `evaluate`."""
    t0 = time.time()
    c = Case(st, air, motor, config, cells, fixed=fixed, overrides=overrides, level=level, init=init).build()
    c.solve(verbose=verbose, attempts=2)
    rep = c.report()
    rep["seconds"] = time.time() - t0
    finish(rep, st, air, motor)
    write_result(rep, st, out_dir, name or case_name(config, cells))
    return rep


# ---------------------------------------------------------------------------------------------------------- the ladder
OK_STATUS = ("ok", "acceptable")


def init_from(rep: Dict[str, Any]) -> Dict[str, float]:
    """Start values for the next level from the report of this one: the design variables, I_pk, V_lap, M and the shaft speed
    of every rotor state (names as in Case.named)."""
    d = {k: float(v) for k, v in rep["design"].items()}
    d["I_pk"], d["V_lap"], d["V_map"], d["M"] = (float(rep["names"][k]) for k in ("I_pk", "V_lap", "V_map", "M"))
    for n, r in rep["rotors"].items():
        d["w_" + n] = float(r["omega_rad_s"])
    for k in ("lap", "map"):
        d["w_cr_" + k] = float(rep["cruise"][k]["omega"])
    return d


def _status_word(c: Case) -> str:
    rs = c.stats.get("return_status", "")
    if c.sol is None:
        return "failed"
    return "ok" if rs == "Solve_Succeeded" else "acceptable"


def solve_level(st, air, motor, config, cells, level, init, fixed=None, overrides=None, verbose=False, max_iter=300,
                max_runtime=1e20) -> Dict[str, Any]:
    """
    One level: the elastic feasibility phase, then the optimality phase from the feasibility point. When the optimality phase
    fails, one retry from the feasibility point with the retry options of settings ladder.ipopt_retry.
    Returns {status, rep, feasibility, iterations, seconds, attempts}. status: ok, acceptable, infeasible or failed.
    """
    lad = st["ladder"]
    t0 = time.time()

    def left():
        return max(max_runtime - (time.time() - t0), 1.0)

    def make(feas, ini):
        return Case(st, air, motor, config, cells, fixed=fixed, overrides=overrides, level=level, feasibility=feas, init=ini).build()

    cf = make(True, init)
    cf.solve(verbose=verbose, max_iter=max_iter, max_runtime=left())
    rf = cf.report()
    total = float(sum(rf["slacks"].values()))
    feas = {"slack_total": total, "slacks": rf["slacks"], "status": cf.stats, "feasible": total <= val(lad, "feasibility_tol")}
    res: Dict[str, Any] = {"feasibility": feas, "iterations": {"feasibility": cf.stats.get("iter_count", 0), "optimality": 0},
                           "attempts": []}
    if not feas["feasible"]:
        res.update(status="infeasible", rep=rf, seconds=time.time() - t0)
        return res
    ini = init_from(rf)
    last = None
    for tag in ("first", "retry"):
        o = lad["ipopt_first" if tag == "first" else "ipopt_retry"]
        co = make(False, ini)
        co.solve(verbose=verbose, max_iter=max_iter, max_runtime=left(),
                 options={"ipopt.mu_init": float(o["mu_init"]), "ipopt.bound_push": float(o["bound_push"]),
                          "ipopt.bound_frac": float(o["bound_push"])})
        res["attempts"].append({"tag": tag, "status": co.stats, "error": co.error})
        res["iterations"]["optimality"] += co.stats.get("iter_count", 0)
        last = co
        if co.sol is not None:
            break
        if time.time() - t0 > max_runtime:
            break
    res["status"] = _status_word(last)
    res["rep"] = last.report()
    res["seconds"] = time.time() - t0
    return res


def worst(rep: Dict[str, Any], n: int = 5) -> List[Tuple[str, float]]:
    """The n enabled constraints with the smallest margin (inequalities only)."""
    rows = [(k, c["margin"]) for k, c in rep["constraints"].items() if c["enabled"] and not c["equality"]]
    return sorted(rows, key=lambda r: r[1])[:n]


def _gap(rep: Dict[str, Any], prev: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if prev is None:
        return None
    f = {"M_kg": lambda r: r["names"]["M"], "E_Wh": lambda r: r["energy_total_Wh"], "D_m": lambda r: r["D_m"],
         "kv": lambda r: r["design"]["kv"]}
    return {k: f[k](rep) - f[k](prev) for k in f}


def random_starts(bounds: Dict[str, Tuple[float, float]], base: Dict[str, float], n: int, seed: int,
                  fixed: Optional[Dict[str, float]] = None) -> List[Dict[str, float]]:
    """The base start and n - 1 random starts inside the bounds of the design variables (fixed seed). Shaft speeds keep the
    start of the base."""
    rng = np.random.default_rng(seed)
    out = [dict(base)]
    for _ in range(max(n - 1, 0)):
        d = dict(base)
        for k, (lo, hi) in bounds.items():
            if not k.startswith("w_") and k not in (fixed or {}):
                d[k] = float(rng.uniform(lo, hi))
        out.append(d)
    return out


def parse_levels(spec: str) -> List[str]:
    """"L0..L4" or "L2" or "L0,L1,L2" -> list of level names."""
    spec = spec.replace(" ", "")
    if ".." in spec:
        a, b = spec.split("..")
        return [f"L{k}" for k in range(int(a[1:]), int(b[1:]) + 1)]
    return spec.split(",")


def ladder(config: str, cells: int, levels: str = "L0..L4", out: Optional[Path] = None, multistart: int = 5, verbose=False,
           time_limit_s: Optional[float] = None, resume: bool = False, st=None, air=None, motor=None, fixed=None,
           overrides=None, max_iter: int = 300, sets: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    The fidelity ladder for one case. Each level has the elastic feasibility phase and the optimality phase and starts from the
    result of the level below. It writes out/<case>/L<k>.json and stops at the first level that fails.
    resume: the first level starts from the L<k-1>.json that is already on disk.
    Returns {"case", "levels": [row, ...], "last_ok": level name or None, "reports": {level: rep}}.
    """
    t_start = time.time()
    st = st or apply_sets(settings(), sets)
    air = air or Airframe(st)
    motor = motor or MotorFit(HERE / "data" / "motor_survey.csv")
    case = case_name(config, cells)
    d = (out or WORK / "ladder") / case
    d.mkdir(parents=True, exist_ok=True)
    lv = parse_levels(levels)
    init: Dict[str, float] = {}
    prev: Optional[Dict[str, Any]] = None
    if resume:
        k0 = int(lv[0][1:])
        if k0 > 0:
            prev = json.loads((d / f"L{k0 - 1}.json").read_text(encoding="utf-8"))
            init = init_from(prev)
    bounds = Case(st, air, motor, config, cells, level="L0", fixed=fixed, overrides=overrides).build().bounds
    rows, reports, last_ok = [], {}, None
    for L in lv:
        t0 = time.time()
        remaining = None if time_limit_s is None else time_limit_s - (time.time() - t_start)
        if remaining is not None and remaining <= 0:
            rows.append({"level": L, "status": "time limit", "seconds": 0.0})
            break
        n_ms = multistart if L in ("L0", "L1") else 1
        starts = random_starts(bounds, init, n_ms, int(val(st["ladder"], "multistart_seed")), fixed)
        best, tried = None, []
        for i, s0 in enumerate(starts):
            try:
                r = solve_level(st, air, motor, config, cells, L, s0, fixed=fixed, overrides=overrides, verbose=verbose,
                                max_iter=max_iter, max_runtime=1e20 if remaining is None else max(remaining - (time.time() - t0), 5.0))
            except RuntimeError as e:                    # a random start that gives NaN at the first point
                tried.append({"start": i, "status": "error", "error": str(e).splitlines()[0]})
                print(f"  [{case} {L}] start {i}: error {str(e).splitlines()[0][:80]}", flush=True)
                continue
            E = r["rep"]["energy_total_Wh"]
            tried.append({"start": i, "status": r["status"], "E_Wh": E, "seconds": r["seconds"],
                          "slack_total": r["feasibility"]["slack_total"]})
            if n_ms > 1:
                print(f"  [{case} {L}] start {i}: {r['status']} E={E:.1f} Wh {r['seconds']:.1f} s", flush=True)
            good = r["status"] in OK_STATUS
            if best is None or (good and (best["status"] not in OK_STATUS or E < best["rep"]["energy_total_Wh"])) or \
                    (not good and best["status"] not in OK_STATUS and r["feasibility"]["slack_total"] < best["feasibility"]["slack_total"]):
                best = r
        if best is None:
            raise RuntimeError(f"{case} {L}: no start could be solved")
        rep = best["rep"]
        rep["converged"] = best["status"] in OK_STATUS
        rep["ladder_status"] = best["status"]
        rep["status_word"], rep["ok"] = best["status"], best["status"] in OK_STATUS
        rep["gap_to_lower_level"] = _gap(rep, prev)
        rep["active"] = [k for k, c in rep["constraints"].items() if c["enabled"] and not c["equality"] and c["margin"] < val(st["ladder"], "active_margin")]
        rep["infeasible"] = [k for k, c in rep["constraints"].items() if c["enabled"] and not c["equality"] and not passes(c)]
        rep["feasibility"] = best["feasibility"]
        rep["iterations"], rep["attempts"], rep["multistart"] = best["iterations"], best["attempts"], tried
        rep["seconds"] = time.time() - t0
        rep["placeholders"] = placeholders(st)
        rep["settings_changed"] = st.get("_changed", [])
        (d / f"{L}.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
        row = {"level": L, "status": best["status"], "seconds": rep["seconds"], "M_kg": rep["names"]["M"], "E_Wh": rep["energy_total_Wh"],
               "D_m": rep["D_m"], "kv": rep["design"]["kv"], "worst": worst(rep), "iterations": best["iterations"],
               "slack_total": best["feasibility"]["slack_total"]}
        if best["status"] == "infeasible":
            row["slack_names"] = sorted(((k, v) for k, v in best["feasibility"]["slacks"].items() if v > 1e-6), key=lambda kv: -kv[1])[:8]
        rows.append(row)
        reports[L] = rep
        print(f"[{case} {L}] {best['status']} {rep['seconds']:.1f} s  M={row['M_kg']:.2f} kg E={row['E_Wh']:.0f} Wh "
              f"D={1000 * row['D_m']:.0f} mm kv={row['kv']:.0f}  iters {best['iterations']}", flush=True)
        if best["status"] not in OK_STATUS:
            break
        last_ok, prev, init = L, rep, init_from(rep)
    print_ladder(case, rows)
    return {"case": case, "levels": rows, "last_ok": last_ok, "reports": reports}


def print_ladder(case: str, rows: List[Dict[str, Any]]) -> None:
    print(f"\nLadder {case}")
    print(f"{'level':5s} {'status':11s} {'s':>7s} {'M kg':>7s} {'E Wh':>7s} {'D mm':>6s} {'kv':>6s}  worst 5 constraints (margin)")
    for r in rows:
        if "M_kg" not in r:
            print(f"{r['level']:5s} {r['status']}")
            continue
        w = ", ".join(f"{k} {m:+.3f}" for k, m in r["worst"])
        print(f"{r['level']:5s} {r['status']:11s} {r['seconds']:7.1f} {r['M_kg']:7.2f} {r['E_Wh']:7.0f} {1000 * r['D_m']:6.0f} {r['kv']:6.0f}  {w}")
        if r.get("slack_names"):
            print("      slack > 0: " + ", ".join(f"{k} {v:.3g}" for k, v in r["slack_names"]))


def optimise(config: Optional[str] = None, cells: Optional[int] = None, out: Optional[Path] = None, verbose=False,
             multistart: int = 5, upto: str = "L4", time_limit_s: Optional[float] = None, sets: Optional[List[str]] = None):
    """The ladder for each case up to `upto`. The result of the highest converged level goes to out/<case>.json with the order sheet."""
    st = apply_sets(settings(), sets)
    air = Airframe(st)
    motor = MotorFit(HERE / "data" / "motor_survey.csv")
    out = out or WORK / "sizing"
    results = {}
    for cfg in ([config] if config else st["configs"]):
        for S in ([cells] if cells else st["cells"]):
            print(f"[{cfg} {S}S] ladder L0 to {upto} ...", flush=True)
            r = ladder(cfg, S, f"L0..{upto}", out=out / "ladder", multistart=multistart, verbose=verbose, time_limit_s=time_limit_s,
                       st=st, air=air, motor=motor)
            if r["last_ok"] is None:
                print(f"[{cfg} {S}S] no level converged")
                continue
            rep = dict(r["reports"][r["last_ok"]])
            rep["level_reached"] = r["last_ok"]
            if r["last_ok"] != upto:
                rep["error"] = f"the ladder stopped above {r['last_ok']}; this is the result of {r['last_ok']}"
            finish(rep, st, air, motor)
            write_result(rep, st, out, case_name(cfg, S))
            results[case_name(cfg, S)] = rep
            print(f"[{cfg} {S}S] result of level {r['last_ok']}: E={rep['energy_total_Wh']:.0f} Wh M={rep['names']['M']:.2f} kg "
                  f"D={1000 * rep['D_m']:.0f} mm", flush=True)
    if results:
        top = {k: v for k, v in results.items() if v["level_reached"] == max(x["level_reached"] for x in results.values())}
        best = min(top, key=lambda k: top[k]["energy_total_Wh"])
        (out / "best.json").write_text(json.dumps({"case": best, "level": top[best]["level_reached"], "result": top[best]}, indent=1),
                                       encoding="utf-8")
        print("best:", best, "level", top[best]["level_reached"])
    else:
        print("no case converged")
    return results


MANUAL = HERE / "settings" / "rosella.manual.json"


def normalise_block(b: Dict[str, Any]) -> Dict[str, Any]:
    """A copy of a block with SI inputs. An old block with inputs.prop_pitch_in gets inputs.prop_pitch_m."""
    b = json.loads(json.dumps(b))
    inp = b.setdefault("inputs", {})
    if "prop_pitch_in" in inp:
        inp.setdefault("prop_pitch_m", inp["prop_pitch_in"] * 0.0254)
        del inp["prop_pitch_in"]
    return b


def load_block(name_or_path: str, file: Optional[Path] = None) -> Dict[str, Any]:
    """A manual block. name_or_path is the path of a JSON file that holds one block, or the name of a block in `file`
    (default settings/rosella.manual.json). Old blocks are converted to SI inputs."""
    p = Path(name_or_path)
    if p.suffix == ".json" and p.is_file():
        d = json.loads(p.read_text(encoding="utf-8"))
        return normalise_block(d if "config" in d else next(iter(d.values())))
    blocks = json.loads(Path(file or MANUAL).read_text(encoding="utf-8"))
    return normalise_block(blocks[name_or_path])


def evaluate_block(block: Dict[str, Any], st: Dict[str, Any], out: Optional[Path] = None, level: str = "L4", name: str = "manual",
                   verbose: bool = False, free: Optional[List[str]] = None, free_x_batt: bool = True, air=None, motor=None) -> Dict[str, Any]:
    """Run the model with the design fixed to a manual block. The block format:
        {"config": "H4", "cells_s": 12, "fixed": {"kv": 150, "q_cap": 2.3, "scale": 1.0, "r_boom": 0.012, ...},
         "overrides": {"motor": {"mass_kg", "rm_ohm", "i0_A"}, "prop": {"mass_kg"}, "esc": {"mass_kg"}, "battery": {"mass_kg"}},
         "free": ["t_boom", "r_boom"],
         "inputs": {"prop_pitch_m", "esc_A", "boom_E_GPa", "boom_rho_kg_m3", ...}}
    free lists the design variables left free (for example the boom, to size it for the chosen parts). It replaces the key
    "free" of the block. x_batt is free too (the CG equality needs it) unless free_x_batt is False. A freed variable starts
    from its fixed value. The notebook and the command line both call this function."""
    block = normalise_block(block)
    inp = block.get("inputs", {})
    free_set = set(block.get("free", []) if free is None else free)
    if free_x_batt:
        free_set.add("x_batt")
    fixed = {k: v for k, v in block.get("fixed", {}).items() if k not in free_set}
    init = {k: float(v) for k, v in block.get("fixed", {}).items() if k in free_set}
    ov = json.loads(json.dumps(block.get("overrides") or {}))
    if "boom_E_GPa" in inp or "boom_rho_kg_m3" in inp:
        ov["boom"] = boom_material(st["material"][st["material"]["design_choice"]], inp.get("boom_E_GPa"), inp.get("boom_rho_kg_m3"))
    if "prop_pitch_m" in inp:
        ov.setdefault("prop", {})["pitch_m"] = float(inp["prop_pitch_m"])
    if "esc_A" in inp:
        ov.setdefault("esc", {})["current_A"] = float(inp["esc_A"])
    air = air or Airframe(st)
    motor = motor or MotorFit(HERE / "data" / "motor_survey.csv")
    rep = run_case(st, air, motor, block["config"], int(block["cells_s"]), out or WORK / "manual", fixed=fixed, overrides=ov,
                   name=name, verbose=verbose, level=level, init=init)
    rep["free"] = sorted(free_set)
    rep["passes"] = {k: passes(v) for k, v in rep["constraints"].items() if v["enabled"]}
    return rep


def evaluate(name: str, out: Optional[Path] = None, verbose=False, level: str = "L4", file: Optional[Path] = None) -> Dict[str, Any]:
    """evaluate_block for the block `name` of settings/rosella.manual.json (or of `file`, or the block file `name`)."""
    nm = Path(name).stem if name.endswith(".json") else name
    return evaluate_block(load_block(name, file), settings(), out, level, name=nm, verbose=verbose)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("optimise")
    o.add_argument("--config")
    o.add_argument("--cells", type=int)
    o.add_argument("--out", type=Path)
    o.add_argument("--upto", default="L4")
    o.add_argument("--multistart", type=int, default=5)
    o.add_argument("--time-limit", type=float, help="seconds for the whole ladder of one case")
    o.add_argument("--set", action="append", dest="sets", help="change a setting for this run, e.g. cruise_aero.map_speed_m_s=19")
    o.add_argument("--verbose", action="store_true")
    e = sub.add_parser("evaluate")
    e.add_argument("name")
    e.add_argument("--level", default="L4")
    e.add_argument("--file", type=Path, help="block file other than settings/rosella.manual.json")
    e.add_argument("--out", type=Path, help="folder for the result JSON and the order sheet (default work/aerosandbox/rosella/manual)")
    e.add_argument("--verbose", action="store_true")
    s = sub.add_parser("order-sheet")
    s.add_argument("--case")
    s.add_argument("--out", type=Path, help="folder for the order sheet (default work/aerosandbox/rosella/order_sheet)")
    la = sub.add_parser("ladder")
    la.add_argument("--config", default="H4")
    la.add_argument("--cells", type=int, default=12)
    la.add_argument("--from", dest="start", default="L0", help="first level; later than L0 starts from the L<k-1>.json on disk")
    la.add_argument("--upto", default="L4")
    la.add_argument("--multistart", type=int, default=5)
    la.add_argument("--out", type=Path)
    la.add_argument("--time-limit", type=float, help="seconds for the whole ladder")
    la.add_argument("--max-iter", type=int, default=300)
    la.add_argument("--set", action="append", dest="sets", help="change a setting for this run, e.g. cruise_aero.map_speed_m_s=19")
    la.add_argument("--verbose", action="store_true")
    sub.add_parser("rotor-check")
    a = ap.parse_args(argv)
    if a.cmd == "optimise":
        optimise(a.config, a.cells, a.out, a.verbose, a.multistart, a.upto, a.time_limit, a.sets)
    elif a.cmd == "ladder":
        ladder(a.config, a.cells, f"{a.start}..{a.upto}", a.out, a.multistart, a.verbose, a.time_limit, resume=a.start != "L0",
               max_iter=a.max_iter, sets=a.sets)
    elif a.cmd == "rotor-check":
        print(json.dumps(rotor_check(settings()), indent=1))
    elif a.cmd == "evaluate":
        rep = evaluate(a.name, a.out, verbose=a.verbose, level=a.level, file=a.file)
        print(f"status {rep['status_word']} ({rep['status'].get('return_status')}), ok {rep['ok']}, M {rep['names']['M']:.3f} kg, "
              f"E {rep['energy_total_Wh']:.1f} Wh, D {1000 * rep['D_m']:.0f} mm")
        if indicative_note(rep):
            print(indicative_note(rep))
        for k, v in rep["constraints"].items():
            if v["enabled"]:
                print(f"{'ok  ' if rep['passes'][k] else 'FAIL'} {k:34s} {v['value']:12.4g}  margin {v['margin']:+.3e}")
    else:
        d = WORK / "sizing"
        f = d / (f"{a.case}.json" if a.case else "best.json")
        rep = json.loads(f.read_text(encoding="utf-8"))
        rep = rep.get("result", rep)
        st = settings()
        md, _ = order_sheet(rep, st)
        out = a.out or WORK / "order_sheet"
        write_result(rep, st, out, a.case or "best")
        print(md)
        print(f"written to {out}")


if __name__ == "__main__":
    main()
