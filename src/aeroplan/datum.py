"""Datum checks of an export package: every geometry source must agree in the one design frame.

The design frame is the flow5 frame: x aft, y right, z up, metres, origin = the flow5 origin. The sources are the CAD
parts (after their hand-config transforms), the flow5 plane XML, the hand values (thrust line, ground contacts, CG),
the T7 point and the contract B file. Each check has a tolerance. A failed check stops the package build.
An `info` row records a value with no second source to compare against.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .adapters.flow5_geometry import Plane
from .muas.reference import ReferenceData

MM = 0.001


@dataclass
class Check:
    name: str
    value: float
    expected: Optional[float]
    tol: Optional[float]
    units: str
    status: str                       # pass, fail or info
    source: str


@dataclass
class DatumReport:
    checks: List[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.status != "fail" for c in self.checks)

    def add(self, name, value, expected, tol, units, source):
        if expected is None:
            status = "info"
        else:
            status = "pass" if abs(value - expected) <= tol else "fail"
        self.checks.append(Check(name, float(value), None if expected is None else float(expected),
                                 None if tol is None else float(tol), units, status, source))

    def text(self) -> str:
        rows = []
        for c in self.checks:
            exp = "" if c.expected is None else f"{c.expected:+.4f} +/- {c.tol:g}"
            rows.append(f"{c.status:4s}  {c.name:44s} {c.value:+.4f} {c.units:4s} {exp}")
        return "\n".join(rows)

    def as_dict(self) -> Dict:
        return {"frame": "design (x aft, y right, z up, m, flow5 origin)", "ok": self.ok,
                "checks": [asdict(c) for c in self.checks]}


def _pts(tri: np.ndarray) -> np.ndarray:
    return tri.reshape(-1, 3)


def _inboard(p: np.ndarray, band: float = 0.05) -> np.ndarray:
    """The vertices within `band` of the innermost span station of a lifting-surface mesh (the root)."""
    ay = np.abs(p[:, 1])
    return p[ay <= ay.min() + band]


def prop_spin(tri: np.ndarray, hub: np.ndarray) -> str:
    """The turn direction seen from behind, from the blade pitch of a tractor propeller (thrust along -x).

    At a station of a blade, the chord line rises from the leading edge (more forward, lower x) to the trailing edge.
    The leading edge moves in the turn direction. A blade that points up (+z) and moves to +y turns clockwise
    seen from behind.
    """
    d = _pts(tri) - hub
    r = np.hypot(d[:, 1], d[:, 2])
    tip = d[r.argmax()]
    u = np.array([0.0, tip[1], tip[2]]) / np.hypot(tip[1], tip[2])
    w = np.cross([-1.0, 0.0, 0.0], u)       # turn direction of a clockwise turn seen from behind (about -x, right hand)
    span = d @ u
    votes = 0.0
    for frac in np.linspace(0.3, 0.8, 11):
        sel = d[np.abs(span - frac * r.max()) < 0.004]
        if len(sel) < 6:
            continue
        x, tg = sel[:, 0], sel @ w
        votes += np.corrcoef(x, tg)[0, 1]
    if votes == 0:
        raise ValueError("no blade section found in the CAD propeller")
    # the leading edge (low x) leads in the turn direction: x falls as tg rises, so a negative correlation is clockwise
    return "cw" if votes < 0 else "ccw"


def datum_checks(cfg: dict, ref: ReferenceData, plane: Plane, design: Dict[str, np.ndarray], prop_diameter_m: float,
                 trim: dict) -> DatumReport:
    rep = DatumReport()
    wing, htail = plane.by_kind("MAINWING"), plane.by_kind("ELEVATOR")

    w = _pts(design["wing"])
    rep.add("wing span (CAD) against b_ref", np.ptp(w[:, 1]), ref.b_ref.value, 5 * MM, "m",
            "raw/cad/wing.stl, reference.json b_ref")
    root = _inboard(w)
    rep.add("wing root leading edge x (CAD) against flow5", root[:, 0].min(), wing.position[0], 10 * MM, "m",
            "raw/cad/wing.stl, flow5 Main Wing position")
    h = _pts(design["htail"])
    hroot = _inboard(h)
    rep.add("htail root leading edge x (CAD) against flow5", hroot[:, 0].min(), htail.position[0], 10 * MM, "m",
            "raw/cad/hstab.stl, flow5 Elevator position")
    rep.add("htail root z (CAD mid) against flow5", (hroot[:, 2].min() + hroot[:, 2].max()) / 2, htail.position[2],
            10 * MM, "m", "raw/cad/hstab.stl, flow5 Elevator position")
    al, ar = _pts(design["aileron_l"]), _pts(design["aileron_r"])
    rep.add("aileron_l mirror of aileron_r (y extent)", al[:, 1].min(), -ar[:, 1].max(), 5 * MM, "m",
            "raw/cad/aileron_l.stl, aileron_r.stl")
    rep.add("aileron_l mirror of aileron_r (x extent)", np.ptp(al[:, 0]), np.ptp(ar[:, 0]), 5 * MM, "m",
            "raw/cad/aileron_l.stl, aileron_r.stl")

    p = cfg["propulsion"]
    hub = np.array([p["thrust_x"], p["thrust_y"], p["thrust_z"]], float)
    pr = _pts(design["propeller"])
    centre = (pr.min(axis=0) + pr.max(axis=0)) / 2
    for i, ax in enumerate("xyz"):
        rep.add(f"propeller hub {ax} (CAD centre) against the thrust line", centre[i], hub[i], 5 * MM, "m",
                "raw/cad/propeller.stl, hand config propulsion.thrust_xyz")
    d_cad = 2 * np.hypot(pr[:, 1] - hub[1], pr[:, 2] - hub[2]).max()
    rep.add("propeller diameter (CAD) against contract B", d_cad, prop_diameter_m, 0.01 * prop_diameter_m, "m",
            "raw/cad/propeller.stl, contract B /propeller diameter_m")
    spin = prop_spin(design["propeller"], hub)
    rep.checks.append(Check("propeller spin (CAD blade pitch) against the hand config", 1.0 if spin == "cw" else -1.0,
                            1.0 if p["spin"] == "cw" else -1.0, 0.0, "cw=1",
                            "pass" if spin == p["spin"] else "fail", f"CAD gives {spin}, hand config propulsion.spin {p['spin']}"))

    g = cfg["ground"]
    gear = _pts(design["gear"])
    rep.add("main wheel contact z against the CAD gear bottom", g["left_main"][2], gear[:, 2].min(), 5 * MM, "m",
            "hand config ground.left_main, raw/cad/gear.stl")
    rep.add("main wheel track (contact y) against the CAD gear", g["right_main"][1] - g["left_main"][1], np.ptp(gear[:, 1]),
            30 * MM, "m", "hand config ground, raw/cad/gear.stl (outer wheel faces)")

    cg = np.array(cfg["mass"]["cg"], float)
    rep.add("MRP against the mass CG (distance)", float(np.linalg.norm(np.array(ref.mrp.point.xyz) - cg)), 0.0, 1e-6, "m",
            "reference.json mrp, hand config mass.cg")
    rep.add("T7 moment point against the mass CG (distance)", float(np.linalg.norm(np.array(trim["cog"]) - cg)), 0.0, 1e-6,
            "m", "flow5 T7 CoG, hand config mass.cg")

    f = _pts(design["fuselage"])
    rep.add("nose x (CAD fuselage front) from the flow5 origin", f[:, 0].min(), None, None, "m",
            "raw/cad/fuselage.stl. The nose datum is this far ahead of the design origin (M-01)")
    rep.add("propeller disc x (CAD front) from the flow5 origin", pr[:, 0].min(), None, None, "m", "raw/cad/propeller.stl")
    rep.add("static margin from the T7 neutral point", (trim["NP_x"] - cg[0]) / ref.c_ref.value, None, None, "nd",
            "flow5 T7 NP_x, hand config mass.cg, reference.json c_ref")
    fin = _pts(design["fin"])
    rd = _pts(design["rudder"])
    rep.add("fin top z (flow5) less the rudder top z (CAD)", fin[:, 2].max() - rd[:, 2].max(), None, None, "m",
            "flow5 Fin wing, raw/cad/rudder.stl")
    b = _pts(design["boom"])
    rep.add("boom x extent (generated)", np.ptp(b[:, 0]), None, None, "m", "the boom part of the package (placeholder)")
    return rep
