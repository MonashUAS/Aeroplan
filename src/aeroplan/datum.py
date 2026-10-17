"""Datum checks of the ADH document: every geometry source must agree in the one design frame.

The design frame is the flow5 frame: x aft, y right, z up, metres, origin = the flow5 origin. The sources are the
flow5 planforms, the reference dimensions, the mass model, the propeller installation, the ground contacts, the
contract B propeller and, when they are on this machine, the CAD meshes of the CREO spoke. Each check has a
tolerance. A failed check stops the build. An `info` row records a value with no second source to compare against.
A `warn` row does not stop the build. It asks for an action (for example a new flow5 sweep after an OpenVSP change).
A CAD check is left out when the CAD mesh is not on this machine. An info row says so.

A multirotor (`muas.reference.kind` multirotor) has no wing, tail or cruise propeller: those checks are left out
(they look for `wing_main`, `htail` and `prop_cruise` and find none). Its checks are the hub symmetry, the clearance
between adjacent rotor discs and MRP = mass CG within 1 mm.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

MM = 0.001


@dataclass
class Check:
    name: str
    value: float
    expected: Optional[float]
    tol: Optional[float]
    units: str
    status: str                       # pass, fail, info or warn
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

    def warn(self, name: str, source: str) -> None:
        """A row that does not stop the build but asks for an action."""
        self.checks.append(Check(name, 0.0, None, None, "-", "warn", source))

    def text(self) -> str:
        rows = []
        for c in self.checks:
            if c.status == "warn":
                rows.append(f"warn  {c.name}: {c.source}")
                continue
            exp = "" if c.expected is None else f"{c.expected:+.4f} +/- {c.tol:g}"
            rows.append(f"{c.status:4s}  {c.name:52s} {c.value:+.4f} {c.units:4s} {exp}")
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


def _get(doc, inst):
    from . import adh_doc

    try:
        return adh_doc.find(doc, inst)
    except KeyError:
        return None


def _surface_checks(rep: DatumReport, air: Dict, pf: Optional[Dict]) -> None:
    from .geometry import planform_reference

    am = air.get("muas") or {}
    ref = am.get("reference")
    if not pf:
        return
    pr = planform_reference(pf)
    if ref:
        rep.add("b_ref against the main wing planform span", ref["b_ref"]["value"], pr["span_m"], 5 * MM, "m",
                "muas.reference b_ref, wing_main planform")
        rep.add("S_ref against the main wing planform area", ref["s_ref"]["value"], pr["area_m2"],
                0.005 * pr["area_m2"], "m^2", "muas.reference s_ref, wing_main planform (flat)")
        rep.add("c_ref against the main wing mean aerodynamic chord", ref["c_ref"]["value"], pr["mac_m"],
                0.01 * pr["mac_m"], "m", "muas.reference c_ref, wing_main planform")
    for perf in air.get("performance") or []:
        if perf.get("name") != "sizing" or perf["tools"][0]["data_exchange"].get("model_identifier") != "athena":
            continue                  # only the Athena printout has the wing area, span and m_total to compare
        outs = {o["name"]: o["value"] for o in perf["tools"][0]["data_exchange"]["outputs"]}
        rep.add("wing area: initial sizing (Athena) less flow5", outs["Wing area"] - pr["area_m2"], None, None, "m^2",
                "sizing output Wing area, wing_main planform")
        rep.add("wing span: initial sizing (Athena) less flow5", outs["Wing span"] - pr["span_m"], None, None, "m",
                "sizing output Wing span, wing_main planform")
        if "mass_properties" in am:
            rep.add("mass: initial sizing (Athena) less the mass model",
                    outs["m_total"] - am["mass_properties"]["mass"]["value"], None, None, "kg",
                    "sizing output m_total, muas.mass_properties")


def _mirror_error(hubs: np.ndarray, flip: np.ndarray) -> float:
    """The largest distance from a hub, mirrored by `flip`, to the nearest hub (0 when the hubs are symmetric)."""
    return float(max(np.linalg.norm(hubs - h * flip, axis=1).min() for h in hubs))


def _multirotor_checks(rep: DatumReport, doc: Dict) -> None:
    """Hub symmetry and the clearance between rotor discs of the lift rotors (looked up by role, no instance name)."""
    from . import adh_doc

    rot = [(item["muas"]["instance"], item["muas"]["propeller"]) for _, item, _ in adh_doc.iter_nodes(doc)
           if ((item.get("muas") or {}).get("propeller") or {}).get("role") == "lift"]
    if not rot:
        return
    hubs = np.array([p["hub"]["xyz"] for _, p in rot], float)
    src = "lift rotors muas.propeller hub"
    rep.add("hub symmetry: mirror y (largest gap to a hub)", _mirror_error(hubs, np.array([1.0, -1.0, 1.0])), 0.0, MM,
            "m", src)
    rep.add("hub symmetry: mirror x (largest gap to a hub)", _mirror_error(hubs, np.array([-1.0, 1.0, 1.0])), 0.0, MM,
            "m", src)
    gaps = {}
    for i in range(len(rot)):
        for j in range(i + 1, len(rot)):
            d_in_plane = float(np.linalg.norm(hubs[i, :2] - hubs[j, :2]))
            gap = d_in_plane - 0.5 * (rot[i][1]["diameter"]["value"] + rot[j][1]["diameter"]["value"])
            gaps[(rot[i][0], rot[j][0])] = gap
    worst = min(gaps, key=gaps.get)
    rep.checks.append(Check("rotor tip clearance, smallest gap between two discs", gaps[worst], None, None, "m",
                            "pass" if gaps[worst] > 0 else "fail",
                            f"{worst[0]} and {worst[1]}: hub distance less the disc radii (must be above 0)"))
    seen = set()
    for (a, b), g in sorted(gaps.items(), key=lambda kv: kv[1]):
        if round(g, 6) in seen:
            continue
        seen.add(round(g, 6))
        rep.add(f"rotor tip clearance {a} to {b}", g, None, None, "m", "hub distance less the disc radii")


def _origin_check(rep: DatumReport, doc: Dict, pf: Optional[Dict]) -> None:
    """ADR 0023: the design frame starts at the root leading edge of `wing_main`. A wing at x other than 0 fails."""
    from .consumers import vehicle_kind

    if pf is None:
        why = ("a multirotor has no main wing, ADR 0018 applies" if vehicle_kind(doc) == "multirotor" else
               "no wing_main: a published reference model (units_system as-source) or an aircraft with no main wing")
        rep.add("origin: skipped (ADR 0023)", 0.0, None, None, "-", why)
        return
    x_le = pf["position"]["xyz"][0] + pf["sections"][0]["x_offset"]
    rep.add("origin: main wing root LE x (ADR 0023)", x_le, 0.0, MM, "m",
            "wing_main planform position + first section x_offset; the origin is the wing root LE")


def datum_checks(doc: Dict, root) -> DatumReport:
    from . import adh_doc
    from .consumers import MRP_CG_TOL_M, vehicle_kind
    from .parts import part_meshes

    rep = DatumReport()
    air = adh_doc.node(doc, "1.2") if adh_doc.has_node(doc, "1.2") else {}
    am = air.get("muas") or {}
    ref = am.get("reference")
    wing = _get(doc, "wing_main")
    pf = (wing or {}).get("muas", {}).get("planform")
    _origin_check(rep, doc, pf)
    _surface_checks(rep, air, pf)

    mp = am.get("mass_properties")
    if ref and mp:
        cg = np.array(mp["cg"]["xyz"], float)
        gap = float(np.linalg.norm(np.array(ref["mrp"]["point"]["xyz"]) - cg))
        if vehicle_kind(doc) == "multirotor":
            rep.add("MRP against the mass CG (distance)", gap, 0.0, MRP_CG_TOL_M, "m",
                    "muas.reference mrp, muas.mass_properties cg (a multirotor needs 1 mm)")
        elif any(r.get("tool") == "SpecSheet" for r in am.get("sources") or []) and gap > 1e-6:
            rep.warn("MRP differs from the mass CG by %.1f mm: the aero model is about the old MRP" % (gap * 1000),
                     "run `aeroplan generate flow5` for the mass model of the SpecSheet spoke, run a new flow5 sweep, "
                     "then build")
        else:
            rep.add("MRP against the mass CG (distance)", gap, 0.0, 1e-6, "m", "muas.reference mrp, muas.mass_properties cg")
        if pf:
            x_le = pf["position"]["xyz"][0] + pf["sections"][0]["x_offset"]
            rep.add("mass CG: x behind the main wing root leading edge, in % c_ref",
                    (cg[0] - x_le) / ref["c_ref"]["value"] * 100.0, None, None, "%",
                    "muas.mass_properties cg, wing_main planform, muas.reference c_ref")
        parts = [item["muas"]["mass_properties"]["mass"]["value"] for _, item, _ in adh_doc.iter_nodes(doc)
                 if (item.get("muas") or {}).get("mass_properties") and item["muas"].get("instance") != am.get("instance")]
        if parts:
            rep.add("mass: sum of the subassembly masses less the air vehicle mass", sum(parts) - mp["mass"]["value"],
                    0.0, 1e-6, "kg", "muas.mass_properties of the subassemblies, node 1.2")

    if vehicle_kind(doc) == "multirotor":
        _multirotor_checks(rep, doc)
    ps = part_meshes(doc, root)
    for n in ps.notes:
        rep.add("view part note", 0.0, None, None, "-", n)
    P = {k: _pts(p.tri) for k, p in ps.parts.items() if not p.source.startswith(("full lifting", "body lofted"))}
    htail = _get(doc, "htail")
    hpf = (htail or {}).get("muas", {}).get("planform")
    if "wing" in P and ref:
        w = P["wing"]
        rep.add("wing span (CAD) against b_ref", np.ptp(w[:, 1]), ref["b_ref"]["value"], 5 * MM, "m",
                "CAD wing, muas.reference b_ref")
        if pf:
            rep.add("wing root leading edge x (CAD) against flow5", _inboard(w)[:, 0].min(), pf["position"]["xyz"][0],
                    10 * MM, "m", "CAD wing, wing_main planform position")
    if "htail" in P and hpf:
        hroot = _inboard(P["htail"])
        rep.add("htail root leading edge x (CAD) against flow5", hroot[:, 0].min(), hpf["position"]["xyz"][0], 10 * MM,
                "m", "CAD htail, htail planform position")
        rep.add("htail root z (CAD mid) against flow5", (hroot[:, 2].min() + hroot[:, 2].max()) / 2,
                hpf["position"]["xyz"][2], 10 * MM, "m", "CAD htail, htail planform position")
    if "aileron_l" in P and "aileron_r" in P:
        al, ar = P["aileron_l"], P["aileron_r"]
        rep.add("aileron_l mirror of aileron_r (y extent)", al[:, 1].min(), -ar[:, 1].max(), 5 * MM, "m", "CAD ailerons")
        rep.add("aileron_l mirror of aileron_r (x extent)", np.ptp(al[:, 0]), np.ptp(ar[:, 0]), 5 * MM, "m", "CAD ailerons")

    prop = _get(doc, "prop_cruise")
    pm = (prop or {}).get("muas", {})
    inst, psys = pm.get("propeller"), pm.get("propulsion_system")
    if inst and psys:
        rep.add("propeller diameter (installation) against contract B", inst["diameter"]["value"],
                psys["diameter"]["value"], 1e-9, "m", "prop_cruise muas.propeller, muas.propulsion_system")
    if inst and "propeller" in P:
        hub = np.array(inst["hub"]["xyz"], float)
        pr_ = P["propeller"]
        centre = (pr_.min(axis=0) + pr_.max(axis=0)) / 2
        for i, ax in enumerate("xyz"):
            rep.add(f"propeller hub {ax} (CAD centre) against the installation", centre[i], hub[i], 5 * MM, "m",
                    "CAD propeller, prop_cruise muas.propeller hub")
        d_cad = 2 * np.hypot(pr_[:, 1] - hub[1], pr_[:, 2] - hub[2]).max()
        rep.add("propeller diameter (CAD) against the installation", d_cad, inst["diameter"]["value"],
                0.01 * inst["diameter"]["value"], "m", "CAD propeller, prop_cruise muas.propeller diameter")
        spin = prop_spin(ps.parts["propeller"].tri, hub)
        rep.checks.append(Check("propeller spin (CAD blade pitch) against the installation", 1.0 if spin == "cw" else -1.0,
                                1.0 if inst["spin"] == "cw" else -1.0, 0.0, "cw=1",
                                "pass" if spin == inst["spin"] else "fail",
                                f"CAD gives {spin}, prop_cruise muas.propeller spin {inst['spin']}"))
    frame = _get(doc, "airframe")
    gc = {c["name"]: c for c in (frame or {}).get("muas", {}).get("ground_contacts") or []}
    if "gear" in P and "LEFT_MAIN" in gc:
        gear = P["gear"]
        lm, rm = gc["LEFT_MAIN"]["position"]["xyz"], gc["RIGHT_MAIN"]["position"]["xyz"]
        rep.add("main wheel contact z against the CAD gear bottom", lm[2], gear[:, 2].min(), 5 * MM, "m",
                "airframe ground contact LEFT_MAIN, CAD gear")
        rep.add("main wheel track (contact y) against the CAD gear", rm[1] - lm[1], np.ptp(gear[:, 1]), 30 * MM, "m",
                "airframe ground contacts, CAD gear (outer wheel faces)")
    if "fuselage" in P:
        rep.add("nose x (CAD fuselage front) from the flow5 origin", P["fuselage"][:, 0].min(), None, None, "m",
                "CAD fuselage. The nose is this far ahead of the design origin")
    _skin_checks(rep, doc, root)
    _geometry_age(rep, doc, air)
    _stale_assets(rep, doc)
    return rep


def _skin_checks(rep: DatumReport, doc: Dict, root) -> None:
    """The gap from the ADH body frames to the CAD outer skin (info: the body is a fit of the skin)."""
    from . import adh_doc
    from .geometry import body_frames, distance_to_mesh
    from .parts import mesh_name, skin_mesh

    for _, item, _ in adh_doc.iter_nodes(doc):
        m = item.get("muas") or {}
        if not m.get("skin"):
            continue
        tri = skin_mesh(doc, item, root)
        if tri is None:
            rep.add("view part note", 0.0, None, None, "-",
                    f"{m['instance']}: skin {mesh_name(doc, m['skin']['mesh'])} is not on this machine (or changed): no skin check")
            continue
        body = (item.get("geometry") or {}).get("body")
        if not body:
            continue
        d = distance_to_mesh(np.vstack(body_frames(body)), tri)
        src = f"{m['instance']} geometry.body frames, skin {mesh_name(doc, m['skin']['mesh'])}"
        rep.add(f"{m['instance']} body frames to the CAD skin: largest gap", float(d.max()), None, None, "m", src)
        rep.add(f"{m['instance']} body frames to the CAD skin: RMS gap", float(np.sqrt(np.mean(d ** 2))), None, None,
                "m", src)


def _geometry_age(rep: DatumReport, doc: Dict, air: Dict) -> None:
    """A warn row for each item whose geometry comes from another spoke than the aero model (flow5)."""
    from . import adh_doc, assets

    aero = assets.item_dataset(air, "aero") if air else None
    if aero is None:
        return
    try:
        e = assets.entry(doc, aero["ref"].partition("#")[0])
        built = e.get("built_against") or e["name"]
    except assets.AssetError:
        built = "?"
    for _, item, _ in adh_doc.iter_nodes(doc):
        m = item.get("muas") or {}
        tool = m.get("geometry_tool")
        if tool and tool != "flow5":
            rep.warn(f"{m['instance']}: aero model is older than the geometry",
                     f"the aero model ({built}) comes from flow5, the geometry of {m['instance']} comes from "
                     f"{tool}. Run a new flow5 sweep")


def _stale_assets(rep: DatumReport, doc: Dict) -> None:
    """Every item reference must name an asset of the register. A derived asset whose input left the register is
    stale (for example an aero model made from CAD or geometry files that changed since): a warn row."""
    from . import assets

    reg = {e["id"]: e for e in assets.register(doc, create=False)}
    missing = sorted(set(assets.referenced(doc)) - set(reg) - {
        d for e in reg.values() for d in e.get("derived_from") or []})
    for aid in missing:
        rep.checks.append(Check("asset reference", 1.0, 0.0, 0.0, "-", "fail",
                                f"{aid} is named by an item but is not in the register (1.10.2)"))
    for e in reg.values():
        gone = [d for d in e.get("derived_from") or [] if d not in reg]
        if gone:
            rep.warn(f"{e['name']}: stale derived asset",
                     f"made from {len(gone)} asset(s) that are no longer in the register (the input changed). "
                     f"Built against {e.get('built_against', '?')}. Run its spoke again")
