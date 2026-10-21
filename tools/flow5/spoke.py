"""flow5 spoke: the flow5 sweep -> ADH geometry, reference, mass model, aero model and trim. The ADH document -> a
flow5 plane XML.

Input (git ignores it): work/flow5/<aircraft>/
    sweeps/<sweep>/        one sweep run of flow5 7.57: plane_with_body.xml, t7_reference.xml (the T7 analysis),
                           t7_reference_opoint.txt (the T7 point), alpha_viscous.csv, results.json
    plane/*.dat            the foils of the plane
Settings (committed): tools/flow5/settings/<aircraft>.yaml
    sweep                  the sweep that gives the data (the ground truth)
    foils                  the folder of the .dat files, relative to the work folder
    surfaces               flow5 surface name -> {node: WBS number, instance: muas.instance, subcomponent: true
                           when the surface is a subcomponent of the node (for example the fin under Stabilizer)}
    body                   {node, instance} of the body
    sweep_date             the date of the sweep run (the export does not record it)
    mesh                   panel counts for `generate`

What ingest writes:
  - each flow5 surface: `geometry.lifting_surface` (ADH) and `muas.planform` on its node
  - the body: `geometry.body` (ADH) on the fuselage node
    The changed file wins: the spoke writes the geometry of an item only when the flow5 files of that item (plane
    XML, foils) differ from the flow5 pointers on the item. So a later change from another geometry spoke (OpenVSP)
    stays until a new flow5 sweep. `muas.geometry_tool` names the spoke that wrote the geometry last.
  - air vehicle: `muas.point_masses`, `muas.mass_properties` (the T7 analysis mass model), `muas.reference`
    (the T7 analysis reference dimensions, MRP = the T7 CoG), the aero model (a dataset of role aero: DAVE-ML in
    ADH form, `aero.<aircraft>`), `muas.initial_conditions` (the T7 trim speed)
  - each raw file it read: an asset of the register (linked), named by `muas.sources`
"""
from __future__ import annotations

import copy
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from aeroplan import adh_doc
from aeroplan.adapters.flow5 import parse_polar_text
from aeroplan.adapters.flow5_geometry import read_foil, read_plane, read_t7_scalars
from aeroplan.aero_buildup import from_flow5, to_daveml
from aeroplan.daveml_adh import from_xml
from aeroplan.dml_validate import validate_dml
from aeroplan.frame import flip_point
from aeroplan.geometry import body_adh, body_frames, lifting_surface_adh
from aeroplan.spokes import Context, set_sources

from .plane_xml import read_body_and_masses, read_wing_masses, write_foil, write_plane
from .sweep import format_result as format_sweep  # noqa: F401  (the CLI prints the sweep with it)

NAME = "flow5"


def _t7_analysis(path: Path) -> Dict[str, Any]:
    """Reference dimensions and the custom inertia of a flow5 stability-polar XML."""
    root = ET.fromstring(path.read_bytes())
    pol = root.find("Polar")
    if pol is None or pol.findtext("Type") != "STABILITYPOLAR":
        raise ValueError(f"{path.name} is not a flow5 stability polar")
    rd = pol.find("Reference_Dimensions")
    inert = pol.find("Inertia")
    out = {"S": float(rd.findtext("Reference_Area")), "b": float(rd.findtext("Reference_Span_Length")),
           "c": float(rd.findtext("Reference_Chord_Length")), "ref_kind": rd.findtext("Reference_Dimensions"),
           "use_plane_inertia": pol.findtext("Use_plane_inertia") == "true"}
    out["mass"] = float(inert.findtext("Mass"))
    out["cog_flow5"] = [float(v) for v in inert.findtext("CoG").split(",")]     # flow5 axes: x aft, z up
    out["cog"] = flip_point(out["cog_flow5"])                                      # design frame (FRD)
    for k in ("Ixx", "Iyy", "Izz", "Ixz"):
        out[k] = float(inert.findtext(f"CoG_{k}"))
    return out


def _item(doc: Dict[str, Any], m: Dict[str, Any], description: str) -> Dict[str, Any]:
    """The item of a settings entry {node, instance, subcomponent?, name?}: the WBS node, or its subcomponent."""
    n = adh_doc.node(doc, m["node"], create=True)
    if not m.get("subcomponent", False):
        adh_doc.muas(n, m["instance"])
        if n["muas"]["instance"] != m["instance"]:
            raise ValueError(f"node {m['node']} carries {n['muas']['instance']!r}, the settings say {m['instance']!r}")
        return n
    for s in n.get("subcomponents") or []:
        if s["muas"]["instance"] == m["instance"]:
            return s
    return adh_doc.put_subcomponent(n, {"name": m.get("name", m["instance"]), "description": description,
                                        "muas": {"ext_version": adh_doc.MUAS_SCHEMA_VERSION, "instance": m["instance"]}})


def _same_files(item: Dict[str, Any], refs: List[Dict[str, Any]]) -> bool:
    """True when the item has geometry and its flow5 pointers name the same files with the same sha256."""
    old = {r["asset"] for r in (item.get("muas") or {}).get("sources") or [] if r["tool"] == NAME}
    return bool(item.get("geometry")) and old == {r["asset"] for r in refs}


def ingest(doc: Dict[str, Any], ctx: Context):
    st = ctx.settings()
    if not st or not (ctx.work / "sweeps" / st.get("sweep", "")).is_dir():
        return None
    sweep = ctx.work / "sweeps" / st["sweep"]
    plane_xml, t7_xml, t7_txt = sweep / "plane_with_body.xml", sweep / "t7_reference.xml", sweep / "t7_reference_opoint.txt"
    polar_csv, results = sweep / "alpha_viscous.csv", sweep / "results.json"
    foils_dir = ctx.work / st.get("foils", "plane")
    changes: List[str] = []
    plane = read_plane(plane_xml)
    wing_mass = read_wing_masses(plane_xml)
    plane_ref = ctx.source_ref(plane_xml, "plane definition of the sweep (wings, body, point masses)")

    # surfaces
    for w in plane.wings:
        m = st["surfaces"].get(w.name)
        if m is None:
            raise ValueError(f"flow5 surface {w.name!r} has no node in tools/flow5/settings/{ctx.aircraft}.yaml surfaces")
        foils = {s.foil: read_foil(foils_dir, s.foil) for s in w.sections}
        item = _item(doc, m, f"{w.name} (flow5 surface)")
        refs = [plane_ref] + [ctx.source_ref(next(p for p in foils_dir.glob("*.dat") if p.stem.lower() == f.lower()),
                                             f"foil {f}") for f in sorted(foils)]
        if _same_files(item, refs):
            item["muas"].setdefault("geometry_tool", NAME)
            if item["muas"]["geometry_tool"] != NAME:
                changes.append(f"{m['instance']}: geometry kept from {item['muas']['geometry_tool']} (the flow5 files "
                               "are the recorded ones)")
            continue
        item.setdefault("geometry", {})["lifting_surface"] = lifting_surface_adh(w, foils)
        item["muas"]["planform"] = {
            "surface_name": w.name, "kind": w.kind, "position": {"xyz": list(w.position)}, "rx_deg": w.rx_deg,
            "ry_deg": w.ry_deg, "symmetric": w.symmetric, "two_sided": w.two_sided,
            "sections": [{"y": s.y, "chord": s.chord, "x_offset": s.x_offset, "dihedral_deg": s.dihedral_deg,
                          "twist_deg": s.twist_deg, "foil": s.foil} for s in w.sections],
            "source": f"flow5 plane {plane.name}, sweep {st['sweep']}"}
        if w.name in wing_mass:
            item["muas"]["planform"]["structural_mass"] = {"value": wing_mass[w.name], "units": "kg"}
        item["muas"]["geometry_tool"] = NAME
        set_sources(item, NAME, refs)
        changes.append(f"{m['instance']}: planform and lifting surface of {w.name} ({len(w.sections)} sections)")

    # body and point masses
    frames, _, masses, _ = read_body_and_masses(plane_xml)
    if frames:
        b = st["body"]
        body_item = _item(doc, b, "fuselage (flow5 body)")
        if _same_files(body_item, [plane_ref]):
            body_item["muas"].setdefault("geometry_tool", NAME)
            if body_item["muas"]["geometry_tool"] != NAME:
                changes.append(f"{b['instance']}: body kept from {body_item['muas']['geometry_tool']} (the flow5 "
                               "plane is the recorded one)")
        else:
            body_item.setdefault("geometry", {})["body"] = body_adh(frames)
            body_item["muas"]["geometry_tool"] = NAME
            set_sources(body_item, NAME, [plane_ref])
            changes.append(f"{b['instance']}: body of {len(frames)} frames")
    air = adh_doc.node(doc, "1.2", create=True)
    adh_doc.muas(air, f"{ctx.aircraft}_airvehicle")
    air["muas"]["point_masses"] = [
        {"tag": pm["tag"], "mass": {"value": pm["mass_kg"], "units": "kg"}, "position": {"xyz": pm["xyz"]},
         "source": f"flow5 plane {plane.name} point mass {pm['tag']}", "placeholder": True} for pm in masses]
    changes.append(f"air vehicle: {len(masses)} point masses")

    # T7 analysis: reference dimensions and the mass model of the trim point
    t7 = _t7_analysis(t7_xml)
    if t7["use_plane_inertia"]:
        raise ValueError(f"{t7_xml.name}: the analysis uses the plane inertia, which the export does not hold")
    op = read_t7_scalars(t7_txt)
    for k, v in (("mass", op["mass"]), ("cog_x", op["CoG_x"]), ("cog_z", op["CoG_z"])):
        ref_v = t7["mass"] if k == "mass" else t7["cog_flow5"][0 if k == "cog_x" else 2]
        # the op-point text file prints 6 significant digits, so a value with more digits differs by up to 5e-6
        if not math.isclose(v, ref_v, rel_tol=1e-5, abs_tol=1e-9):
            raise ValueError(f"T7 point {k} {v} differs from the T7 analysis {ref_v}")
    t7_src = ctx.source_ref(t7_xml, "T7 analysis: reference dimensions and the custom mass model")
    air["muas"]["mass_properties"] = {
        "mass": {"value": t7["mass"], "units": "kg"}, "cg": {"xyz": t7["cog"]},
        "inertia": {"ixx": t7["Ixx"], "iyy": t7["Iyy"], "izz": t7["Izz"], "ixz": t7["Ixz"], "unverified_products": ["ixz"]},
        "source": "estimate", "placeholder": True,
        "notes": [f"The custom inertia of the flow5 T7 analysis {t7_xml.name} (sweep {st['sweep']}). It is a typed "
                  "mass model, not a weighing or a CAD mass report.",
                  "flow5 does not document its Ixz sign convention in the export: Ixz is not verified."]}
    old_ref = air["muas"].get("reference") or {}
    air["muas"]["reference"] = {
        "design_frame": "x_fwd_y_right_z_down_m_wingLE",
        "s_ref": {"value": t7["S"], "units": "m^2"}, "b_ref": {"value": t7["b"], "units": "m"},
        "c_ref": {"value": t7["c"], "units": "m"}, "nominal_cg": {"xyz": t7["cog"]},
        "mrp": {"definition": "nominal_cg", "config_id": f"{ctx.aircraft}.nominal", "point": {"xyz": t7["cog"]}},
        **({"surface_signs": old_ref["surface_signs"]} if "surface_signs" in old_ref else {}),
        "placeholder_fields": ["nominal_cg", "mrp"],
        "notes": [f"S, b and c: the {t7['ref_kind']} reference dimensions of the flow5 T7 analysis {t7_xml.name}.",
                  "The design frame is FRD (x forward, y right, z down), flipped from the flow5 axes (x aft, z up) at the "
                  "file edge. The origin is the flow5 origin, the wing root leading edge.",
                  "MRP = the CoG of the T7 analysis (the nominal CG). It is a mass model value (placeholder)."]}
    changes.append(f"reference: S {t7['S']} m^2, b {t7['b']} m, c {t7['c']} m, MRP {t7['cog']}")

    # aero model
    polar = parse_polar_text(polar_csv.read_text(encoding="utf-8", errors="replace"), polar_csv)
    viscous = pd.DataFrame({"CL": polar.col("CL"), "CD": polar.col("CD")})
    aero_settings = air["muas"].get("aero_settings")
    if aero_settings is None:
        raise ValueError("air vehicle muas.aero_settings (cl_max, cl_min) is missing: the CL table needs the stall values")
    stall = {"CL_max": aero_settings["cl_max"], "CL_min": aero_settings["cl_min"],
             "placeholder": aero_settings.get("placeholder", True)}
    bu = from_flow5(sweep, viscous, stall)
    res = json.loads(results.read_text(encoding="utf-8"))
    xml = to_daveml(bu, name=f"{ctx.aircraft.capitalize()} aerodynamic model", author="AeroPlan flow5 spoke", org="MUAS",
                    created=str(st.get("sweep_date") or res["created_utc"][:10]),
                    description=f"{ctx.aircraft} aero build-up from the flow5 sweep {res.get('name')} (plane "
                                f"{res.get('plane')}). Moments about the MRP (the T7 CoG). " + " ".join(bu.notes))
    errors = validate_dml(xml)
    if errors:
        raise ValueError(f"the aero model fails the DAVE-ML 2.0 DTD: {errors[:3]}")
    air_sources = [plane_ref, t7_src, ctx.source_ref(t7_txt, "T7 point: stability derivatives and trim"),
                   ctx.source_ref(polar_csv, "viscous alpha polar: CD0 and K"),
                   ctx.source_ref(results, "sweep results: control derivatives and validation")]
    ctx.add_dataset(
        air, f"aero.{ctx.aircraft}", from_xml(xml), role="aero model (DAVE-ML in ADH form)", dataset_role="aero",
        derived_from=[r["asset"] for r in air_sources],
        meta={"form": "daveml-adh", "fidelity": "L2", "units_system": "SI",
              "model_description": {"generation_tool": "flow5 7.57 + AeroPlan aero build-up",
                                    "model_name": f"{ctx.aircraft} aero build-up",
                                    "description": f"flow5 sweep {st['sweep']} ({st['sweep_date']})"},
              "mrp": {"xyz": t7["cog"]}, "analysis_mass_model": copy.deepcopy(air["muas"]["mass_properties"]),
              "placeholder": bool(stall["placeholder"]),
              "notes": ["No uncertainty estimate exists in the source (sigma not given)."] + list(bu.notes)})
    changes.append(f"aero model: {len(bu.coefs)} coefficients, CL table of {len(bu.cl_table)} points")

    # trim point -> initial conditions
    air["muas"]["initial_conditions"] = {
        "rate_frame": "local_NED", "latitude_type": "geodetic", "attitude_sequence": "3-2-1",
        "values": {"speed_mps": bu.trim["speed_mps"], "altitude_m": 0.0}, "placeholder": True}
    changes.append(f"initial conditions: T7 trim speed {bu.trim['speed_mps']} m/s, altitude 0 m (placeholder: the "
                   "flow5 export does not give the air density)")
    set_sources(air, NAME, air_sources)
    return changes


def sweep(doc: Dict[str, Any], ctx: Context, name: Optional[str] = None, only: Optional[List[str]] = None,
          dry_run: bool = False, keep: bool = False, timeout: float = 3600.0, flow5: Optional[str] = None) -> Dict[str, Any]:
    """Run the flow5 sweep of the document: plane from the ADH geometry, mass model and reference from node 1.2.

    Writes work/<aircraft>/sweeps/<name>/ (the layout `ingest` reads). Settings block `sweep_runner`: runs, ranges,
    polar options, the `.fl5` project. The sweep that the settings name as `sweep` (the ground truth) is not overwritten.
    """
    from datetime import date

    from .sweep import Flow5Error, find_flow5, run

    st = ctx.settings()
    sr = st.get("sweep_runner")
    if not sr:
        raise ValueError(f"tools/flow5/settings/{ctx.aircraft}.yaml has no sweep_runner block")
    name = name or f"{ctx.aircraft}_{date.today().isoformat()}"
    if name == st.get("sweep"):
        raise ValueError(f"{name!r} is the sweep that the settings use as ground truth: give another --name")
    plane_xml = generate(doc, ctx)[0]
    air = adh_doc.node(doc, "1.2")
    ref = (air.get("muas") or {}).get("reference")
    mp = (air.get("muas") or {}).get("mass_properties")
    if not ref or not mp or "inertia" not in mp:
        raise ValueError("node 1.2 needs muas.reference and muas.mass_properties with inertia (run the SpecSheet spoke)")
    i = mp["inertia"]
    inputs = {"S": ref["s_ref"]["value"], "b": ref["b_ref"]["value"], "cbar": ref["c_ref"]["value"],
              "mass": mp["mass"]["value"], "cg": flip_point(mp["cg"]["xyz"]), "inertia": [i["ixx"], i["iyy"], i["izz"], i["ixz"]]}   # flow5 axes
    project = ctx.work / sr["project"] if sr.get("project") else None
    if project is not None and not project.is_file():
        raise ValueError(f"project file not found: {project}")
    hint = None
    old = ctx.work / "sweeps" / str(st.get("sweep", "")) / "results.json"
    if dry_run and old.is_file():
        r = json.loads(old.read_text(encoding="utf-8"))
        hint = (r["speed"], r["alpha_deg"])         # dry run only: the trim of the settings sweep
    exe = None
    if not dry_run:
        exe = find_flow5(flow5 or st.get("flow5_exe"))
    try:
        return run(plane_xml=plane_xml, inputs=inputs, sr=sr, name=name, dest=ctx.work / "sweeps" / name,
                   work_root=ctx.work / "runs" / name, project=project, only=only, exe=exe, timeout=timeout,
                   dry_run=dry_run, keep=keep, trim_hint=hint,
                   extra={"aircraft_version": getattr(ctx.acft, "version", None), "mass_model_source": mp.get("source")})
    except Flow5Error as err:
        raise RuntimeError(str(err)) from err


def generate(doc: Dict[str, Any], ctx: Context) -> List[Path]:
    """Write work/<aircraft>/generated/<aircraft>.xml (flow5 plane) and the foil .dat files from the document."""
    from aeroplan.geometry import foils_of

    st = ctx.settings()
    out = ctx.work / "generated"
    out.mkdir(parents=True, exist_ok=True)
    surfaces, foils = [], {}
    for _, item, _ in adh_doc.iter_nodes(doc):
        pf = (item.get("muas") or {}).get("planform")
        if pf:
            surfaces.append(pf)
            foils.update(foils_of(item))
    order = {name: i for i, name in enumerate(st.get("surfaces", {}))}
    surfaces.sort(key=lambda s: order.get(s["surface_name"], len(order)))
    body = None
    if "body" in st:
        b = adh_doc.find(doc, st["body"]["instance"])
        if "body" in (b.get("geometry") or {}):
            body = {"frames": body_frames(b["geometry"]["body"]), "position": [0.0, 0.0, 0.0]}
    air = adh_doc.node(doc, "1.2")
    masses = [{"tag": p["tag"], "mass_kg": p["mass"]["value"], "xyz": p["position"]["xyz"]}
              for p in air["muas"].get("point_masses") or []]
    files = []
    plane_path = out / f"{ctx.aircraft}.xml"
    write_plane(plane_path, f"{ctx.aircraft}_aeroplan", surfaces, body, masses, st.get("mesh", {}))
    files.append(plane_path)
    for name, contour in sorted(foils.items()):
        p = out / f"{name}.dat"
        write_foil(p, name, contour)
        files.append(p)
    return files
