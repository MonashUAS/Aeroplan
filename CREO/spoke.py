"""CREO spoke: the CAD part exports -> `muas.visual` of their ADH items (pointer, pose and hinge of each mesh).

Input (git ignores it): CREO/work/<aircraft>/cad/*.stl, exported from the Creo assembly.
Settings (committed): CREO/settings/<aircraft>.yaml
    units           units of the STL files
    parts           part name -> {file, instance (the ADH item), axes, origin_m}
    skins           skin name -> {file, instance, axes, origin_m, body}: an outer skin (a faceted STEP file, for example
                    the shrinkwrap of the fuselage). It is a reference shape for the datum checks, the OpenVSP view and
                    the OpenVSP panel analysis. With `body: {frames, points, cut}` the spoke also slices the skin into
                    the ADH body of the item (aeroplan.skin_body): `frames` frames of `points` points each, and `cut`
                    {x_m: [x0, x1], y_max_m} removes the wing centre panel that the shrinkwrap holds.
    tubes           instance -> {node, name, description, radius_m, from_instance, to_instance, source, placeholder}:
                    a round tube body (the tail boom) until the CAD has the part. It goes into the ADH as a
                    subcomponent of `node` with `geometry.body` (ADH Body) and `muas.tube` (inputs, source). It runs
                    without the CAD folder.

The meshes stay raw files on the user's machine. The `.muas` file holds, for each part: a pointer (path, sha256),
the transform into the design frame, and for a movable part (aileron_l, aileron_r, elevator, rudder) its hinge axis.
The hinge is a line through the front edge of the mesh (aeroplan.visual.front_edge_axis).

Later: mass properties from the Creo mass report.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

import numpy as np

from aeroplan import MUAS_SCHEMA_VERSION, adh_doc
from aeroplan.geometry import body_adh, body_frames, planform_wing
from aeroplan.spokes import Context, set_sources
from aeroplan.visual import MOVABLE, PIVOT, front_edge_axis, read_stl, to_design

NAME = "CREO"
TUBE_POINTS = 17              # points of each right-half frame of a tube (top to bottom), the same in every frame


def tube_ends(doc: Dict[str, Any], from_instance: str, to_instance: str) -> np.ndarray:
    """Start and end of a tube: the centre of the last frame of the body of `from_instance`, and the root quarter
    chord of the planform of `to_instance` (the rule of the visual boom, aeroplan.parts._tube_part)."""
    body = adh_doc.find(doc, from_instance).get("geometry", {}).get("body")
    if body is None:
        raise ValueError(f"tube: {from_instance} has no ADH body geometry")
    aft = body_frames(body)[-1]
    start = [float(aft[0, 0]), 0.0, float(0.5 * (aft[:, 2].min() + aft[:, 2].max()))]
    pf = adh_doc.find(doc, to_instance)["muas"].get("planform")
    if pf is None:
        raise ValueError(f"tube: {to_instance} has no planform")
    wing = planform_wing(pf)
    s0 = wing.sections[0]
    end = [wing.position[0] + s0.x_offset + PIVOT * s0.chord, 0.0, wing.position[2]]
    return np.array([start, end], float)


def tube_frames(p0: np.ndarray, p1: np.ndarray, radius: float) -> List[np.ndarray]:
    """Frames of a round tube from p0 to p1 (x must rise) with closed ends. A frame is the right half, top to bottom,
    in the plane x = constant. The ends are one point (zero area); the full radius starts one radius inside each end."""
    length = float(p1[0] - p0[0])
    if length <= 2 * radius:
        raise ValueError("tube: the end must be aft of the start by more than a diameter")
    th = np.linspace(0.0, math.pi, TUBE_POINTS)
    frames = []
    for x in (p0[0], p0[0] + radius, p1[0] - radius, p1[0]):
        t = (x - p0[0]) / length
        c = p0 + t * (p1 - p0)
        r = radius if p0[0] < x < p1[0] else 0.0
        frames.append(np.column_stack([np.full_like(th, c[0]), r * np.sin(th), c[2] + r * np.cos(th)]))
    return frames


def write_tubes(doc: Dict[str, Any], tubes: Dict[str, Dict[str, Any]]) -> List[str]:
    """Write each tube of the settings as a subcomponent of its ADH node (geometry.body and muas.tube)."""
    changes = []
    for inst, spec in tubes.items():
        ends = tube_ends(doc, spec["from_instance"], spec["to_instance"])
        radius = float(spec["radius_m"])
        body = body_adh(tube_frames(ends[0], ends[1], radius))
        comp = {"name": spec["name"], "description": spec.get("description", spec["name"]),
                "geometry": {"body": body},
                "muas": {"ext_version": MUAS_SCHEMA_VERSION, "instance": inst, "geometry_tool": NAME,
                         "tube": {"radius": {"value": radius, "units": "m"}, "from_instance": spec["from_instance"],
                                  "to_instance": spec["to_instance"], "source": spec["source"],
                                  "placeholder": bool(spec.get("placeholder", False))}}}
        parent = adh_doc.node(doc, str(spec["node"]), create=True)
        old = next((s for s in parent.get("subcomponents") or [] if (s.get("muas") or {}).get("instance") == inst), None)
        if old is not None and old.get("geometry") == comp["geometry"] and old["muas"].get("tube") == comp["muas"]["tube"]:
            continue
        adh_doc.put_subcomponent(parent, comp)
        length = float(np.linalg.norm(ends[1] - ends[0]))
        changes.append(f"{inst}: tube body, radius {radius:g} m, length {length:.3f} m, under {spec['node']}")
    return changes


def _min_height(want: Dict[str, Any]):
    return {"value": float(want["min_height_m"]), "units": "m"} if want.get("min_height_m") else None


def _skin_body(item: Dict[str, Any], name: str, spec: Dict[str, Any], tri: np.ndarray, ref: Dict[str, Any]) -> List[str]:
    """Slice the skin into the ADH body of the item and record the fit in `muas.skin.body_fit`. The changed file wins:
    nothing happens when the skin is the recorded one and the recorded fit has the same method and settings."""
    from aeroplan.skin_body import METHOD, fit_report, slice_frames

    want = spec["body"]
    cut = want.get("cut")
    old_fit = (item["muas"].get("skin") or {}).get("body_fit") or {}
    recorded = any(r["tool"] == NAME and r["asset"] == ref["asset"] for r in item["muas"].get("sources") or [])
    if (recorded and (item.get("geometry") or {}).get("body") is not None and item["muas"].get("geometry_tool") == NAME
            and (old_fit.get("method"), old_fit.get("frames"), old_fit.get("points"), old_fit.get("cut"),
             old_fit.get("min_height")) == (METHOD, int(want["frames"]), int(want["points"]), cut,
                                            _min_height(want))):
        return []
    frames = slice_frames(tri, int(want["frames"]), int(want["points"]), cut, float(want.get("min_height_m", 0.0)))
    rep = fit_report(frames, tri, cut)
    item.setdefault("geometry", {})["body"] = body_adh(frames)
    item["muas"]["geometry_tool"] = NAME
    set_sources(item, NAME, [ref])
    q = lambda v, u: {"value": round(float(v), 9), "units": u}   # noqa: E731
    item["muas"]["skin"]["body_fit"] = {
        "method": METHOD, "frames": int(want["frames"]), "points": int(want["points"]), "cut": cut,
        "min_height": _min_height(want),
        "rms_gap": q(rep["rms_gap_m"], "m"), "largest_gap": q(rep["largest_gap_m"], "m"),
        "body_volume": q(rep["body_volume_m3"], "m^3"), "skin_volume": q(rep["skin_volume_m3"], "m^3")}
    return [f"{spec['instance']}: body of {len(frames)} frames x {want['points']} points from the skin {name}: gap to "
            f"the skin RMS {rep['rms_gap_m'] * 1e3:.2f} mm, largest {rep['largest_gap_m'] * 1e3:.1f} mm "
            f"(wing panel excluded), volume {rep['body_volume_m3']:.5f} m3 (skin {rep['skin_volume_m3']:.5f} m3 with "
            "the wing panel)"]


def ingest(doc: Dict[str, Any], ctx: Context):
    st = ctx.settings()
    if not st:
        return None
    cad = ctx.work / "cad"
    changes: List[str] = []
    if cad.is_dir():
        changes += _ingest_cad(doc, ctx, st, cad)
    # the tubes follow the body, so they come after the skins
    tube_changes = write_tubes(doc, st.get("tubes") or {})
    if not cad.is_dir():
        return tube_changes if st.get("tubes") else None
    return changes + tube_changes


def _ingest_cad(doc: Dict[str, Any], ctx: Context, st: Dict[str, Any], cad) -> List[str]:
    changes: List[str] = []
    by_item: Dict[str, list] = {}
    for part, spec in st["parts"].items():
        path = cad / spec["file"]
        if not path.is_file():
            raise ValueError(f"CAD part {part}: {path.name} is not in {cad}")
        transform = {"axes": spec["axes"], "origin_m": spec.get("origin_m", [0.0, 0.0, 0.0])}
        entry = {"part": part, "mesh": ctx.source_ref(path, f"CAD mesh of {part}"), "units": st["units"],
                 "transform": transform, "source": f"Creo export {spec['file']} with the CREO settings transform"}
        if part in MOVABLE:
            tri = to_design(read_stl(path.read_bytes(), path.name), st["units"], transform)
            a, b = front_edge_axis(tri, vertical=part == "rudder")
            entry["hinge"] = [[round(float(c), 6) for c in a], [round(float(c), 6) for c in b]]
        by_item.setdefault(spec["instance"], []).append(entry)
    for inst, entries in by_item.items():
        item = adh_doc.find(doc, inst)
        keep = [v for v in item["muas"].get("visual") or [] if "mesh" not in v]
        item["muas"]["visual"] = entries + keep
        changes.append(f"{inst}: CAD parts {', '.join(e['part'] for e in entries)}")
    for name, spec in (st.get("skins") or {}).items():
        path = cad / spec["file"]
        if not path.is_file():
            raise ValueError(f"CAD skin {name}: {path.name} is not in {cad}")
        fmt = "step_faceted" if path.suffix.lower() in (".stp", ".step") else "stl"
        if fmt == "step_faceted":
            from aeroplan.step_mesh import read_step_faceted

            raw, unit = read_step_faceted(path)
            note = f"{len(raw)} triangles, file unit {unit}"
            units = "m"
        else:
            raw = read_stl(path.read_bytes(), path.name)
            note = f"units {st['units']}"
            units = st["units"]
        item = adh_doc.find(doc, spec["instance"])
        transform = {"axes": spec["axes"], "origin_m": spec.get("origin_m", [0.0, 0.0, 0.0])}
        ref = ctx.source_ref(path, f"outer skin {name} ({'faceted STEP' if fmt == 'step_faceted' else 'STL'})")
        fit = (item["muas"].get("skin") or {}).get("body_fit") if spec.get("body") else None
        item["muas"]["skin"] = {
            "mesh": ref, "format": fmt, "units": units, "transform": transform,
            "source": f"Creo export {spec['file']} with the CREO settings transform ({note})",
            **({"body_fit": fit} if fit else {})}
        changes.append(f"{spec['instance']}: outer skin {spec['file']} ({note})")
        if spec.get("body"):
            changes += _skin_body(item, name, spec, to_design(raw, units, transform), ref)
    return changes
