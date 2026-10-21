"""The aero build-up of contract C (`dml/aero.dml`): coefficients from flow5, written as DAVE-ML 2.0.

Model (stability axes, per rad, rates non-dimensional with c/2V and b/2V, moments about the MRP = the nominal CG).
The variable names are those of the Aerolink model (Aerolink docs/package_contract.md)::

    CL = CL_basic(alpha) + CLq*qhat + CLde*de          CL_linear = CL0 + CLa*alpha + CLq*qhat + CLde*de
    CD = CD0 + K*CL_linear^2 + CDde*|de|
    CY = CYb*beta + CYp*phat + CYr*rhat + CYdr*dr
    Cl = Clb*beta + Clp*phat + Clr*rhat + Clda*da + Cldr*dr
    Cm = Cm0 + Cma*alpha + Cmq*qhat + Cmde*de
    Cn = Cnb*beta + Cnp*phat + Cnr*rhat + Cnda*da + Cndr*dr

Sources (`coefficients`), the rules of Aerolink 6f7edb7 `model.from_flow5`, except the drag polar:
  - T7 stability point: CLa = -CZa, CLq = -CZq, CL0 = CL_trim - CLa*alpha_trim, Cm0 = Cm_trim - Cma*alpha_trim,
    Cma, Cmq and the lateral derivatives as written (aeronautical signs).
  - CD0 and K: a least-squares line of CD on CL^2 over every point of the viscous alpha polar. The T7 point is
    inviscid (CD_viscous = 0), so its drag has no friction part (decision on missing data M-09).
  - Control derivatives: the `derivatives` of the sweep results.json (JSBSim signs, per rad).
  - CL_basic: linear inside CL_min to CL_max with the post-stall shape of Aerolink 6f7edb7 `jsbsim_xml.cl_alpha_table`.
    CL_min and CL_max are hand-config placeholders.
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from .adapters.flow5_geometry import read_t7_scalars
from .frame import flip_point

NS, MATHML = "http://daveml.org/2010/DAVEML", "http://www.w3.org/1998/Math/MathML"
DOCTYPE = ('<!DOCTYPE DAVEfunc PUBLIC "-//AIAA//DTD for Flight Dynamic Models - Functions 2.0//EN" '
           '"http://daveml.org/DTDs/2p0/DAVEfunc.dtd">')
INPUTS = (("alpha", "angleOfAttack", "rad", "stability axes", "positive nose up relative to the air"),
          ("beta", "angleOfSideslip", "rad", "stability axes", "positive with the air from the right"),
          ("phat", "rollRateNondim", "nd", "body axes", "p b / (2 V), positive right wing down"),
          ("qhat", "pitchRateNondim", "nd", "body axes", "q c / (2 V), positive nose up"),
          ("rhat", "yawRateNondim", "nd", "body axes", "r b / (2 V), positive nose right"),
          ("de", "elevatorDeflection", "rad", "none", "positive trailing edge down (JSBSim)"),
          ("da", "aileronDeflection", "rad", "none", "positive rolls right (JSBSim)"),
          ("dr", "rudderDeflection", "rad", "none", "positive trailing edge left (JSBSim)"))
OUTPUTS = (("CL", "liftCoefficient", [("_table", None), ("CLq", "qhat"), ("CLde", "de")]),
           ("CL_linear", "liftCoefficientLinear", [("CL0", None), ("CLa", "alpha"), ("CLq", "qhat"), ("CLde", "de")]),
           ("CD", "dragCoefficient", [("CD0", None), ("K", "CL_linear^2"), ("CDde", "|de|")]),
           ("CY", "sideForceCoefficient", [("CYb", "beta"), ("CYp", "phat"), ("CYr", "rhat"), ("CYdr", "dr")]),
           ("Cl", "rollMomentCoefficient", [("Clb", "beta"), ("Clp", "phat"), ("Clr", "rhat"), ("Clda", "da"), ("Cldr", "dr")]),
           ("Cm", "pitchMomentCoefficient", [("Cm0", None), ("Cma", "alpha"), ("Cmq", "qhat"), ("Cmde", "de")]),
           ("Cn", "yawMomentCoefficient", [("Cnb", "beta"), ("Cnp", "phat"), ("Cnr", "rhat"), ("Cnda", "da"), ("Cndr", "dr")]))
AXIS = ("CL", "CD", "CY", "Cl", "Cm", "Cn")
NONDIM = ("CL0", "CD0", "K", "Cm0")
CONTROL = ("CLde", "CDde", "Cmde", "Clda", "Cnda", "CYdr", "Cldr", "Cndr")
T7_LATERAL = {"Cyb": "CYb", "Clb": "Clb", "Cnb": "Cnb", "Cyp": "CYp", "Clp": "Clp", "Cnp": "Cnp",
              "Cyr": "CYr", "Clr": "Clr", "Cnr": "Cnr"}


@dataclass(frozen=True)
class Coefficient:
    value: float
    units: str
    source: str
    placeholder: bool = False


@dataclass
class AeroBuildUp:
    coefs: Dict[str, Coefficient]
    cl_table: List[Tuple[float, float]]          # (alpha rad, CL_basic)
    cl_table_source: str
    trim: Dict[str, float]                       # the T7 point: speed, alpha, CoG, mass
    notes: List[str]


def _cl_table(cl0: float, cla: float, cl_max: float, cl_min: float) -> List[Tuple[float, float]]:
    """Aerolink 6f7edb7 jsbsim_xml.cl_alpha_table: linear to the stall, a drop after it, a flat-plate-like tail."""
    a_max, a_min, d10 = (cl_max - cl0) / cla, (cl_min - cl0) / cla, math.radians(10)
    pts = [(math.radians(-90), 0.0), (a_min - 2 * d10, 0.6 * cl_min), (a_min, cl_min), (a_max, cl_max),
           (a_max + d10, 0.75 * cl_max), (math.radians(45), 0.9), (math.radians(90), 0.0)]
    pts = sorted(pts)
    if any(b[0] <= a[0] for a, b in zip(pts, pts[1:])):
        raise ValueError("CL_basic breakpoints are not strictly rising: check CL_min, CL_max, CL0 and CLa")
    return pts


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


# ---------------------------------------------------------------------------------------------------------- DAVE-ML
def _num(x: float) -> str:
    return format(float(x), ".17g")


def _sub(parent, tag, text=None, ns=NS, **attrib):
    e = ET.SubElement(parent, f"{{{ns}}}{tag}", {k: str(v) for k, v in attrib.items() if v is not None})
    if text is not None:
        e.text = text
    return e


def _apply(parent, op):
    a = _sub(parent, "apply", ns=MATHML)
    _sub(a, op, ns=MATHML)
    return a


def _ci(parent, var):
    _sub(parent, "ci", var, ns=MATHML)


def _term(parent, coef, var):
    if var is None:
        _ci(parent, coef)
        return
    t = _apply(parent, "times")
    _ci(t, coef)
    if var.endswith("^2"):
        p = _apply(t, "power")
        _ci(p, var[:-2])
        _sub(p, "cn", "2", ns=MATHML)
    elif var.startswith("|"):
        _ci(_apply(t, "abs"), var.strip("|"))
    else:
        _ci(t, var)


def evaluate(b: AeroBuildUp, x: Dict[str, float]) -> Dict[str, float]:
    """The six outputs of the build-up at one input point (the check-cases of the file)."""
    c = {k: v.value for k, v in b.coefs.items()}
    a, cl = np.array(b.cl_table).T
    cl_lin = c["CL0"] + c["CLa"] * x["alpha"] + c["CLq"] * x["qhat"] + c["CLde"] * x["de"]
    return {"CL": float(np.interp(x["alpha"], a, cl)) + c["CLq"] * x["qhat"] + c["CLde"] * x["de"],
            "CD": c["CD0"] + c["K"] * cl_lin**2 + c["CDde"] * abs(x["de"]),
            "CY": c["CYb"] * x["beta"] + c["CYp"] * x["phat"] + c["CYr"] * x["rhat"] + c["CYdr"] * x["dr"],
            "Cl": c["Clb"] * x["beta"] + c["Clp"] * x["phat"] + c["Clr"] * x["rhat"] + c["Clda"] * x["da"] + c["Cldr"] * x["dr"],
            "Cm": c["Cm0"] + c["Cma"] * x["alpha"] + c["Cmq"] * x["qhat"] + c["Cmde"] * x["de"],
            "Cn": c["Cnb"] * x["beta"] + c["Cnp"] * x["phat"] + c["Cnr"] * x["rhat"] + c["Cnda"] * x["da"] + c["Cndr"] * x["dr"]}


CHECK_POINTS = (("trim", {"alpha": "trim"}), ("alpha_elevator", {"alpha": 0.08, "qhat": 0.01, "de": -0.09}),
                ("sideslip_rudder", {"alpha": 0.05, "beta": 0.09, "rhat": 0.02, "dr": 0.07}),
                ("roll_aileron", {"alpha": 0.06, "phat": 0.03, "da": 0.12}))


def to_daveml(b: AeroBuildUp, *, name: str, author: str, org: str, created: str, description: str) -> bytes:
    """dml/aero.dml with the Aerolink variable names and the check-cases of CHECK_POINTS."""
    missing = [k for _, _, terms in OUTPUTS for k, _ in terms if k != "_table" and k not in b.coefs]
    if missing:
        raise ValueError(f"the build-up lacks {sorted(set(missing))}")
    ET.register_namespace("", NS)
    ET.register_namespace("mathml", MATHML)
    root = ET.Element(f"{{{NS}}}DAVEfunc")
    hdr = _sub(root, "fileHeader", name=name)
    _sub(hdr, "author", name=author, org=org)
    _sub(hdr, "creationDate", date=created)
    _sub(hdr, "fileVersion", "1")
    _sub(hdr, "description", description)
    for var, vname, units, axis, sign in INPUTS:
        v = _sub(root, "variableDef", name=vname, varID=var, units=units, axisSystem=axis, sign=sign, initialValue="0")
        _sub(v, "isInput")
    for k in sorted(b.coefs):
        c = b.coefs[k]
        v = _sub(root, "variableDef", name=k, varID=k, units=c.units, initialValue=_num(c.value))
        _sub(v, "description", f"source: {c.source.replace(';', ',')}; placeholder: {'true' if c.placeholder else 'false'}")
    _sub(root, "variableDef", name="liftCoefficientBasic", varID="CL_basic", units="nd")
    for var, vname, terms in OUTPUTS:
        v = _sub(root, "variableDef", name=vname, varID=var, units="nd", axisSystem="stability axes")
        s = _apply(_sub(_sub(v, "calculation"), "math", ns=MATHML), "plus")
        for coef, inp in terms:
            _ci(s, "CL_basic") if coef == "_table" else _term(s, coef, inp)
        if var in AXIS:
            _sub(v, "isOutput")
    bp = _sub(root, "breakpointDef", name="alpha breakpoints", bpID="BP_ALPHA", units="rad")
    _sub(bp, "bpVals", ", ".join(_num(a) for a, _ in b.cl_table))
    g = _sub(root, "griddedTableDef", name="basic lift coefficient", gtID="GT_CL_BASIC", units="nd")
    _sub(g, "description", f"source: {b.cl_table_source.replace(';', ',')}; placeholder: true")
    _sub(_sub(g, "breakpointRefs"), "bpRef", bpID="BP_ALPHA")
    _sub(g, "dataTable", ", ".join(_num(cl) for _, cl in b.cl_table))
    f = _sub(root, "function", name="basicLiftCoefficient")
    _sub(f, "independentVarRef", varID="alpha", min=_num(b.cl_table[0][0]), max=_num(b.cl_table[-1][0]),
         extrapolate="neither", interpolate="linear")
    _sub(f, "dependentVarRef", varID="CL_basic")
    _sub(_sub(f, "functionDefn", name="basic lift table"), "griddedTableRef", gtID="GT_CL_BASIC")
    cd = _sub(root, "checkData")
    zero = {k: 0.0 for k, *_ in INPUTS}
    for cname, over in CHECK_POINTS:
        x = dict(zero, **{k: (b.trim["alpha_rad"] if v == "trim" else v) for k, v in over.items()})
        shot = _sub(cd, "staticShot", name=cname)
        ins = _sub(shot, "checkInputs")
        for var, *_ in INPUTS:
            sig = _sub(ins, "signal")
            _sub(sig, "varID", var)
            _sub(sig, "signalValue", _num(x[var]))
        outs = _sub(shot, "checkOutputs")
        for var, value in evaluate(b, x).items():
            sig = _sub(outs, "signal")
            _sub(sig, "varID", var)
            _sub(sig, "signalValue", _num(value))
            _sub(sig, "tol", "1e-09")
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    body = body.replace(f' xmlns:mathml="{MATHML}"', "").replace("<mathml:math>", f'<math xmlns="{MATHML}">')
    body = body.replace("<mathml:", "<").replace("</mathml:", "</")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + DOCTYPE + "\n" + body + "\n").encode("utf-8")
