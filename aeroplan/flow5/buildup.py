"""The flow5 sources of the aero build-up (aeroplan.aero_buildup): the T7 stability point, the viscous polar and the
sweep derivatives. The rules are in the aero_buildup module docstring."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from ..aero_buildup import CONTROL, T7_LATERAL, AeroBuildUp, Coefficient, _cl_table
from ..frame import flip_point
from .files import read_t7_scalars


def from_flow5(sweep_dir: Path, viscous: pd.DataFrame, stall: dict) -> AeroBuildUp:
    """Coefficients from the sweep folder, the viscous alpha polar (columns CL, CD) and the stall values."""
    sweep_dir = Path(sweep_dir)
    t7_file = sweep_dir / "t7_reference_opoint.txt"
    op = read_t7_scalars(t7_file)
    res = json.loads((sweep_dir / "results.json").read_text(encoding="utf-8"))
    if not res.get("validation", {}).get("ok"):
        raise ValueError(f"{sweep_dir.name}/results.json: the sweep validation did not pass, so its derivatives are not used")
    t7 = f"flow5 T7 {sweep_dir.name}/{t7_file.name}"
    a0 = math.radians(op["alpha"])
    cl_t, cm_t = op["CL"], op["Cm_inviscid"] + op["Cm_viscous"]
    co: Dict[str, Coefficient] = {}

    def add(k, v, units, src, ph=False):
        co[k] = Coefficient(float(v), units, src, ph)

    cla = -op["CZa"]
    add("CLa", cla, "1_per_rad", f"{t7} (-CZa)")
    add("CL0", cl_t - cla * a0, "nd", f"{t7} (CL_trim - CLa alpha_trim)")
    add("CLq", -op["CZq"], "1_per_rad", f"{t7} (-CZq)")
    add("Cma", op["Cma"], "1_per_rad", t7)
    add("Cmq", op["Cmq"], "1_per_rad", t7)
    add("Cm0", cm_t - op["Cma"] * a0, "nd", f"{t7} (Cm_trim - Cma alpha_trim)")
    for f5, k in T7_LATERAL.items():
        add(k, op[f5], "1_per_rad", f"{t7} ({f5})")

    pts = viscous
    k, cd0 = np.polyfit(pts["CL"].to_numpy() ** 2, pts["CD"].to_numpy(), 1)
    vsrc = f"flow5 viscous alpha polar {sweep_dir.name} ({len(pts)} points, least squares CD on CL^2)"
    add("CD0", cd0, "nd", vsrc)
    add("K", k, "nd", vsrc)

    for key in CONTROL:
        d = res["derivatives"].get(key)
        if d is None:
            raise ValueError(f"{sweep_dir.name}/results.json has no derivative {key}")
        add(key, d["value"], "1_per_rad",
            f"flow5 sweep {res['name']} run {d['run']} (plane {res['plane']}, flow5 {res['flow5']}, linearity {d['linearity']:.4f})")

    ph = bool(stall.get("placeholder", True))
    table = _cl_table(co["CL0"].value, cla, float(stall["CL_max"]), float(stall["CL_min"]))
    table_src = (f"linear CL0 + CLa alpha inside CL_min {stall['CL_min']} to CL_max {stall['CL_max']} (stall settings, "
                 f"placeholder {str(ph).lower()}), post-stall shape of Aerolink 6f7edb7 jsbsim_xml.cl_alpha_table (placeholder)")
    trim = {"speed_mps": op["VInf"], "alpha_rad": a0, "mass_kg": op["mass"],
            "cog": flip_point([op["CoG_x"], op["CoG_y"], op["CoG_z"]]), "NP_x": -op["NP_x"]}   # flow5 axes -> FRD
    notes = [f"Trim point of the T7 analysis: V {op['VInf']} m/s, alpha {op['alpha']} deg, CL {cl_t}.",
             "The T7 point is inviscid. CD0 and K come from the viscous alpha polar instead (M-09)."]
    return AeroBuildUp(co, table, table_src, trim, notes)
