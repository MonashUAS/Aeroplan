"""OpenVSP worker: runs in the OpenVSP Python (tools/openvsp/.venv, made by `aeroplan setup OpenVSP`), not in AeroPlan.

    <venv python> -I vsp_worker.py job.json result.json

It imports only openvsp, numpy and the standard library. AeroPlan code (tools/openvsp/runner.py) writes the job and reads
the result. Jobs:

    {"job": "version"}                               -> {"version": "OpenVSP 3.54.0"}
    {"job": "write", "spec": SPEC, "path": P}        -> {"path": P}       make the .vsp3 file
    {"job": "read", "path": P}                       -> {"spec": SPEC}    the .vsp3 file back to the spec
    {"job": "project", "path": P, "sets": [{"geom", "points"}]}
                                                     -> {"distances": [[d, ...], ...]}  point to surface, m
    {"job": "probe", "path": P, "geom", "u": [...], "w": [...]}  -> {"points": [[x, y, z], ...]} (u, w in 0..1)
    {"job": "eta_to_u", "path": P, "geom", "eta": [...]}         -> {"u": [...]} (u in 0..1)
    {"job": "edit", "path": P, "out": P2, "set": [{"geom", "parm", "group", "value", "subsurf"?}]} -> {"path": P2}
    {"job": "get", "path": P, "get": [{"geom", "parm", "group"}]}                       -> {"values": [...]}
    {"job": "compgeom", "path": P, "sets": SETS, "set": NAME}    -> wetted area and volume of each component
    {"job": "parasite_drag", "path": P, "sets": SETS, "set": NAME, "cond": COND}          -> CD0 build-up
    {"job": "vspaero", "path": P, "dir": D, "name": N, "sets": SETS, "thin": NAME, "thick": NAME|null, "case": CASE}
                                                                 -> the polar rows of one VSPAERO sweep
SETS = {name: [geometry names]}: user sets, made in the model before the analysis. COND = {sref, vinf, altitude_m}.
CASE = {sref, bref, cref, xcg, ycg, zcg, mach, vinf, rho, alpha: [start, end, n], beta: [start, end, n], wake_iter,
        fixed_wake, ncpu}. Metres, degrees, SI.

SPEC (design frame: x aft, y right, z up, metres, degrees):
    {"wings": [{"instance", "position": [x, y, z], "rx_deg", "ry_deg", "mirror": bool,
                "sections": [{"y", "chord", "x_offset", "dihedral_deg", "twist_deg", "foil"}],
                "foils": {name: [[x/c, z/c], ...]},          Selig order (upper TE -> LE -> lower TE)
                "controls": [{"name", "eta": [a, b], "hinge_x_over_c"}]}],
     "bodies": [{"instance", "frames": [[[x, y, z], ...], ...]}],  right half of each frame, top to bottom
                                                                    ("body", one body, is the old key: it is also read)
     "rotors": [{"instance", "p0", "axis", "diameter"}],  actuator disks (OpenVSP propeller in disk mode): `p0` the hub,
                                                           `axis` the direction of the slipstream (opposite the thrust)
     "parts": [{"name", "p0", "axis", "length", "radius"}],  round cylinders (lift booms, rotor discs): `p0` the start,
                                                              `axis` a unit vector, `length` and `radius` in m
     "reference_meshes": [{"name", "stl"}]}

The wing section rules are those of the flow5 planform in AeroPlan (aeroplan.geometry._edges): y is the projected
span station, the section twists about its quarter chord in the x-z plane, and the dihedral of a section sets the
panel outboard of it. An OpenVSP wing section i (XSec i-1 to XSec i) has the true span dy / cos(dihedral), the
leading-edge sweep of the x_offset change, and the dihedral of flow5 section i-1. The dihedral of the last flow5
section sets no panel: OpenVSP has no slot for it, so `read` gives the dihedral of the panel inboard of it.
"""
from __future__ import annotations

import json
import math
import os
import sys
import traceback

import numpy as np
import openvsp as vsp

PIVOT = 0.25          # twist axis, fraction of the chord (aeroplan.visual.PIVOT)
REF_SUFFIX = " (reference)"
PART_SUFFIX = " (part)"     # lift booms and rotor discs: write-only parts, ingest does not read them back


# ------------------------------------------------------------------------------------------------------- helpers
def _set(container: str, name: str, group: str, value: float) -> None:
    pid = vsp.FindParm(container, name, group)
    if not pid:
        raise RuntimeError(f"OpenVSP has no parameter {group}/{name}")
    vsp.SetParmVal(pid, float(value))


def _get(container: str, name: str, group: str) -> float:
    pid = vsp.FindParm(container, name, group)
    if not pid:
        raise RuntimeError(f"OpenVSP has no parameter {group}/{name}")
    return vsp.GetParmVal(pid)


def _vec(p) -> list:
    return [p.x(), p.y(), p.z()]


def _check_errors(where: str) -> None:
    mgr = vsp.ErrorMgrSingleton.getInstance()
    msgs = []
    while mgr.GetNumTotalErrors() > 0:
        e = mgr.PopLastError()
        msgs.append(e.GetErrorString())
    if msgs:
        raise RuntimeError(f"{where}: OpenVSP error: {'; '.join(msgs)}")


def _split_foil(contour: list) -> tuple:
    """Upper and lower surface (each from the leading edge to the trailing edge) of a Selig contour."""
    c = np.asarray(contour, float)
    i = int(np.argmin(c[:, 0]))
    return c[: i + 1][::-1], c[i:]


def _geoms_by_name() -> dict:
    out = {}
    for g in vsp.FindGeoms():
        name = vsp.GetGeomName(g)
        if name in out:
            raise RuntimeError(f"two OpenVSP components are named {name!r}")
        out[name] = g
    return out


# --------------------------------------------------------------------------------------------------------- write
def _write_wing(w: dict) -> str:
    secs = w["sections"]
    n = len(secs)
    g = vsp.AddGeom("WING")
    vsp.SetGeomName(g, w["instance"])
    for flag in ("RelativeDihedralFlag", "RelativeTwistFlag", "RotateAirfoilMatchDideralFlag"):
        _set(g, flag, "WingGeom", 0)
    _set(g, "TwistAllInXZPlaneFlag", "WingGeom", 1)   # twist in the x-z plane, as the flow5 sections
    _set(g, "Sym_Planar_Flag", "Sym", vsp.SYM_XZ if w["mirror"] else 0)
    xs = vsp.GetXSecSurf(g, 0)
    while vsp.GetNumXSec(xs) < n:
        vsp.InsertXSec(g, vsp.GetNumXSec(xs) - 1, vsp.XS_FILE_AIRFOIL)
    vsp.Update()
    for i in range(1, n):
        a, b = secs[i - 1], secs[i]
        vsp.SetDriverGroup(g, i, vsp.SPAN_WSECT_DRIVER, vsp.ROOTC_WSECT_DRIVER, vsp.TIPC_WSECT_DRIVER)
        dih = math.radians(a["dihedral_deg"])
        span = (b["y"] - a["y"]) / math.cos(dih)
        grp = f"XSec_{i}"
        _set(g, "Span", grp, span)
        _set(g, "Root_Chord", grp, a["chord"])
        _set(g, "Tip_Chord", grp, b["chord"])
        _set(g, "Sweep_Location", grp, 0.0)
        _set(g, "Sweep", grp, math.degrees(math.atan2(b["x_offset"] - a["x_offset"], span)))
        _set(g, "Dihedral", grp, a["dihedral_deg"])
        vsp.Update()                      # each section needs the update before the next (the drivers chain)
    for i, s in enumerate(secs):
        grp = f"XSec_{i}"
        _set(g, "Twist", grp, s["twist_deg"])
        _set(g, "Twist_Location", grp, PIVOT)
        vsp.ChangeXSecShape(xs, i, vsp.XS_FILE_AIRFOIL)
        up, lo = _split_foil(w["foils"][s["foil"]])
        vsp.SetAirfoilPnts(vsp.GetXSec(xs, i), [vsp.vec3d(x, z, 0.0) for x, z in up],
                           [vsp.vec3d(x, z, 0.0) for x, z in lo])
    x, y, z = w["position"]
    for k, v in (("X_Rel_Location", x), ("Y_Rel_Location", y), ("Z_Rel_Location", z),
                 ("X_Rel_Rotation", -w["rx_deg"]), ("Y_Rel_Rotation", w["ry_deg"])):
        _set(g, k, "XForm", v)
    for c in w.get("controls", []):
        ss = vsp.AddSubSurf(g, vsp.SS_CONTROL, 0)
        vsp.SetSubSurfName(g, ss, c["name"])
        for k, v in (("EtaFlag", 1), ("Abs_Rel_Flag", 1), ("SE_Const_Flag", 1), ("LE_Flag", 0), ("Surf_Type", 2),
                     ("EtaStart", c["eta"][0]), ("EtaEnd", c["eta"][1]),
                     ("Length_C_Start", 1.0 - c["hinge_x_over_c"]), ("Length_C_End", 1.0 - c["hinge_x_over_c"])):
            _set(ss, k, "SS_Control", v)
    vsp.Update()
    _check_errors(f"wing {w['instance']}")
    return g


def _frame_ring(half: np.ndarray) -> tuple:
    """(ring, width, height, z_centre) of a right-half frame: the OpenVSP file section, normalised to width and
    height 1. The ring starts at the right-most point, runs down through the bottom, round the left side and over
    the top, back to the start (the order SetXSecPnts needs)."""
    w = 2.0 * float(half[:, 1].max())
    zc = (float(half[:, 2].max()) + float(half[:, 2].min())) / 2.0
    h = float(half[:, 2].max() - half[:, 2].min())
    k = int(np.argmax(half[:, 1]))
    if k in (0, len(half) - 1):
        raise ValueError("the widest point of a frame must not be its top or bottom point")
    pts = np.vstack([half[k:], (half[::-1] * [1, -1, 1])[1:], half[1: k + 1]])
    ring = np.column_stack([pts[:, 1] / w, (pts[:, 2] - zc) / h])
    return ring, w, h, zc


def _write_body(b: dict) -> str:
    frames = [np.asarray(f, float) for f in b["frames"]]
    x0, x1 = frames[0][0, 0], frames[-1][0, 0]
    length = x1 - x0
    g = vsp.AddGeom("FUSELAGE")
    vsp.SetGeomName(g, b["instance"])
    _set(g, "Length", "Design", length)
    xs = vsp.GetXSecSurf(g, 0)
    while vsp.GetNumXSec(xs) < len(frames):
        vsp.InsertXSec(g, vsp.GetNumXSec(xs) - 2, vsp.XS_FILE_FUSE)
    while vsp.GetNumXSec(xs) > len(frames):
        vsp.CutXSec(g, 1)
    vsp.Update()
    for i, f in enumerate(frames):
        point = float(np.ptp(f[:, 1])) == 0.0 and float(np.ptp(f[:, 2])) == 0.0
        vsp.ChangeXSecShape(xs, i, vsp.XS_POINT if point else vsp.XS_FILE_FUSE)
        xsec = vsp.GetXSec(xs, i)
        _set(xsec, "XLocPercent", "XSec", (f[0, 0] - x0) / length)
        if point:
            _set(xsec, "ZLocPercent", "XSec", f[0, 2] / length)
            continue
        ring, w, h, zc = _frame_ring(f)
        vsp.SetXSecPnts(xsec, [vsp.vec3d(p[0], p[1], 0.0) for p in ring])
        # the parameters, not SetXSecWidthHeight: that call updates the whole model (1.5 s each)
        vsp.SetParmVal(vsp.GetXSecParm(xsec, "Width"), w)
        vsp.SetParmVal(vsp.GetXSecParm(xsec, "Height"), h)
        _set(xsec, "ZLocPercent", "XSec", zc / length)
        _check_errors(f"body {b['instance']} frame {i}")
    _set(g, "X_Rel_Location", "XForm", x0)
    vsp.Update()
    _check_errors(f"body {b['instance']}")
    return g


def _write_part(p: dict) -> str:
    """A round cylinder from `p0` along `axis`: an OpenVSP fuselage with circle sections. The rotation turns the
    fuselage axis x onto `axis`."""
    a = np.asarray(p["axis"], float)
    a = a / np.linalg.norm(a)
    g = vsp.AddGeom("FUSELAGE")
    vsp.SetGeomName(g, p["name"] + PART_SUFFIX)
    xs = vsp.GetXSecSurf(g, 0)
    while vsp.GetNumXSec(xs) > 2:                          # two sections: a straight cylinder, no spline overshoot
        vsp.CutXSec(g, 1)
    n = vsp.GetNumXSec(xs)
    for i in range(n):
        vsp.ChangeXSecShape(xs, i, vsp.XS_CIRCLE)
        xsec = vsp.GetXSec(xs, i)
        _set(xsec, "XLocPercent", "XSec", i / (n - 1))
        vsp.SetXSecTanAngles(xsec, vsp.XSEC_BOTH_SIDES, 0.0, 0.0, 0.0, 0.0)      # the end tangent of a fuselage rounds the end: 0 keeps it straight
        vsp.SetParmVal(vsp.GetXSecParm(xsec, "Circle_Diameter"), 2.0 * p["radius"])
    vsp.Update()
    _set(g, "Length", "Design", p["length"])
    _place(g, p["p0"], a)
    vsp.Update()
    _check_errors(f"part {p['name']}")
    return g


def _place(g: str, p0, axis) -> None:
    """Put the origin of a geom at `p0` and turn its x axis onto the unit vector `axis`. OpenVSP turns about z first,
    then about y (measured): x -> (cos ry cos rz, sin rz, -sin ry cos rz)."""
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    for k, v in zip(("X_Rel_Location", "Y_Rel_Location", "Z_Rel_Location"), p0):
        _set(g, k, "XForm", float(v))
    _set(g, "Z_Rel_Rotation", "XForm", math.degrees(math.asin(float(a[1]))))
    _set(g, "Y_Rel_Rotation", "XForm", math.degrees(math.atan2(-float(a[2]), float(a[0]))))


def _write_rotor(r: dict) -> str:
    """An actuator disk: a propeller in disk mode. Its x axis is the slipstream direction. The operating point (rpm, CT,
    CP) is set for each run (job_vspaero)."""
    g = vsp.AddGeom("PROP")
    vsp.SetGeomName(g, r["instance"])
    _set(g, "PropMode", "Design", float(vsp.PROP_DISK))
    _set(g, "Diameter", "Design", float(r["diameter"]))
    _place(g, r["p0"], r["axis"])
    vsp.Update()
    _check_errors(f"rotor {r['instance']}")
    return g


def job_write(spec: dict, path: str) -> dict:
    vsp.VSPRenew()
    vsp.ClearVSPModel()
    for w in spec.get("wings", []):
        _write_wing(w)
    for b in spec.get("bodies") or ([spec["body"]] if spec.get("body") else []):
        _write_body(b)
    for p in spec.get("parts", []):
        _write_part(p)
    for r in spec.get("rotors", []):
        _write_rotor(r)
    for m in spec.get("reference_meshes", []):
        g = vsp.ImportFile(m["stl"], vsp.IMPORT_STL, "")
        if not g:
            raise RuntimeError(f"OpenVSP could not import {m['stl']}")
        vsp.SetGeomName(g, m["name"] + REF_SUFFIX)
    vsp.Update()
    vsp.SetVSP3FileName(path)
    vsp.WriteVSPFile(path, vsp.SET_ALL)
    _check_errors(f"write {path}")
    return {"path": path}


# ---------------------------------------------------------------------------------------------------------- read
def _read_foil(xsec: str, n_sample: int = 161) -> list:
    """The Selig contour of a wing XSec: the stored points of a file airfoil, else samples of the curve."""
    if vsp.GetXSecShape(xsec) == vsp.XS_FILE_AIRFOIL:
        up = [(p.x(), p.y()) for p in vsp.GetAirfoilUpperPnts(xsec)]
        lo = [(p.x(), p.y()) for p in vsp.GetAirfoilLowerPnts(xsec)]
        tc, base = (vsp.GetParmVal(vsp.GetXSecParm(xsec, k)) for k in ("ThickChord", "BaseThickChord"))
        k = tc / base if base else 1.0
        up = [(x, z * k) for x, z in up]
        lo = [(x, z * k) for x, z in lo]
        return [list(p) for p in up[::-1]] + [list(p) for p in lo[1:]]
    pts = np.array([_vec(vsp.ComputeXSecPnt(xsec, t)) for t in np.linspace(0.0, 1.0, n_sample)])
    chord = pts[:, 0].max() - pts[:, 0].min()
    c = np.column_stack([(pts[:, 0] - pts[:, 0].min()) / chord, pts[:, 1] / chord])
    i = int(np.argmin(c[:, 0]))
    if c[: i + 1, 1].mean() < c[i:, 1].mean():   # make it Selig: the upper surface first
        c = c[::-1]
    return c.tolist()


def _read_wing(g: str) -> dict:
    xs = vsp.GetXSecSurf(g, 0)
    n = vsp.GetNumXSec(xs)
    for flag in ("RelativeDihedralFlag", "RelativeTwistFlag", "RotateAirfoilMatchDideralFlag"):
        if _get(g, flag, "WingGeom") != 0:
            raise ValueError(f"wing {vsp.GetGeomName(g)}: switch off {flag} (the spoke reads absolute angles)")
    if _get(g, "TwistAllInXZPlaneFlag", "WingGeom") != 1:
        raise ValueError(f"wing {vsp.GetGeomName(g)}: switch on TwistAllInXZPlaneFlag (the sections twist in the x-z "
                         "plane, as in flow5)")
    secs = [{"y": 0.0, "x_offset": 0.0}]
    for i in range(1, n):
        grp = f"XSec_{i}"
        span, cr, ct = _get(g, "Span", grp), _get(g, "Root_Chord", grp), _get(g, "Tip_Chord", grp)
        loc, sweep = _get(g, "Sweep_Location", grp), math.radians(_get(g, "Sweep", grp))
        dih = _get(g, "Dihedral", grp)
        secs[i - 1].update({"chord": cr, "dihedral_deg": dih})
        secs.append({"y": secs[i - 1]["y"] + span * math.cos(math.radians(dih)),
                     "x_offset": secs[i - 1]["x_offset"] + span * math.tan(sweep) - loc * (ct - cr), "chord": ct})
    secs[-1]["dihedral_deg"] = secs[-2]["dihedral_deg"]
    foils = {}
    for i, s in enumerate(secs):
        grp = f"XSec_{i}"
        if abs(_get(g, "Twist_Location", grp) - PIVOT) > 1e-12:
            raise ValueError(f"wing {vsp.GetGeomName(g)} XSec {i}: Twist_Location must be {PIVOT}")
        s["twist_deg"] = _get(g, "Twist", grp)
        s["foil"] = f"s{i}"
        foils[s["foil"]] = _read_foil(vsp.GetXSec(xs, i))
    controls = []
    for ss in vsp.GetSubSurfIDVec(g):
        if vsp.GetSubSurfType(ss) != vsp.SS_CONTROL:
            continue
        if _get(ss, "EtaFlag", "SS_Control") != 1 or _get(ss, "Abs_Rel_Flag", "SS_Control") != 1:
            raise ValueError(f"control surface {vsp.GetSubSurfName(ss)}: use the eta span and the chord fraction")
        lc0, lc1 = _get(ss, "Length_C_Start", "SS_Control"), _get(ss, "Length_C_End", "SS_Control")
        if abs(lc0 - lc1) > 1e-12:
            raise ValueError(f"control surface {vsp.GetSubSurfName(ss)}: the hinge chord fraction must be constant")
        controls.append({"name": vsp.GetSubSurfName(ss),
                         "eta": [_get(ss, "EtaStart", "SS_Control"), _get(ss, "EtaEnd", "SS_Control")],
                         "hinge_x_over_c": 1.0 - lc0})
    return {"instance": vsp.GetGeomName(g),
            "position": [_get(g, k, "XForm") for k in ("X_Rel_Location", "Y_Rel_Location", "Z_Rel_Location")],
            "rx_deg": -_get(g, "X_Rel_Rotation", "XForm"), "ry_deg": _get(g, "Y_Rel_Rotation", "XForm"),
            "mirror": _get(g, "Sym_Planar_Flag", "Sym") == vsp.SYM_XZ,
            "sections": secs, "foils": foils, "controls": controls}


def _read_body(g: str, n_half: int) -> dict:
    xs = vsp.GetXSecSurf(g, 0)
    length = _get(g, "Length", "Design")
    x0 = _get(g, "X_Rel_Location", "XForm")
    frames = []
    for i in range(vsp.GetNumXSec(xs)):
        xsec = vsp.GetXSec(xs, i)
        x = x0 + _get(xsec, "XLocPercent", "XSec") * length
        zc = _get(xsec, "ZLocPercent", "XSec") * length
        shape = vsp.GetXSecShape(xsec)
        if shape == vsp.XS_POINT:
            frames.append([[x, 0.0, zc]] * n_half)
            continue
        w, h = vsp.GetXSecWidth(xsec), vsp.GetXSecHeight(xsec)
        if shape == vsp.XS_FILE_FUSE:
            ring = np.array([_vec(p) for p in vsp.GetXSecPnts(xsec)])[:, :2]
            n = (len(ring) + 1) // 2
            bottom = next(j for j in range(1, len(ring)) if abs(ring[j, 0]) < 1e-12)
            k = n - 1 - bottom
            # the ring of _frame_ring: H[k..n-1], the mirror of H[n-2..0], H[1..k] (H: the right half)
            half = np.vstack([[ring[len(ring) - 1 - k]], ring[len(ring) - k:], ring[1: bottom + 1]])
            half[0, 0] = 0.0
            half = half * [w, h] + [0.0, zc]
        else:
            # a shape type of the OpenVSP GUI: n_half samples of the right half, from the top to the bottom
            t = np.concatenate([np.linspace(0.75, 1.0, n_half // 2 + 1)[:-1], np.linspace(0.0, 0.25, n_half - n_half // 2)])
            pts = np.array([_vec(vsp.ComputeXSecPnt(xsec, float(u))) for u in t])
            half = pts[:, :2] + [0.0, zc]
            half[:, 0] = np.abs(half[:, 0])
        frames.append([[x, float(p[0]), float(p[1])] for p in half])
    return {"instance": vsp.GetGeomName(g), "frames": frames}


def job_read(path: str, n_half: int = 13) -> dict:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no OpenVSP model {path}")
    vsp.VSPRenew()
    vsp.ReadVSPFile(path)
    vsp.Update()
    _check_errors(f"read {path}")
    spec = {"wings": [], "body": None, "bodies": [], "parts": [], "rotors": [], "reference_meshes": [], "other": []}
    for name, g in _geoms_by_name().items():
        t = vsp.GetGeomTypeName(g)
        if name.endswith(PART_SUFFIX):
            spec["parts"].append({"name": name[: -len(PART_SUFFIX)]})
        elif name.endswith(REF_SUFFIX):
            spec["reference_meshes"].append({"name": name[: -len(REF_SUFFIX)]})
        elif t == "Propeller":
            spec["rotors"].append({"instance": name})
        elif t == "Wing":
            spec["wings"].append(_read_wing(g))
        elif t == "Fuselage":
            spec["bodies"].append(_read_body(g, n_half))
            spec["body"] = spec["body"] or spec["bodies"][0]
        else:
            spec["other"].append({"name": name, "type": t})
    return {"spec": spec}


# ------------------------------------------------------------------------------------------------- shape probes
def _open(path: str) -> dict:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no OpenVSP model {path}")
    vsp.VSPRenew()
    vsp.ReadVSPFile(path)
    vsp.Update()
    return _geoms_by_name()


def job_project(path: str, sets: list) -> dict:
    """The distance from each point to the main surface of a component (surface 0: the right half)."""
    geoms = _open(path)
    out, near = [], []
    for s in sets:
        pts = [vsp.vec3d(*p) for p in s["points"]]
        res = vsp.ProjVecPnt01(geoms[s["geom"]], 0, pts)
        if not (isinstance(res, (tuple, list)) and len(res) == 3):
            raise RuntimeError("ProjVecPnt01 gave an unknown result layout")
        us, ws, d = list(res[0]), list(res[1]), [float(v) for v in res[2]]
        # a start guess on the iso-u line of the section: the global search can stop on a cap patch next to it
        for j, u0 in enumerate(s.get("u0") or []):
            if d[j] < 1e-7:
                continue
            r = vsp.ProjPnt01Guess(geoms[s["geom"]], 0, pts[j], float(u0), float(ws[j]))
            if float(r[0]) < d[j]:
                d[j], us[j], ws[j] = float(r[0]), float(r[1]), float(r[2])
        res = (us, ws, d)
        out.append(d)
        if s.get("closest"):
            near.append([_vec(q) for q in vsp.CompVecPnt01(geoms[s["geom"]], 0, list(res[0]), list(res[1]))])
    return {"distances": out, **({"closest": near} if near else {})}


def job_probe(path: str, geom: str, u: list, w: list) -> dict:
    g = _open(path)[geom]
    pts = vsp.CompVecPnt01(g, 0, [float(v) for v in u], [float(v) for v in w])
    return {"points": [_vec(p) for p in pts]}


def job_eta_to_u(path: str, geom: str, eta: list) -> dict:
    g = _open(path)[geom]
    u_max = vsp.GetNumXSec(vsp.GetXSecSurf(g, 0)) + 1.0     # a wing surface: the sections and the two end caps
    out = []
    for e in eta:
        r = vsp.ConvertEtatoU(g, float(e))
        out.append(float(r[0] if isinstance(r, (tuple, list)) else r) / u_max)
    return {"u": out}


def job_edit(path: str, out: str, changes: list) -> dict:
    """Change parameters of a model and save it (the tests use it in place of an edit in the OpenVSP GUI)."""
    geoms = _open(path)
    for c in changes:
        container = geoms[c["geom"]]
        if c.get("subsurf"):
            container = next(ss for ss in vsp.GetSubSurfIDVec(container) if vsp.GetSubSurfName(ss) == c["subsurf"])
        _set(container, c["parm"], c["group"], c["value"])
        vsp.Update()
    vsp.WriteVSPFile(out, vsp.SET_ALL)
    _check_errors(f"edit {path}")
    return {"path": out}


def job_get(path: str, items: list) -> dict:
    geoms = _open(path)
    return {"values": [_get(geoms[c["geom"]], c["parm"], c["group"]) for c in items]}


# ----------------------------------------------------------------------------------------------------- analyses
def _user_sets(geoms: dict, sets: dict) -> dict:
    """Make the user sets {name: [geometry names]}. Returns {name: set index}."""
    n = len(sets)
    index = {}
    for g in geoms.values():
        for i in range(vsp.SET_FIRST_USER, vsp.SET_FIRST_USER + n):
            vsp.SetSetFlag(g, i, False)
    for k, (name, members) in enumerate(sets.items()):
        index[name] = vsp.SET_FIRST_USER + k
        for m in members:
            if m not in geoms:
                raise ValueError(f"the model has no component {m!r} (set {name})")
            vsp.SetSetFlag(geoms[m], index[name], True)
    vsp.Update()
    return index


def _results(rid: str) -> dict:
    out = {}
    for n in vsp.GetAllDataNames(rid):
        ty = vsp.GetResultsType(rid, n)
        out[n] = list(vsp.GetStringResults(rid, n, 0) if ty == 3 else vsp.GetIntResults(rid, n, 0) if ty == 1
                      else vsp.GetDoubleResults(rid, n, 0) if ty == 2 else [])
    return out


def job_compgeom(path: str, sets: dict, set_name: str) -> dict:
    """Wetted area and volume of each component of a set. A mesh component (the CAD skin) is one entry."""
    geoms = _open(path)
    idx = _user_sets(geoms, sets)[set_name]
    a = "CompGeom"
    vsp.SetAnalysisInputDefaults(a)
    vsp.SetIntAnalysisInput(a, "Set", [idx])
    vsp.SetIntAnalysisInput(a, "WriteCSVFlag", [0])
    vsp.SetIntAnalysisInput(a, "WriteTXTFlag", [0])
    r = _results(vsp.ExecAnalysis(a))
    _check_errors("compgeom")
    comps = [{"name": n, "wet_area_m2": r["Wet_Area"][i], "theo_area_m2": r["Theo_Area"][i],
              "wet_volume_m3": r["Wet_Vol"][i], "theo_volume_m3": r["Theo_Vol"][i]}
             for i, n in enumerate(r["Comp_Name"][: len(r["Wet_Area"])])]
    return {"components": comps, "total_wet_area_m2": r["Total_Wet_Area"][0], "total_theo_area_m2": r["Total_Theo_Area"][0],
            "total_theo_volume_m3": r["Total_Theo_Vol"][0], "num_tris": r["Total_Num_Tris"][0]}


def job_parasite_drag(path: str, sets: dict, set_name: str, cond: dict) -> dict:
    """The OpenVSP parasite drag build-up (form factors, Reynolds numbers, flat plate Cf) at ISA altitude."""
    geoms = _open(path)
    idx = _user_sets(geoms, sets)[set_name]
    a = "ParasiteDrag"
    vsp.SetAnalysisInputDefaults(a)
    vsp.SetIntAnalysisInput(a, "GeomSet", [idx])
    for k, v in (("LengthUnit", vsp.LEN_M), ("VelocityUnit", 1), ("AltLengthUnit", 1), ("RefFlag", 0), ("RecomputeGeom", 1),
                 ("FreestreamPropChoice", vsp.ATMOS_TYPE_US_STANDARD_1976)):
        vsp.SetIntAnalysisInput(a, k, [v])
    for k, v in (("Sref", cond["sref"]), ("Vinf", cond["vinf"]), ("Altitude", cond["altitude_m"]), ("DeltaTemp", 0.0)):
        vsp.SetDoubleAnalysisInput(a, k, [float(v)])
    r = _results(vsp.ExecAnalysis(a))
    _check_errors("parasite drag")
    n = int(r["Num_Comp"][0])
    comps = []
    for i in range(n):
        row = {"name": r["Comp_Label"][i]}
        for key, val in r.items():
            if key.startswith("Comp_") and key not in ("Comp_Label", "Comp_SurfNum") and len(val) == n:
                row[key[len("Comp_"):]] = val[i]
        comps.append(row)
    return {"components": comps, "cd0": r["Total_CD_Total"][0], "f_total_m2": r["Total_f_Total"][0],
            "condition": {k: r[k][0] for k in ("FC_Alt", "FC_Mach", "FC_Rho", "FC_Sref", "FC_Vinf") if k in r}}


def _read_polar(path: str) -> list:
    lines = [ln for ln in open(path, encoding="utf-8", errors="replace").read().splitlines() if ln.strip()]
    hdr = next(i for i, ln in enumerate(lines) if ln.split()[:2] == ["Beta", "Mach"])
    cols = lines[hdr].split()
    rows = []
    for ln in lines[hdr + 1:]:
        vals = ln.split()
        if len(vals) != len(cols):
            continue
        row = {}
        for c, v in zip(cols, vals):
            try:
                row[c] = float(v)
            except ValueError:
                row[c] = float("nan")
        rows.append(row)
    return rows


def _set_rotors(geoms: dict, set_indexes: list, states: dict) -> dict:
    """Put the rotors of `states` ({instance: {rpm, ct, cp}}) in the VSPAERO sets, and every other rotor out of them. Set
    the operating point of each disk. Returns {instance: expected hub xyz}."""
    props = [n for n, g in geoms.items() if vsp.GetGeomTypeName(g) == "Propeller"]
    unknown = sorted(set(states) - set(props))
    if unknown:
        raise ValueError(f"the model has no rotor {unknown}")
    if len(props) != vsp.GetNumActuatorDisks():
        raise RuntimeError(f"{len(props)} propeller components but {vsp.GetNumActuatorDisks()} actuator disks: "
                           "a rotor must be in disk mode")
    disk_of = _disk_of_rotor({n: geoms[n] for n in props})
    out = {}
    for n in props:
        g = geoms[n]
        for i in set_indexes:
            vsp.SetSetFlag(g, i, n in states)
        if n not in states:
            continue
        for key, par in (("rpm", "RotorRPM"), ("ct", "RotorCT"), ("cp", "RotorCP")):
            vsp.SetParmVal(vsp.GetParm(disk_of[n], par, "Rotor"), float(states[n][key]))
        out[n] = [_get(g, a, "XForm") for a in ("X_Location", "Y_Location", "Z_Location")]
    vsp.Update()
    return out


def _disk_of_rotor(props: dict) -> dict:
    """{instance: actuator disk id}. OpenVSP gives no link from a disk to its component and the disks do not follow the
    order of the components. Each component gets a unique diameter for a moment (steps of 0.1 mm); the disk with that
    diameter is its disk. The diameters are restored."""
    names = list(props)
    d0 = {n: _get(props[n], "Diameter", "Design") for n in names}
    for k, n in enumerate(names):
        _set(props[n], "Diameter", "Design", d0[n] + (k + 1) * 1e-4)
    vsp.Update()
    disks = [vsp.FindActuatorDisk(k) for k in range(vsp.GetNumActuatorDisks())]
    out = {}
    for k, n in enumerate(names):
        want = d0[n] + (k + 1) * 1e-4
        hit = [d for d in disks if abs(vsp.GetParmVal(vsp.GetParm(d, "RotorDiameter", "Rotor")) - want) < 1e-9]
        if len(hit) != 1:
            raise RuntimeError(f"no unique actuator disk for the rotor {n} ({len(hit)} with diameter {want} m)")
        out[n] = hit[0]
    for n in names:
        _set(props[n], "Diameter", "Design", d0[n])
    vsp.Update()
    return out


def _check_rotor_file(path: str, expected: dict) -> list:
    """The PropElement blocks that VSPAERO wrote (<case>.vspaero). Each expected rotor must be there, at its hub, with
    its CT. Returns [{instance, xyz, normal, radius, rpm, ct, cp}]."""
    lines = [ln.strip() for ln in open(path, encoding="utf-8", errors="replace").read().splitlines()]
    found = []
    for i, ln in enumerate(lines):
        if ln.startswith("PropElement_"):
            xyz = [float(x) for x in lines[i + 2].split()]
            nrm = [float(x) for x in lines[i + 3].split()]
            found.append({"xyz": xyz, "normal": nrm, "radius": float(lines[i + 4]), "hub_radius": float(lines[i + 5]),
                          "rpm": float(lines[i + 6]), "ct": float(lines[i + 7]), "cp": float(lines[i + 8])})
    if len(found) != len(expected):
        raise RuntimeError(f"VSPAERO wrote {len(found)} rotors, the run has {len(expected)}: {path}")
    used = []
    for n, xyz in expected.items():
        near = min(found, key=lambda f: sum((a - b) ** 2 for a, b in zip(f["xyz"], xyz)))
        if sum((a - b) ** 2 for a, b in zip(near["xyz"], xyz)) > 1e-8:
            raise RuntimeError(f"VSPAERO has no rotor at the hub of {n} {xyz}: {path}")
        used.append({"instance": n} | near)
    return used


def job_vspaero(path: str, dir: str, name: str, sets: dict, thin, thick, case: dict) -> dict:
    """One VSPAERO sweep: thin surfaces (VLM) and thick surfaces (panel). Writes <dir>/<name>.* and the log."""
    import re
    import time

    geoms = _open(path)
    idx = _user_sets(geoms, sets)
    os.makedirs(dir, exist_ok=True)
    thin_i = idx[thin] if thin else -1
    thick_i = idx[thick] if thick else -1
    disks = _set_rotors(geoms, [i for i in (thin_i, thick_i) if i >= 0], case["rotors"]) if "rotors" in case else {}
    model = os.path.join(dir, name + ".vsp3")
    vsp.SetVSP3FileName(model)
    vsp.WriteVSPFile(model, vsp.SET_ALL)
    c = "VSPAEROComputeGeometry"
    vsp.SetAnalysisInputDefaults(c)
    vsp.SetIntAnalysisInput(c, "GeomSet", [thick_i])
    vsp.SetIntAnalysisInput(c, "ThinGeomSet", [thin_i])
    vsp.ExecAnalysis(c)
    _check_errors("vspaero geometry")
    a = "VSPAEROSweep"
    vsp.SetAnalysisInputDefaults(a)
    vsp.SetIntAnalysisInput(a, "GeomSet", [thick_i])
    vsp.SetIntAnalysisInput(a, "ThinGeomSet", [thin_i])
    for k, v in (("Sref", case["sref"]), ("bref", case["bref"]), ("cref", case["cref"]), ("Xcg", case["xcg"]),
                 ("Ycg", case["ycg"]), ("Zcg", case["zcg"]), ("Machref", case["mach"]), ("MachStart", case["mach"]),
                 ("MachEnd", case["mach"]), ("Vinf", case["vinf"]), ("Vref", case["vinf"]), ("Rho", case["rho"]),
                 ("AlphaStart", case["alpha"][0]), ("AlphaEnd", case["alpha"][1]),
                 ("BetaStart", case["beta"][0]), ("BetaEnd", case["beta"][1])):
        vsp.SetDoubleAnalysisInput(a, k, [float(v)])
    for k, v in (("AlphaNpts", case["alpha"][2]), ("BetaNpts", case["beta"][2]), ("MachNpts", 1), ("RefFlag", 0),
                 ("MACFlag", 0), ("NCPU", case.get("ncpu") or os.cpu_count() or 4), ("WakeNumIter", case["wake_iter"]),
                 ("FixedWakeFlag", 1 if case.get("fixed_wake", True) else 0)):
        vsp.SetIntAnalysisInput(a, k, [int(v)])
    log = os.path.join(dir, name + ".log")
    vsp.SetStringAnalysisInput(a, "RedirectFile", [log])
    t0 = time.time()
    vsp.ExecAnalysis(a)
    seconds = time.time() - t0
    text = open(log, encoding="utf-8", errors="replace").read()
    if "Mesh is not logically valid" in text:
        raise RuntimeError(f"VSPAERO {name}: the mesh is not logically valid (an edge with more than 2 triangles). "
                           f"See {log}")
    polar = model[: -len(".vsp3")] + ".polar"
    if not os.path.isfile(polar):
        raise RuntimeError(f"VSPAERO {name}: no polar file. See {log}")
    tris = {}
    for k in ("thin", "thick"):
        m = re.search(rf"Number of {k} +tris: +(\d+)", text)
        if m:
            tris[k] = int(m.group(1))
    out = {"rows": _read_polar(polar), "seconds": seconds, "log": log, "polar": polar, "triangles": tris}
    if "rotors" in case:
        out["rotors"] = _check_rotor_file(model[: -len(".vsp3")] + ".vspaero", disks)
    return out


def main(argv: list) -> int:
    job_file, result_file = argv[1], argv[2]
    job = json.loads(open(job_file, encoding="utf-8").read())
    try:
        if hasattr(vsp, "SilenceErrors"):
            vsp.SilenceErrors()
        kind = job["job"]
        if kind == "version":
            res = {"version": vsp.GetVSPVersion()}
        elif kind == "write":
            res = job_write(job["spec"], job["path"])
        elif kind == "read":
            res = job_read(job["path"], job.get("n_half", 13))
        elif kind == "project":
            res = job_project(job["path"], job["sets"])
        elif kind == "probe":
            res = job_probe(job["path"], job["geom"], job["u"], job["w"])
        elif kind == "eta_to_u":
            res = job_eta_to_u(job["path"], job["geom"], job["eta"])
        elif kind == "edit":
            res = job_edit(job["path"], job["out"], job["set"])
        elif kind == "get":
            res = job_get(job["path"], job["get"])
        elif kind == "compgeom":
            res = job_compgeom(job["path"], job["sets"], job["set"])
        elif kind == "parasite_drag":
            res = job_parasite_drag(job["path"], job["sets"], job["set"], job["cond"])
        elif kind == "vspaero":
            res = job_vspaero(job["path"], job["dir"], job["name"], job["sets"], job.get("thin"), job.get("thick"),
                              job["case"])
        else:
            raise ValueError(f"unknown job {kind!r}")
        out = {"ok": True, **res}
    except Exception as e:  # the AeroPlan side shows the text
        out = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
