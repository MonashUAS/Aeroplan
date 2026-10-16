"""OpenVSP spoke: the ADH geometry -> an OpenVSP model (.vsp3), and a changed OpenVSP model -> the ADH geometry.

OpenVSP runs in its own Python (tools/openvsp/.venv, made by `python -m aeroplan setup OpenVSP`). runner.py sends each job to
vsp_worker.py. The worker holds the rules between the flow5 planform form and the OpenVSP wing form.

Input (git ignores it): work/openvsp/<aircraft>/<model>, the member's OpenVSP model (a copy of the generated model,
changed in the OpenVSP GUI).
Settings (committed): tools/openvsp/settings/<aircraft>.yaml
    vsp_version     the OpenVSP version that the tests ran with (setup warns on another version)
    model           the file name of the member's model in the work folder
    wings           the ADH items (muas.instance) with a planform that go into OpenVSP
    body            the ADH item with the fuselage body
    reference_skin  the item whose CAD skin (muas.skin) goes into the model as a reference mesh

What generate writes (work/<aircraft>/generated/): <aircraft>.vsp3 and <skin item>_skin.stl (the skin in the design
frame, m). It gives the gap from the OpenVSP fuselage surface to the skin.

What sweep writes (`aeroplan sweep OpenVSP <aircraft>`): work/<aircraft>/sweeps/<name>/results.json and the raw VSPAERO
files. The analysis settings are in the `analysis` block: user sets of components, the CompGeom and parasite drag sets,
and the VSPAERO runs (thin = VLM set, thick = panel set). The trim point and the ranges come from the flow5 sweep.

What ingest writes, only for the items that differ from the document (the changed file wins):
  - wings: `muas.planform` sections, position and angles, `geometry.lifting_surface`, the foils
  - control surfaces: `muas.control_surface` eta_span and hinge_x_over_c
  - body: `geometry.body`
  - `muas.geometry_tool = "OpenVSP"` and an OpenVSP pointer on each changed item. The air vehicle gets the pointer of
    the model it read. When the model sha256 equals that pointer, ingest reads nothing.
Before it writes, ingest puts the ADH shape of each item on the OpenVSP surface. A gap above SHAPE_TOL stops the build:
the model then holds a change that the ADH form cannot hold.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from aeroplan import adh_doc
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
    spec: Dict[str, Any] = {"wings": wings, "body": None, "reference_meshes": []}
    if st.get("body"):
        body = adh_doc.find(doc, st["body"])["geometry"]["body"]
        spec["body"] = {"instance": st["body"], "frames": [f.tolist() for f in body_frames(body)]}
    return spec


# ------------------------------------------------------------------------------------------------- shape gate
def _shape_sets(wings: Dict[str, Tuple[Dict[str, Any], Dict[str, np.ndarray]]],
                frames: Optional[Tuple[str, List[np.ndarray]]]) -> List[Dict[str, Any]]:
    sets = []
    for inst, (pf, foils) in wings.items():
        pts = section_points(planform_wing(pf), foils)
        n = len(pts)
        u0 = np.concatenate([np.full(len(p), (i + 1) / (n + 1)) for i, p in enumerate(pts)])
        sets.append({"geom": inst, "points": np.vstack(pts).tolist(), "u0": u0.tolist()})
    if frames:
        sets.append({"geom": frames[0], "points": np.vstack(frames[1]).tolist()})
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
            stl.write_bytes(write_stl(skin, f"{st['reference_skin']} CAD skin, design frame, m"))
            spec["reference_meshes"].append({"name": f"{st['reference_skin']}_skin", "stl": str(stl)})
            files.append(stl)
    path = out / f"{ctx.aircraft}.vsp3"
    runner.run({"job": "write", "spec": spec, "path": str(path)})
    files.insert(0, path)
    wings = {w["instance"]: (adh_doc.find(doc, w["instance"])["muas"]["planform"],
                             {k: np.asarray(v) for k, v in w["foils"].items()}) for w in spec["wings"]}
    frames = (spec["body"]["instance"], [np.asarray(f) for f in spec["body"]["frames"]]) if spec["body"] else None
    if frames and len(frames[1]) > 30:          # projecting every point of a dense body takes minutes: sample the frames
        keep = sorted(set(range(0, len(frames[1]), 4)) | {len(frames[1]) - 1})
        frames = (frames[0], [frames[1][i] for i in keep])
        print(f"OpenVSP: shape check of the body on {len(keep)} of {len(spec['body']['frames'])} frames "
              "(ingest checks all frames).")
    for inst, gap in shape_gaps(path, wings, frames).items():
        print(f"OpenVSP: largest gap from the ADH shape of {inst} to the OpenVSP surface: {gap * 1e6:.2f} um")
    if skin is not None and spec["body"]:
        u = np.linspace(0.02, 0.98, 49)
        w = np.linspace(0.0, 1.0, 37)
        uu, ww = np.meshgrid(u, w)
        pts = runner.run({"job": "probe", "path": str(path), "geom": spec["body"]["instance"],
                          "u": uu.ravel().tolist(), "w": ww.ravel().tolist()})["points"]
        d = distance_to_mesh(np.array(pts), skin)
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
    pf = {**old_pf, "position": {**old_pf["position"], "xyz": [float(v) for v in w["position"]]},
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
    frames = None
    if st.get("body"):
        if not spec["body"] or spec["body"]["instance"] != st["body"]:
            raise ValueError(f"OpenVSP model {path.name}: no fuselage named {st['body']!r}")
        frames = (st["body"], [np.asarray(f, float) for f in spec["body"]["frames"]])
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

    # body
    if frames:
        item = adh_doc.find(doc, st["body"])
        old = body_frames(item["geometry"]["body"])
        if len(old) != len(frames[1]) or any(a.shape != b.shape or np.abs(a - b).max() > VALUE_TOL
                                             for a, b in zip(old, frames[1])):
            item["geometry"]["body"] = body_adh(frames[1])
            item["muas"]["geometry_tool"] = NAME
            set_sources(item, NAME, [ref])
            changes.append(f"{st['body']}: body of {len(frames[1])} frames from OpenVSP (was {len(old)} frames)")

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
    (beta sweep). Slopes per radian. VSPAERO moments: CMytot pitch (nose up positive), CMxtot and CMztot (signs flipped)."""
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
        out.update({"CLa": cla, "Cma": cma, "CL0": fits["CL"][1], "Cm0": fits["Cm"][1], "NP_x": x_ref - c_ref * cma / cla,
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
    f5 = _flow5_reference(ctx)
    rg = f5["ranges"]
    alpha_rng, beta_rng = _range(rg["alpha_deg"]), _range(rg["beta_deg"])
    mach = f5["speed_m_s"] / ISA_SOUND_SPEED
    base = {"sref": s_ref, "bref": b_ref, "cref": c_ref, "xcg": mrp[0], "ycg": mrp[1], "zcg": mrp[2], "mach": mach,
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
                      "atmosphere": "ISA 1976 sea level", "rho_kg_m3": ISA_DENSITY, "source": f"flow5 sweep {f5['sweep']}"},
        "reference": {"s_ref_m2": s_ref, "b_ref_m": b_ref, "c_ref_m": c_ref, "mrp_xyz_m": mrp},
        "ranges": {"alpha_deg": alpha_rng, "beta_deg": beta_rng}, "geometry": {}, "runs": {}, "summaries": {},
        "failed": {}, "warnings": {}, "notes": list(an.get("notes") or [])}
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
        for kind, case in (("alpha", {**base, "alpha": alpha_rng, "beta": [0.0, 0.0, 1]}),
                           ("beta", {**base, "alpha": [f5["alpha_deg"]] * 2 + [1], "beta": beta_rng})):
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
    result["flow5"] = {"sweep": f5["sweep"], "alpha": (f5["summaries"].get("alpha") or {}),
                       "t7": (f5["summaries"].get("t7_reference") or {})}
    result["validation"] = {"ok": not result["failed"] and bool(result["summaries"]), "failed": result["failed"],
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
                                                                    t.get("NP_x"), t.get("Cnb"), None, None)))
    for k, v in res.get("failed", {}).items():
        out.append(f"  FAILED {k}: {v}")
    for k, v in res.get("warnings", {}).items():
        out.append(f"  WARNING (optional run) {k}: {v}")
    out.append("  validation: " + ("PASS" if res["validation"]["ok"] else "FAIL"))
    return "\n".join(out)


def _n_half(doc: Dict[str, Any], st: Dict[str, Any]) -> int:
    if not st.get("body"):
        return 13
    return len(body_frames(adh_doc.find(doc, st["body"])["geometry"]["body"])[0])


def setup(ctx: Context, vsp: Optional[str] = None) -> Dict[str, str]:
    """Make the OpenVSP Python for this machine (see runner.setup)."""
    return runner.setup(vsp, expected=str(ctx.settings().get("vsp_version") or ""))


def describe() -> str:
    return runner.describe()
