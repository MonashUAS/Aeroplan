"""OpenVSP spoke: the ADH geometry -> an OpenVSP model (.vsp3), and a changed OpenVSP model -> the ADH geometry.

OpenVSP runs in its own Python (tools/openvsp/.venv, made by `python -m aeroplan setup OpenVSP`). runner.py sends each job to
vsp_worker.py. The worker holds the rules between the flow5 planform form and the OpenVSP wing form.

Input (git ignores it): work/openvsp/<aircraft>/<model>, the member's OpenVSP model (a copy of the generated model,
changed in the OpenVSP GUI).
Settings (committed): tools/openvsp/settings/<aircraft>.yaml
    vsp_version     the OpenVSP version that the tests ran with (setup warns on another version)
    model           the file name of the member's model in the work folder
    wings           the ADH items (muas.instance) with a planform that go into OpenVSP
    bodies          the ADH items with a body (fuselage, tail boom): each is one OpenVSP fuselage component
                    (`body: <item>` is the old key for one body)
    rotors          the ADH items with a `muas.propeller` (lift rotors, the nose propeller): each is one actuator disk
                    (an OpenVSP propeller in disk mode, axis = the slipstream direction). Write only
    disk_states     the operating points of the disks: {state: {rotor item: prefix of the sizing outputs}}. The outputs
                    <prefix>_rpm, _thrust and _shaft_power are in the performance record of node 1.2 (AeroSandbox spoke)
    parts           the ADH items whose `muas.visual` tube or disc goes in as a round cylinder (lift booms, rotor discs).
                    Write only: ingest does not read them back
    reference_skin  the item whose CAD skin (muas.skin) goes into the model as a reference mesh

What generate writes (work/<aircraft>/generated/): <aircraft>.vsp3 and <skin item>_skin.stl (the skin in the design
frame, m). It gives the gap from the OpenVSP fuselage surface to the skin.

What sweep writes (`aeroplan sweep OpenVSP <aircraft>`): work/<aircraft>/sweeps/<name>/results.json and the raw VSPAERO
files. The analysis settings are in the `analysis` block: user sets of components, the CompGeom and parasite drag sets,
and the VSPAERO runs (thin = VLM set, thick = panel set). The trim point and the ranges come from the flow5 sweep.

What ingest writes, only for the items that differ from the document (the changed file wins):
  - wings: `muas.planform` sections, position and angles, `geometry.lifting_surface`, the foils
  - control surfaces: `muas.control_surface` eta_span and hinge_x_over_c
  - bodies: `geometry.body`
  - `muas.geometry_tool = "OpenVSP"` and an OpenVSP pointer on each changed item. The air vehicle gets the pointer of
    the model it read. When the model sha256 equals that pointer, ingest reads nothing.
Frames. OpenVSP works in x aft, y right, z up. The ADH design frame is FRD (aeroplan.frame). The spoke flips every
position and direction at the edge of the worker (the SPEC, the skin STL, the shape gate points, the points that the
worker reads back) and the VSPAERO forces and moments of an analysis point. The worker keeps the OpenVSP frame.

Before it writes, ingest puts the ADH shape of each item on the OpenVSP surface. A gap above SHAPE_TOL stops the build:
the model then holds a change that the ADH form cannot hold.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from aeroplan import adh_doc
from aeroplan.frame import flip_array, flip_point
from aeroplan.geometry import (body_adh, body_frames, distance_to_mesh, foils_of, lifting_surface_adh, planform_wing,
                               section_points)
from aeroplan.spokes import Context, set_sources

from . import runner

NAME = "OpenVSP"
SHAPE_TOL = 1e-5        # m: the largest gap from the ADH shape to the OpenVSP surface (OpenVSP builds the root
                        # section of a wing with dihedral up to 3.5 um from the foil points, see README.md)
VALUE_TOL = 1e-9        # m and deg: a smaller difference is not a change
SECTION_KEYS = ("y", "chord", "x_offset", "dihedral_deg", "twist_deg")


# ------------------------------------------------------------------------------------------------ eta conversion
def _true_span(sections: List[Dict[str, Any]]) -> np.ndarray:
    """The span along the panels at each section (OpenVSP measures eta along the panels)."""
    y = np.array([s["y"] for s in sections])
    dih = np.radians([s["dihedral_deg"] for s in sections[:-1]])
    return np.concatenate([[0.0], np.cumsum(np.diff(y) / np.cos(dih))])


def eta_to_vsp(sections: List[Dict[str, Any]], eta: float) -> float:
    """ADH eta (fraction of the projected half span) -> OpenVSP eta (fraction of the span along the panels)."""
    y = np.array([s["y"] for s in sections])
    s = _true_span(sections)
    return float(np.interp(eta * y[-1], y, s) / s[-1])


def eta_from_vsp(sections: List[Dict[str, Any]], eta: float) -> float:
    y = np.array([s["y"] for s in sections])
    s = _true_span(sections)
    return float(np.interp(eta * s[-1], s, y) / y[-1])


# --------------------------------------------------------------------------------------------------- the spec
def _controls(doc: Dict[str, Any], parent: str, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OpenVSP control surfaces of a wing. A left/right pair with the same shape is one surface named "a+b"."""
    found: Dict[Tuple, List[str]] = {}
    for _, item, _ in adh_doc.iter_nodes(doc):
        cs = (item.get("muas") or {}).get("control_surface")
        if cs and cs["parent"] == parent:
            key = (tuple(cs["eta_span"]), cs["hinge_x_over_c"], cs.get("side", "both") == "both")
            found.setdefault(key, []).append(item["muas"]["instance"])
    out = []
    for (eta, hinge, both), names in found.items():
        groups = [[n] for n in names] if both else [sorted(names)]
        for g in groups:
            out.append({"name": "+".join(g), "eta": [eta_to_vsp(sections, e) for e in eta], "hinge_x_over_c": hinge})
    return out


def _mirror(pf: Dict[str, Any]) -> bool:
    return pf.get("symmetric", True) and (pf["kind"] != "FIN" or pf.get("two_sided", True))


def body_items(st: Dict[str, Any]) -> List[str]:
    """The ADH items with a body: `bodies` (list), or the old `body` (one item)."""
    return list(st.get("bodies") or ([st["body"]] if st.get("body") else []))


def part_cylinders(doc: Dict[str, Any], items: List[str]) -> List[Dict[str, Any]]:
    """Round cylinders from the `muas.visual` tubes (p0, p1, radius_m) and discs (centre, axis, radius_m, thickness_m)."""
    out = []
    for inst in items:
        for v in adh_doc.find(doc, inst)["muas"].get("visual") or []:
            s = v["shape"]
            if v["generator"] == "tube":
                p0, p1 = np.asarray(s["p0"], float), np.asarray(s["p1"], float)
                out.append({"name": v["part"], "p0": p0.tolist(), "axis": ((p1 - p0) / np.linalg.norm(p1 - p0)).tolist(),
                            "length": float(np.linalg.norm(p1 - p0)), "radius": float(s["radius_m"])})
            elif v["generator"] == "disc":
                ax = np.asarray(s["axis"], float)
                ax = ax / np.linalg.norm(ax)
                t = float(s["thickness_m"])
                out.append({"name": v["part"], "p0": (np.asarray(s["centre"], float) - 0.5 * t * ax).tolist(),
                            "axis": ax.tolist(), "length": t, "radius": float(s["radius_m"])})
    return out


def rotor_geoms(doc: Dict[str, Any], items: List[str]) -> List[Dict[str, Any]]:
    """The actuator disks: hub, slipstream direction (opposite the ADH thrust axis) and diameter of each rotor."""
    out = []
    for inst in items:
        p = adh_doc.find(doc, inst)["muas"]["propeller"]
        t = np.asarray(p["thrust_axis"], float)
        out.append({"instance": inst, "p0": [float(x) for x in p["hub"]["xyz"]], "axis": (-t / np.linalg.norm(t)).tolist(),
                    "diameter": float(p["diameter"]["value"])})
    return out


def sizing_outputs(doc: Dict[str, Any]) -> Dict[str, float]:
    """{name: value} of the outputs of the performance records of node 1.2 (SI; rotor speed in rpm)."""
    out = {}
    for rec in adh_doc.node(doc, "1.2").get("performance") or []:
        for tool in rec.get("tools") or []:
            for o in (tool.get("data_exchange") or {}).get("outputs") or []:
                if isinstance(o.get("value"), (int, float)):
                    out[o["name"]] = float(o["value"])
    return out


def disk_coefficients(thrust_n: float, power_w: float, rpm: float, diameter_m: float, rho: float) -> Tuple[float, float]:
    """(CT, CP) of an actuator disk: T / (rho n^2 D^4) and P / (rho n^3 D^5), n in rev/s."""
    n = rpm / 60.0
    return thrust_n / (rho * n ** 2 * diameter_m ** 4), power_w / (rho * n ** 3 * diameter_m ** 5)


# VSPAERO: a positive RotorRPM turns the air about the +x axis of the disk, that is about the slipstream direction
# (measured 2026-10-18: it gives a negative CMx on the wing). ADH `cw` turns about the thrust axis, so about -slipstream.
SPIN_SIGN = {"cw": -1.0, "ccw": 1.0}


def disk_states(doc: Dict[str, Any], st: Dict[str, Any], rho: float) -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
    """({state: {rotor item: {rpm, ct, cp, thrust_N}}}, {state: [missing output names]}) from `disk_states` of the
    settings and the sizing outputs. The rpm carries the sign of the spin. A state with a missing output is not built."""
    outputs = sizing_outputs(doc)
    states: Dict[str, Any] = {}
    missing: Dict[str, List[str]] = {}
    for state, rotors in (st.get("disk_states") or {}).items():
        need = [f"{pre}_{k}" for pre in rotors.values() for k in ("rpm", "thrust", "shaft_power")]
        lack = [n for n in need if n not in outputs]
        if lack:
            missing[state] = lack
            continue
        states[state] = {}
        for inst, pre in rotors.items():
            p = adh_doc.find(doc, inst)["muas"]["propeller"]
            rpm, thrust, power = (outputs[f"{pre}_{k}"] for k in ("rpm", "thrust", "shaft_power"))
            ct, cp = disk_coefficients(thrust, power, rpm, float(p["diameter"]["value"]), rho)
            states[state][inst] = {"rpm": SPIN_SIGN[str(getattr(p["spin"], "value", p["spin"]))] * rpm, "ct": ct, "cp": cp,
                                   "thrust_N": thrust}
    return states, missing


def spec_from_doc(doc: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    wings = []
    for inst in st["wings"]:
        item = adh_doc.find(doc, inst)
        pf = item["muas"]["planform"]
        wings.append({"instance": inst, "position": list(pf["position"]["xyz"]), "rx_deg": pf.get("rx_deg", 0.0),
                      "ry_deg": pf.get("ry_deg", 0.0), "mirror": _mirror(pf),
                      "sections": [{k: s[k] for k in SECTION_KEYS + ("foil",)} for s in pf["sections"]],
                      "foils": {k: v.tolist() for k, v in foils_of(item).items()},
                      "controls": _controls(doc, inst, pf["sections"])})
    bodies = [{"instance": b, "frames": [f.tolist() for f in body_frames(adh_doc.find(doc, b)["geometry"]["body"])]}
              for b in body_items(st)]
    return {"wings": wings, "body": bodies[0] if bodies else None, "bodies": bodies,
            "parts": part_cylinders(doc, st.get("parts") or []), "rotors": rotor_geoms(doc, st.get("rotors") or []),
            "reference_meshes": []}


def vsp_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """The SPEC of `spec_from_doc` (design frame, FRD) in the frame of OpenVSP (x aft, z up). A copy."""
    out = copy.deepcopy(spec)
    for w in out["wings"]:
        w["position"] = flip_point(w["position"])
    for b in out["bodies"]:                         # out["body"] is the first of them: the same object
        b["frames"] = [flip_array(np.asarray(f)).tolist() for f in b["frames"]]
    for p in out["parts"] + out["rotors"]:
        p["p0"], p["axis"] = flip_point(p["p0"]), flip_point(p["axis"])
    return out


# ------------------------------------------------------------------------------------------------- shape gate
def _shape_sets(wings: Dict[str, Tuple[Dict[str, Any], Dict[str, np.ndarray]]],
                frames: Optional[List[Tuple[str, List[np.ndarray]]]]) -> List[Dict[str, Any]]:
    sets = []
    for inst, (pf, foils) in wings.items():
        pts = section_points(planform_wing(pf), foils)
        n = len(pts)
        u0 = np.concatenate([np.full(len(p), (i + 1) / (n + 1)) for i, p in enumerate(pts)])
        sets.append({"geom": inst, "points": flip_array(np.vstack(pts)).tolist(), "u0": u0.tolist()})
    if frames and isinstance(frames[0], str):       # one body as (instance, frames): the old form
        frames = [frames]
    for inst, fr in frames or []:
        sets.append({"geom": inst, "points": flip_array(np.vstack(fr)).tolist()})
    return sets


def shape_gaps(path: Path, wings, frames) -> Dict[str, float]:
    """The largest gap (m) from the ADH shape of each item to the OpenVSP surface of the model."""
    sets = _shape_sets(wings, frames)
    d = runner.run({"job": "project", "path": str(path), "sets": sets})["distances"]
    return {s["geom"]: float(max(v)) for s, v in zip(sets, d)}


# --------------------------------------------------------------------------------------------------- generate
def generate(doc: Dict[str, Any], ctx: Context) -> List[Path]:
    """Write work/<aircraft>/generated/<aircraft>.vsp3 (and the skin STL) from the document."""
    from aeroplan.parts import mesh_name, skin_mesh
    from aeroplan.visual import write_stl

    st = ctx.settings()
    out = ctx.work / "generated"
    out.mkdir(parents=True, exist_ok=True)
    spec = spec_from_doc(doc, st)
    files = []
    skin = None
    if st.get("reference_skin"):
        item = adh_doc.find(doc, st["reference_skin"])
        skin = skin_mesh(doc, item, ctx.root)
        if skin is None:
            why = ("the .muas file holds no skin for it (the CREO spoke records it)" if not item["muas"].get("skin")
                   else f"{mesh_name(doc, item['muas']['skin']['mesh'])} is not on this machine (or changed)")
            print(f"OpenVSP: no reference mesh for {st['reference_skin']}: {why}.")
        else:
            from aeroplan.skin_body import repair_for_panel

            skin, fixed = repair_for_panel(skin)    # the panel solver of VSPAERO needs a manifold mesh
            if any(fixed.values()):
                print(f"OpenVSP: skin {st['reference_skin']} repaired for VSPAERO: {fixed['flap_triangles']} flap "
                      f"triangles removed, {fixed['needles']} needle triangles removed, {fixed['tjunction_splits']} "
                      "triangles split at T-junctions (volume unchanged).")
            stl = out / f"{st['reference_skin']}_skin.stl"
            stl.write_bytes(write_stl(flip_array(skin.reshape(-1, 3)).reshape(-1, 3, 3),
                                      f"{st['reference_skin']} CAD skin, OpenVSP frame (x aft, z up), m"))
            spec["reference_meshes"].append({"name": f"{st['reference_skin']}_skin", "stl": str(stl)})
            files.append(stl)
    path = out / f"{ctx.aircraft}.vsp3"
    runner.run({"job": "write", "spec": vsp_spec(spec), "path": str(path)})
    files.insert(0, path)
    wings = {w["instance"]: (adh_doc.find(doc, w["instance"])["muas"]["planform"],
                             {k: np.asarray(v) for k, v in w["foils"].items()}) for w in spec["wings"]}
    frames = []
    for b in spec["bodies"]:
        fr = [np.asarray(f) for f in b["frames"]]
        if len(fr) > 30:        # projecting every point of a dense body takes minutes: sample the frames
            keep = sorted(set(range(0, len(fr), 4)) | {len(fr) - 1})
            print(f"OpenVSP: shape check of {b['instance']} on {len(keep)} of {len(fr)} frames (ingest checks all frames).")
            fr = [fr[i] for i in keep]
        frames.append((b["instance"], fr))
    for inst, gap in shape_gaps(path, wings, frames).items():
        print(f"OpenVSP: largest gap from the ADH shape of {inst} to the OpenVSP surface: {gap * 1e6:.2f} um")
    if skin is not None and spec["bodies"]:
        u = np.linspace(0.02, 0.98, 49)
        w = np.linspace(0.0, 1.0, 37)
        uu, ww = np.meshgrid(u, w)
        pts = runner.run({"job": "probe", "path": str(path), "geom": st["reference_skin"],
                          "u": uu.ravel().tolist(), "w": ww.ravel().tolist()})["points"]
        d = distance_to_mesh(flip_array(np.array(pts)), skin)
        print(f"OpenVSP: gap from the OpenVSP fuselage to the CAD skin: largest {d.max() * 1e3:.1f} mm, "
              f"RMS {np.sqrt(np.mean(d ** 2)) * 1e3:.1f} mm ({len(d)} surface points)")
    return files


# ----------------------------------------------------------------------------------------------------- ingest
def _foil_name(new: np.ndarray, old: Dict[str, np.ndarray], prefer: Optional[str], fallback: str) -> str:
    """The document name of a read foil: the same name when the points are the same, else a new name."""
    for name in ([prefer] if prefer else []) + sorted(old):
        o = old.get(name)
        if o is not None and o.shape == new.shape and np.allclose(o, new, rtol=0.0, atol=1e-12):
            return name
    return fallback


def _wing_from_spec(w: Dict[str, Any], item: Dict[str, Any], model: str) -> Tuple[Dict[str, Any], Dict[str, np.ndarray]]:
    """(new planform, foils) of a read wing. Values that OpenVSP does not hold stay as they are in the document."""
    old_pf = item["muas"]["planform"]
    old_foils = foils_of(item)
    if w["mirror"] != _mirror(old_pf):
        raise ValueError(f"OpenVSP {w['instance']}: the planar symmetry changed. The spoke does not change it")
    secs, foils = [], {}
    for i, s in enumerate(w["sections"]):
        f = np.asarray(w["foils"][s["foil"]], float)
        prefer = old_pf["sections"][i]["foil"] if i < len(old_pf["sections"]) else None
        name = _foil_name(f, old_foils, prefer, f"{w['instance']} s{i} (OpenVSP)")
        foils[name] = old_foils.get(name, f)
        secs.append({**{k: float(s[k]) for k in SECTION_KEYS}, "foil": name})
    if len(secs) == len(old_pf["sections"]):
        secs[-1]["dihedral_deg"] = old_pf["sections"][-1]["dihedral_deg"]   # sets no panel: OpenVSP has no slot for it
    pf = {**old_pf, "position": {**old_pf["position"], "xyz": flip_point(w["position"])},
          "rx_deg": float(w["rx_deg"]), "ry_deg": float(w["ry_deg"]), "sections": secs,
          "source": f"OpenVSP model {model}", "placeholder": False}
    return pf, foils


def _planform_changes(inst: str, old: Dict[str, Any], new: Dict[str, Any], old_foils, new_foils) -> List[str]:
    out = []
    for k, unit in (("rx_deg", "deg"), ("ry_deg", "deg")):
        if abs(old.get(k, 0.0) - new[k]) > VALUE_TOL:
            out.append(f"{inst}: {k} {old.get(k, 0.0):g} -> {new[k]:g} {unit}")
    for a, b, ax in zip(old["position"]["xyz"], new["position"]["xyz"], "xyz"):
        if abs(a - b) > VALUE_TOL:
            out.append(f"{inst}: root position {ax} {a:g} -> {b:g} m")
    if len(old["sections"]) != len(new["sections"]):
        out.append(f"{inst}: {len(old['sections'])} -> {len(new['sections'])} sections")
        return out
    for i, (a, b) in enumerate(zip(old["sections"], new["sections"])):
        for k in SECTION_KEYS:
            if abs(a[k] - b[k]) > VALUE_TOL:
                out.append(f"{inst}: section {i} {k} {a[k]:g} -> {b[k]:g} {'deg' if k.endswith('deg') else 'm'}")
        fa, fb = old_foils[a["foil"]], new_foils[b["foil"]]
        if a["foil"] != b["foil"] or fa.shape != fb.shape or not np.allclose(fa, fb, rtol=0.0, atol=1e-12):
            out.append(f"{inst}: section {i} foil {a['foil']!r} -> {b['foil']!r}")
    return out


def ingest(doc: Dict[str, Any], ctx: Context):
    st = ctx.settings()
    if not st:
        return None
    path = ctx.work / st.get("model", f"{ctx.aircraft}.vsp3")
    if not path.is_file():
        return None
    ref = ctx.source_ref(path, "OpenVSP model (the member's changed copy)")
    air = adh_doc.node(doc, "1.2")
    if any(r["tool"] == NAME and r["asset"] == ref["asset"] for r in air["muas"].get("sources") or []):
        return []
    spec = runner.run({"job": "read", "path": str(path), "n_half": _n_half(doc, st)})["spec"]
    if spec["other"]:
        raise ValueError(f"OpenVSP model {path.name}: components with no ADH item: "
                         f"{', '.join(o['name'] + ' (' + o['type'] + ')' for o in spec['other'])}")
    by_name = {w["instance"]: w for w in spec["wings"]}
    unknown = sorted(set(by_name) - set(st["wings"]))
    missing = sorted(set(st["wings"]) - set(by_name))
    if unknown or missing:
        raise ValueError(f"OpenVSP model {path.name}: wings {unknown} are not in the settings, wings {missing} are "
                         "missing. Name each OpenVSP wing by its ADH instance")
    changes: List[str] = []
    new_wings: Dict[str, Tuple[Dict[str, Any], Dict[str, np.ndarray]]] = {}
    changed_items: List[int] = []
    for inst in st["wings"]:
        item = adh_doc.find(doc, inst)
        pf, foils = _wing_from_spec(by_name[inst], item, path.name)
        new_wings[inst] = (pf, foils)
        diff = _planform_changes(inst, item["muas"]["planform"], pf, foils_of(item), foils)
        if diff:
            changes += diff
            changed_items.append(id(item))
    frames = []
    read_bodies = {b["instance"]: b for b in spec["bodies"]}
    for b in body_items(st):
        if b not in read_bodies:
            raise ValueError(f"OpenVSP model {path.name}: no fuselage named {b!r}")
        frames.append((b, [flip_array(np.asarray(f, float)) for f in read_bodies[b]["frames"]]))
    extra = sorted(set(read_bodies) - set(body_items(st)))
    if extra:
        raise ValueError(f"OpenVSP model {path.name}: fuselages {extra} are not in the settings")
    gaps = shape_gaps(path, new_wings, frames)
    bad = {k: v for k, v in gaps.items() if v > SHAPE_TOL}
    if bad:
        raise ValueError(f"OpenVSP model {path.name}: the ADH form cannot hold the shape of "
                         f"{', '.join(f'{k} (gap {v * 1e3:.3f} mm)' for k, v in bad.items())}. Change it with the "
                         "wing section values, the foils and the fuselage sections only")

    # write the changed wings
    for inst in st["wings"]:
        item = adh_doc.find(doc, inst)
        if id(item) not in changed_items:
            continue
        pf, foils = new_wings[inst]
        item["muas"]["planform"] = pf
        item.setdefault("geometry", {})["lifting_surface"] = lifting_surface_adh(planform_wing(pf), foils)
        item["muas"]["geometry_tool"] = NAME
        set_sources(item, NAME, [ref])

    # control surfaces
    for w in spec["wings"]:
        secs = new_wings[w["instance"]][0]["sections"]
        for c in w["controls"]:
            eta = [round(eta_from_vsp(secs, e), 12) for e in c["eta"]]
            for name in c["name"].split("+"):
                item = adh_doc.find(doc, name)
                cs = item["muas"].get("control_surface")
                if not cs or cs["parent"] != w["instance"]:
                    raise ValueError(f"OpenVSP control surface {name!r} is not a control surface of {w['instance']}")
                old = (list(cs["eta_span"]), cs["hinge_x_over_c"])
                if max(abs(a - b) for a, b in zip(old[0], eta)) > VALUE_TOL or abs(old[1] - c["hinge_x_over_c"]) > VALUE_TOL:
                    cs["eta_span"] = eta
                    cs["hinge_x_over_c"] = round(c["hinge_x_over_c"], 12)
                    item["muas"]["geometry_tool"] = NAME
                    set_sources(item, NAME, [ref])
                    changes.append(f"{name}: eta_span {old[0]} -> {eta}, hinge_x_over_c {old[1]:g} -> "
                                   f"{cs['hinge_x_over_c']:g}")

    # bodies
    for inst, fr in frames:
        item = adh_doc.find(doc, inst)
        old = body_frames(item["geometry"]["body"])
        if len(old) != len(fr) or any(a.shape != b.shape or np.abs(a - b).max() > VALUE_TOL for a, b in zip(old, fr)):
            item["geometry"]["body"] = body_adh(fr)
            item["muas"]["geometry_tool"] = NAME
            set_sources(item, NAME, [ref])
            changes.append(f"{inst}: body of {len(fr)} frames from OpenVSP (was {len(old)} frames)")

    set_sources(air, NAME, [ref])
    if not changes:
        changes.append(f"model {path.name} read: no geometry change (largest shape gap "
                       f"{max(gaps.values()) * 1e6:.2f} um)")
    return changes


# ----------------------------------------------------------------------------------------------------- analysis
ISA_SOUND_SPEED = 340.294      # m/s, ISA 1976 sea level (the speed of sound at 288.15 K)
ISA_DENSITY = 1.225            # kg/m3, ISA 1976 sea level


def _fit(x: np.ndarray, y: np.ndarray) -> Optional[Tuple[float, float]]:
    """(slope, intercept) of a least squares line, or None when fewer than 3 finite points."""
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return None
    s, i = np.polyfit(x[ok], y[ok], 1)
    return float(s), float(i)


def _rows(res: Dict[str, Any], key: str) -> np.ndarray:
    return np.array([r[key] for r in res["rows"]], float)


def summarize(alpha_res: Dict[str, Any], beta_res: Dict[str, Any], alpha_trim: float, x_ref: float, c_ref: float,
              window_deg: float = 4.0) -> Dict[str, Any]:
    """Derivatives of one configuration: CLa, Cma, NP_x (alpha sweep, within +-window of the trim alpha) and Cnb, Cyb, Clb
    (beta sweep). Slopes per radian. VSPAERO moments: CMytot pitch (nose up positive), CMxtot and CMztot (signs flipped).
    `x_ref` and NP_x are in the design frame (FRD, x forward). A stable aircraft has Cma < 0, so the neutral point is
    behind the reference point (lower x): NP_x = x_ref + c_ref Cma / CLa."""
    out: Dict[str, Any] = {}
    a = _rows(alpha_res, "AoA")
    near = np.abs(a - alpha_trim) <= window_deg + 1e-9
    k = 180.0 / math.pi
    fits = {}
    for name, col in (("CL", "CLtot"), ("Cm", "CMytot"), ("CD", "CDtot")):
        f = _fit(a[near], _rows(alpha_res, col)[near])
        fits[name] = f
    if fits["CL"] and fits["Cm"]:
        cla, cma = fits["CL"][0] * k, fits["Cm"][0] * k
        out.update({"CLa": cla, "Cma": cma, "CL0": fits["CL"][1], "Cm0": fits["Cm"][1], "NP_x": x_ref + c_ref * cma / cla,
                    "alpha_window_deg": [alpha_trim - window_deg, alpha_trim + window_deg]})
        out["CL_at_trim"] = fits["CL"][0] * alpha_trim + fits["CL"][1]
        out["Cm_at_trim"] = fits["Cm"][0] * alpha_trim + fits["Cm"][1]
    b = _rows(beta_res, "Beta")
    # The OpenVSP axes are x aft, y right, z up. A moment about the aft x axis is a roll to the left, and a moment about
    # the up z axis is a yaw to the left. The aeronautical Cl and Cn are the negative of CMx and CMz.
    for name, col, sign in (("Cyb", "CStot", 1.0), ("Clb", "CMxtot", -1.0), ("Cnb", "CMztot", -1.0)):
        f = _fit(b, _rows(beta_res, col))
        if f:
            out[name] = sign * f[0] * k
    return out


def _flow5_reference(ctx: Context) -> Dict[str, Any]:
    """The flow5 trim point (speed, alpha) and the derivatives of the flow5 sweep, from the flow5 settings sweep."""
    from aeroplan.spokes import context

    c5 = context("flow5", ctx.aircraft)
    st = c5.settings()
    f = c5.work / "sweeps" / str(st.get("sweep", "")) / "results.json"
    if not f.is_file():
        raise ValueError(f"no flow5 sweep results at {f}: the OpenVSP analysis takes the trim point and the ranges "
                         "from the flow5 sweep")
    res = json.loads(f.read_text(encoding="utf-8"))
    return {"sweep": st["sweep"], "speed_m_s": float(res["speed"]), "alpha_deg": float(res["alpha_deg"]),
            "ranges": (st.get("sweep_runner") or {}).get("ranges") or {}, "summaries": res.get("summaries") or {},
            "inputs": res.get("inputs") or {}}


def _adh_reference(cond: Dict[str, Any], outputs: Dict[str, float]) -> Dict[str, Any]:
    """The flight condition from the settings and the ADH sizing outputs (no flow5 sweep): speed from the output named
    by `speed_output`; the alpha and beta ranges and the alpha of the beta sweep are choices of the analysis."""
    name = cond["speed_output"]
    if name not in outputs:
        raise ValueError(f"the ADH sizing outputs have no {name!r} (the speed of the analysis): run `aeroplan build` again")
    return {"sweep": None, "speed_m_s": outputs[name], "alpha_deg": float(cond["beta_alpha_deg"]),
            "ranges": {"alpha_deg": cond["alpha_deg"], "beta_deg": cond["beta_deg"]}, "summaries": {}, "inputs": {},
            "source": f"ADH sizing output {name}"}


def point_summary(row: Dict[str, float], case: Dict[str, Any], alpha_deg: float) -> Dict[str, Any]:
    """The forces (N) and moments (N m, about the MRP) of one VSPAERO point, in the design frame (FRD: x forward, y
    right, z down). VSPAERO gives x aft, z up: x and z change sign. CF and CM are per q S, q S b or q S c with q from the
    speed of the case."""
    q = 0.5 * case["rho"] * case["vinf"] ** 2
    s, b, c = case["sref"], case["bref"], case["cref"]
    return {"speed_m_s": case["vinf"], "alpha_deg": alpha_deg, "q_Pa": q,
            "force_N": {"x": -row["CFxtot"] * q * s, "y": row["CFytot"] * q * s, "z": -row["CFztot"] * q * s},
            "moment_Nm": {"x": -row["CMxtot"] * q * s * b, "y": row["CMytot"] * q * s * c, "z": -row["CMztot"] * q * s * b},
            "rotor_thrust_N": sum(v["thrust_N"] for v in (case.get("rotors") or {}).values())}


def _range(r: List[float]) -> List[float]:
    start, end, step = float(r[0]), float(r[1]), float(r[2])
    return [start, end, int(round((end - start) / step)) + 1]


def sweep(doc: Dict[str, Any], ctx: Context, name: Optional[str] = None, only: Optional[List[str]] = None,
          dry_run: bool = False, keep: bool = False, timeout: float = 3600, **_ignored) -> Dict[str, Any]:
    """OpenVSP preliminary analysis of the ADH geometry: CompGeom (wetted area, volume), parasite drag, and the
    VSPAERO sweeps (alpha, beta) of the wings alone (VLM), the wings with the ADH body, and the wings with the raw
    CAD skin (panel). The flight condition, the ranges and the moment reference point come from the flow5 sweep of the
    settings, so the two tools run the same case. Writes work/<aircraft>/sweeps/<name>/results.json."""
    import datetime

    st = ctx.settings()
    an = st.get("analysis")
    if not an:
        raise ValueError(f"tools/openvsp/settings/{ctx.aircraft}.yaml has no `analysis` block")
    name = name or f"{ctx.aircraft}_{datetime.date.today().isoformat()}"
    dest = ctx.work / "sweeps" / name
    air = adh_doc.node(doc, "1.2")
    ref = air["muas"].get("reference")
    if not ref:
        raise ValueError("node 1.2 has no muas.reference: run the flow5 ingest first")
    s_ref, b_ref, c_ref = (float(ref[k]["value"]) for k in ("s_ref", "b_ref", "c_ref"))
    mrp = [float(v) for v in ref["mrp"]["point"]["xyz"]]
    cond = an.get("condition") or {}
    outputs = sizing_outputs(doc)
    f5 = _adh_reference(cond, outputs) if cond.get("source") == "adh" else _flow5_reference(ctx)
    states, missing = disk_states(doc, st, ISA_DENSITY)
    rg = f5["ranges"]
    alpha_rng, beta_rng = _range(rg["alpha_deg"]), _range(rg["beta_deg"])
    mach = f5["speed_m_s"] / ISA_SOUND_SPEED
    mrp_vsp = flip_point(mrp)                      # VSPAERO takes the reference point in the OpenVSP frame
    base = {"sref": s_ref, "bref": b_ref, "cref": c_ref, "xcg": mrp_vsp[0], "ycg": mrp_vsp[1], "zcg": mrp_vsp[2], "mach": mach,
            "vinf": f5["speed_m_s"], "rho": ISA_DENSITY, "wake_iter": int(an.get("wake_iterations", 3)),
            "fixed_wake": True, "ncpu": an.get("ncpu")}
    sets = {k: list(v) for k, v in (an.get("sets") or {}).items()}
    runs = [r for r in an["runs"] if not only or r["name"] in only]
    model = ctx.work / "generated" / f"{ctx.aircraft}.vsp3"
    tree = ctx.root / "aircraft" / ctx.aircraft
    current = (model.is_file() and tree.is_dir()
               and model.stat().st_mtime > max(f.stat().st_mtime for f in tree.rglob("*") if f.is_file()))
    if not dry_run and not current:         # generate takes minutes (the shape gate): reuse a model newer than the tree
        model = generate(doc, ctx)[0]
    elif not model.is_file():
        raise ValueError(f"{model} does not exist: run `aeroplan generate OpenVSP {ctx.aircraft}` first")
    result: Dict[str, Any] = {
        "name": name, "aircraft": ctx.aircraft, "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"), "model": model.name, "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "aircraft_version": ctx.acft.version if ctx.acft is not None else None, "tool": runner.run({"job": "version"})["version"],
        "condition": {"speed_m_s": f5["speed_m_s"], "mach": mach, "alpha_trim_deg": f5["alpha_deg"],
                      "atmosphere": "ISA 1976 sea level", "rho_kg_m3": ISA_DENSITY,
                      "source": f5.get("source") or f"flow5 sweep {f5['sweep']}"},
        "reference": {"s_ref_m2": s_ref, "b_ref_m": b_ref, "c_ref_m": c_ref, "mrp_xyz_m": mrp},
        "ranges": {"alpha_deg": alpha_rng, "beta_deg": beta_rng}, "geometry": {}, "runs": {}, "summaries": {},
        "points": {}, "disk_states": states, "failed": {}, "warnings": {}, "notes": list(an.get("notes") or [])}
    if dry_run:
        result.update({"dry_run": True, "planned_runs": [r["name"] for r in runs], "sets": sets})
        return result

    # geometry: wetted area and volume, parasite drag, for each analysis set
    for label, set_name in (an.get("geometry_sets") or {}).items():
        if only and label not in only and "geometry" not in only:
            continue
        try:
            result["geometry"][label] = {
                "set": set_name, "compgeom": runner.run({"job": "compgeom", "path": str(model), "sets": sets,
                                                          "set": set_name}, timeout=timeout),
                "parasite_drag": runner.run({"job": "parasite_drag", "path": str(model), "sets": sets, "set": set_name,
                                             "cond": {"sref": s_ref, "vinf": f5["speed_m_s"],
                                                      "altitude_m": float(an.get("altitude_m", 0.0))}},
                                            timeout=timeout)}
            for k in ("ok",):
                result["geometry"][label]["compgeom"].pop(k, None)
                result["geometry"][label]["parasite_drag"].pop(k, None)
        except runner.OpenVSPError as e:
            result["failed"][f"geometry:{label}"] = str(e).splitlines()[0]

    # VSPAERO sweeps
    raw = dest / "raw"
    for r in runs:
        got = {}
        run_base = dict(base)
        if r.get("state") and r["state"] not in states:
            if r["state"] not in missing:
                raise ValueError(f"run {r['name']}: the settings have no disk_states entry {r['state']!r}")
            result["warnings"][r["name"]] = (f"no operating point {r['state']}: the ADH sizing outputs lack "
                                             f"{', '.join(missing[r['state']])} (run `aeroplan build` again)")
            continue
        if st.get("rotors"):
            run_base["rotors"] = states[r["state"]] if r.get("state") else {}
        if r.get("speed_m_s"):
            run_base.update({"vinf": float(r["speed_m_s"]), "mach": float(r["speed_m_s"]) / ISA_SOUND_SPEED})
        if r.get("point"):
            a0 = float(r.get("alpha_deg", 0.0))
            try:
                res = runner.run({"job": "vspaero", "path": str(model), "dir": str(raw), "name": r["name"], "sets": sets,
                                  "thin": r.get("thin"), "thick": r.get("thick"),
                                  "case": {**run_base, "alpha": [a0, a0, 1], "beta": [0.0, 0.0, 1]}}, timeout=timeout)
                res.pop("ok", None)
                result["runs"][r["name"]] = {"point": res}
                result["points"][r["name"]] = point_summary(res["rows"][0], run_base, a0)
            except runner.OpenVSPError as e:
                (result["warnings"] if r.get("optional") else result["failed"])[r["name"]] = str(e).splitlines()[0]
            continue
        for kind, case in (("alpha", {**run_base, "alpha": alpha_rng, "beta": [0.0, 0.0, 1]}),
                           ("beta", {**run_base, "alpha": [f5["alpha_deg"]] * 2 + [1], "beta": beta_rng})):
            try:
                res = runner.run({"job": "vspaero", "path": str(model), "dir": str(raw), "name": f"{r['name']}_{kind}",
                                  "sets": sets, "thin": r.get("thin"), "thick": r.get("thick"), "case": case},
                                 timeout=timeout)
                res.pop("ok", None)
                got[kind] = res
            except runner.OpenVSPError as e:
                (result["warnings"] if r.get("optional") else result["failed"])[f"{r['name']}:{kind}"] = str(e).splitlines()[0]
        result["runs"][r["name"]] = {k: {kk: v for kk, v in g.items() if kk != "rows"} | {"rows": g["rows"]}
                                     for k, g in got.items()}
        if "alpha" in got and "beta" in got:
            result["summaries"][r["name"]] = summarize(got["alpha"], got["beta"], f5["alpha_deg"], mrp[0], c_ref)
            if not np.isfinite(_rows(got["alpha"], "CLtot")).all() or not np.isfinite(_rows(got["beta"], "CMztot")).all():
                (result["warnings"] if r.get("optional") else result["failed"])[r["name"]] = (
                    "VSPAERO returned NaN: the panel solution did not converge")
                result["summaries"].pop(r["name"], None)
    if f5.get("sweep"):
        result["flow5"] = {"sweep": f5["sweep"], "alpha": (f5["summaries"].get("alpha") or {}),
                           "t7": (f5["summaries"].get("t7_reference") or {})}
    result["validation"] = {"ok": not result["failed"] and bool(result["summaries"] or result["points"]), "failed": result["failed"],
                            "warnings": result["warnings"]}
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "results.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def format_sweep(res: Dict[str, Any]) -> str:
    """A text table of an OpenVSP sweep result."""
    out = [f"OpenVSP analysis {res['name']} ({res['tool']}), model {res['model']}",
           f"  condition: V {res['condition']['speed_m_s']:.3f} m/s, Mach {res['condition']['mach']:.4f}, trim alpha "
           f"{res['condition']['alpha_trim_deg']:.2f} deg, {res['condition']['atmosphere']} ({res['condition']['source']})",
           f"  MRP x {res['reference']['mrp_xyz_m'][0]:.4f} m, c_ref {res['reference']['c_ref_m']:.3f} m"]
    if res.get("dry_run"):
        return "\n".join(out + [f"  dry run: planned runs {', '.join(res['planned_runs'])}"])
    if res["geometry"]:
        out.append("  geometry (CompGeom, parasite drag):")
        for label, g in res["geometry"].items():
            out.append(f"    {label:12s} Swet {g['compgeom']['total_wet_area_m2']:.4f} m2  volume "
                       f"{g['compgeom']['total_theo_volume_m3']:.5f} m3  CD0 {g['parasite_drag']['cd0']:.5f}")
    cols = ("CLa", "Cma", "CL0", "Cm0", "NP_x", "Cnb", "Cyb", "Clb")
    out.append("  derivatives (per rad):  " + "".join(f"{c:>9s}" for c in cols))
    for run, s in res["summaries"].items():
        out.append(f"    {run:20s}   " + "".join(f"{s.get(c, float('nan')):9.4f}" for c in cols))
    f5 = res.get("flow5", {})
    if f5.get("alpha"):
        a, t = f5["alpha"], f5.get("t7") or {}
        out.append(f"    {'flow5 ' + f5['sweep']:20s}   " + "".join(
            f"{v:9.4f}" if v is not None else f"{'':>9s}" for v in (a.get("CLa"), a.get("Cma"), None, None,
                                                                    None if t.get("NP_x") is None else -t["NP_x"], t.get("Cnb"), None, None)))   # flow5 x aft -> FRD
    for run, p in res.get("points", {}).items():
        out.append(f"  point run {run}: V {p['speed_m_s']:.2f} m/s, alpha {p['alpha_deg']:.1f} deg, rotor thrust "
                   f"{p['rotor_thrust_N']:.1f} N; wing and body force x/y/z "
                   + " ".join(f"{p['force_N'][a]:+.2f}" for a in "xyz") + " N, moment x/y/z "
                   + " ".join(f"{p['moment_Nm'][a]:+.2f}" for a in "xyz") + " N m")
    for k, v in res.get("failed", {}).items():
        out.append(f"  FAILED {k}: {v}")
    for k, v in res.get("warnings", {}).items():
        out.append(f"  WARNING (optional run) {k}: {v}")
    out.append("  validation: " + ("PASS" if res["validation"]["ok"] else "FAIL"))
    return "\n".join(out)


def _n_half(doc: Dict[str, Any], st: Dict[str, Any]) -> int:
    return max([len(body_frames(adh_doc.find(doc, b)["geometry"]["body"])[0]) for b in body_items(st)] or [13])


def setup(ctx: Context, vsp: Optional[str] = None) -> Dict[str, str]:
    """Make the OpenVSP Python for this machine (see runner.setup)."""
    return runner.setup(vsp, expected=str(ctx.settings().get("vsp_version") or ""))


def describe() -> str:
    return runner.describe()
