"""The aero model of a multirotor: the body drag, written as DAVE-ML 2.0 (forces only, no moments).

Variables (body axes FRD: x forward, y right, z down; the velocities are those of the body relative to the air)::

    inputs     u, v, w    m/s      air-relative velocity of the body along x, y, z
               n_sum      rev/s    the sum of the rotor speeds (4 rotors: n1 + n2 + n3 + n4, each above 0)
               rho        kg/m^3   air density (default value: ISA sea level, ISO 2533)
    constants  S_ref      m^2      reference area (muas.reference s_ref: the frontal area of the body)
               CDx, CDy, CDz  nd   body drag coefficients on S_ref for a flow along the x, y and z axis
               k_rotor_drag   kg   rotor drag: force per (rev/s of n_sum) per (m/s of velocity)
    outputs    Fx, Fy, Fz  N       aerodynamic force on the body, body axes

    Fx = -0.5 rho S_ref CDx u |u| - k_rotor_drag n_sum u
    Fy = -0.5 rho S_ref CDy v |v| - k_rotor_drag n_sum v
    Fz = -0.5 rho S_ref CDz w |w|

Each force opposes the velocity along its axis. The rotor thrust, its torque and the rotor inflow are NOT in this
model (the propulsion dataset has them). There are no moments: the body is a point at the MRP (the CG) for the drag.
The model has no coupling between the axes and no angle of attack: it is the simplest model that lets a simulator
fly a quadcopter. The coefficients come from `tools/aerosandbox/asb_worker.py` job multirotor_drag.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple

from .aero_buildup import DOCTYPE, MATHML, NS, Coefficient, _apply, _ci, _num, _sub

INPUTS: Tuple[Tuple[str, str, str, str, str, float], ...] = (
    ("u", "bodyVelocityU", "m/s", "body axes FRD", "air-relative velocity of the body along x, positive forward", 0.0),
    ("v", "bodyVelocityV", "m/s", "body axes FRD", "air-relative velocity of the body along y, positive right", 0.0),
    ("w", "bodyVelocityW", "m/s", "body axes FRD", "air-relative velocity of the body along z, positive down", 0.0),
    ("n_sum", "rotorSpeedSum", "rev/s", "none", "sum of the four rotor speeds, each above 0", 0.0),
    ("rho", "airDensity", "kg/m^3", "none", "air density", 1.225))
RHO_SOURCE = "ISA sea level, ISO 2533 (the default value of the input rho)"
OUTPUTS = (("Fx", "bodyForceX", "forward"), ("Fy", "bodyForceY", "right"), ("Fz", "bodyForceZ", "down"))
CONSTANTS = ("S_ref", "CDx", "CDy", "CDz", "k_rotor_drag")
UNITS = {"S_ref": "m^2", "CDx": "nd", "CDy": "nd", "CDz": "nd", "k_rotor_drag": "kg"}


def coefficients(s_ref_m2: float, cd: Dict[str, float], k_rotor_drag_kg: float, sources: Dict[str, Tuple[str, bool]]
                 ) -> Dict[str, Coefficient]:
    """The five constants. `sources` maps each name to (source text, placeholder)."""
    vals = {"S_ref": s_ref_m2, "CDx": cd["CDx"], "CDy": cd["CDy"], "CDz": cd["CDz"], "k_rotor_drag": k_rotor_drag_kg}
    missing = [k for k in CONSTANTS if k not in sources]
    if missing:
        raise ValueError(f"the body-drag model has no source for {missing}")
    return {k: Coefficient(float(vals[k]), UNITS[k], sources[k][0], bool(sources[k][1])) for k in CONSTANTS}


def evaluate(c: Dict[str, Coefficient], x: Dict[str, float]) -> Dict[str, float]:
    """The three forces at one input point (the check cases of the file). Same formula as the MathML below."""
    v = {k: c[k].value for k in CONSTANTS}
    q = 0.5 * x["rho"] * v["S_ref"]
    return {"Fx": -q * v["CDx"] * x["u"] * abs(x["u"]) - v["k_rotor_drag"] * x["n_sum"] * x["u"],
            "Fy": -q * v["CDy"] * x["v"] * abs(x["v"]) - v["k_rotor_drag"] * x["n_sum"] * x["v"],
            "Fz": -q * v["CDz"] * x["w"] * abs(x["w"])}


CHECK_POINTS: Tuple[Tuple[str, Dict[str, float]], ...] = (
    ("rest", {}),
    ("forward", {"u": 10.0, "n_sum": 100.0}),
    ("backward_side", {"u": -4.0, "v": 3.0, "n_sum": 80.0}),
    ("climb_and_descent", {"w": -2.0, "n_sum": 90.0}),
    ("descent", {"w": 3.0, "rho": 1.1}),
    ("all_axes", {"u": 6.0, "v": -5.0, "w": 2.5, "n_sum": 120.0, "rho": 1.2}))


def _cn(parent, value) -> None:
    _sub(parent, "cn", _num(value), ns=MATHML)


def _drag_term(parent, vel: str, cd: str) -> None:
    """0.5 * rho * S_ref * cd * vel * |vel|"""
    t = _apply(parent, "times")
    _cn(t, 0.5)
    for ref in ("rho", "S_ref", cd, vel):
        _ci(t, ref)
    _ci(_apply(t, "abs"), vel)


def to_daveml(c: Dict[str, Coefficient], *, name: str, author: str, org: str, created: str, description: str) -> bytes:
    """The body-drag model with the check cases of CHECK_POINTS (DAVE-ML 2.0, passes the DTD)."""
    if set(c) != set(CONSTANTS):
        raise ValueError(f"the body-drag model needs exactly the constants {CONSTANTS}")
    ET.register_namespace("", NS)
    ET.register_namespace("mathml", MATHML)
    root = ET.Element(f"{{{NS}}}DAVEfunc")
    hdr = _sub(root, "fileHeader", name=name)
    _sub(hdr, "author", name=author, org=org)
    _sub(hdr, "creationDate", date=created)
    _sub(hdr, "fileVersion", "1")
    _sub(hdr, "description", description)
    for var, vname, units, axis, sign, init in INPUTS:
        v = _sub(root, "variableDef", name=vname, varID=var, units=units, axisSystem=axis, sign=sign,
                 initialValue=_num(init))
        if var == "rho":
            _sub(v, "description", f"source: {RHO_SOURCE}; placeholder: false")
        _sub(v, "isInput")
    for k in CONSTANTS:
        co = c[k]
        v = _sub(root, "variableDef", name=k, varID=k, units=co.units, initialValue=_num(co.value))
        _sub(v, "description", f"source: {co.source.replace(';', ',')}; placeholder: {'true' if co.placeholder else 'false'}")
    for var, vname, axis in OUTPUTS:
        v = _sub(root, "variableDef", name=vname, varID=var, units="N", axisSystem="body axes FRD",
                 sign=f"force along {var[1]}, positive {axis}")
        top = _apply(_sub(_sub(v, "calculation"), "math", ns=MATHML), "minus")
        if var == "Fz":
            _drag_term(top, "w", "CDz")
        else:
            vel, cd = ("u", "CDx") if var == "Fx" else ("v", "CDy")
            _drag_term(_apply(top, "plus"), vel, cd)
            plus = list(top)[-1]
            k = _apply(plus, "times")
            for ref in ("k_rotor_drag", "n_sum", vel):
                _ci(k, ref)
        _sub(v, "isOutput")
    cd_ = _sub(root, "checkData")
    zero = {"u": 0.0, "v": 0.0, "w": 0.0, "n_sum": 0.0, "rho": 1.225}
    for cname, over in CHECK_POINTS:
        x = {**zero, **over}
        shot = _sub(cd_, "staticShot", name=cname)
        ins = _sub(shot, "checkInputs")
        for var, *_ in INPUTS:
            sig = _sub(ins, "signal")
            _sub(sig, "varID", var)
            _sub(sig, "signalValue", _num(x[var]))
        outs = _sub(shot, "checkOutputs")
        for var, value in evaluate(c, x).items():
            sig = _sub(outs, "signal")
            _sub(sig, "varID", var)
            _sub(sig, "signalValue", _num(value))
            _sub(sig, "tol", "1e-09")
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    body = body.replace(f' xmlns:mathml="{MATHML}"', "").replace("<mathml:math>", f'<math xmlns="{MATHML}">')
    body = body.replace("<mathml:", "<").replace("</mathml:", "</")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + DOCTYPE + "\n" + body + "\n").encode("utf-8")


def placeholders(c: Dict[str, Coefficient]) -> List[str]:
    return [k for k in CONSTANTS if c[k].placeholder]

