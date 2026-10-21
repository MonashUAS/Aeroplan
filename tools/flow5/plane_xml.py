"""flow5 plane XML: read the body frames and point masses, and write a plane XML from the ADH document.

flow5 works in x aft, y right, z up. The readers return, and the writer takes, the design frame (FRD, aeroplan.frame): each
position is flipped at the file edge. The wing reader is aeroplan.adapters.flow5_geometry.read_plane. Layout of the file: a hand copy of the plane XML that
flow5 7.57 writes (`<xflplane version="1.0">`, the Currawong file plane_with_body.xml). The writer makes the same
elements. Meshing values (panel counts and distributions) are tool settings: they come from tools/flow5/settings/.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from aeroplan.frame import flip_array, flip_point


def _tag(e: ET.Element) -> str:
    return e.tag.lower()


def _child(e: ET.Element, name: str):
    return next((c for c in e if _tag(c) == name.lower()), None)


def _vec(text: str) -> np.ndarray:
    return np.array([float(t) for t in text.replace(",", " ").split()], float)


def read_body_and_masses(path: Path) -> Tuple[List[np.ndarray], np.ndarray, List[Dict[str, Any]], Dict[str, Any]]:
    """(frames, body position, point masses, body mesh settings) of a plane XML, in the design frame (FRD). Frames are
    right-half points, nose first."""
    root = ET.fromstring(Path(path).read_bytes())
    plane = _child(root, "plane")
    masses = []
    inertia = _child(plane, "inertia")
    for pm in (c for c in (inertia if inertia is not None else []) if _tag(c) == "point_mass"):
        masses.append({"tag": _child(pm, "tag").text.strip(), "mass_kg": float(_child(pm, "mass").text),
                       "xyz": flip_point(_vec(_child(pm, "coordinates").text))})
    body = _child(plane, "body")
    if body is None:
        return [], np.zeros(3), masses, {}
    pos = _vec(_child(body, "position").text)
    nurbs = _child(body, "nurbs")
    frames, x_panels = [], []
    for fr in (c for c in nurbs if _tag(c) == "frame"):
        frames.append(flip_array(np.array([_vec(p.text) for p in fr if _tag(p) == "point"]) + pos))
        x_panels.append(int(_child(fr, "x_panels").text))
    stripes = [int(s.text) for s in _child(body, "panel_stripes")]
    mesh = {"name": _child(body, "name").text, "type": _child(body, "type").text, "x_panels": x_panels,
            "panel_stripes": stripes}
    return frames, np.array(flip_point(pos)), masses, mesh


def read_wing_masses(path: Path) -> Dict[str, float]:
    """Surface name -> the structure mass of the wing (<Inertia><Mass>), for the wings that give one."""
    plane = _child(ET.fromstring(Path(path).read_bytes()), "plane")
    out = {}
    for w in (c for c in plane if _tag(c) == "wing"):
        inert = _child(w, "inertia")
        mass = _child(inert, "mass") if inert is not None else None
        if mass is not None and mass.text and mass.text.strip():
            out[_child(w, "name").text.strip()] = float(mass.text)
    return out


def _sub(parent: ET.Element, tag: str, text: Any = None) -> ET.Element:
    e = ET.SubElement(parent, tag)
    if text is not None:
        e.text = str(text)
    return e


def _f(v: float) -> str:
    return format(float(v), ".7g")


def fit_counts(values: List[int] | None, n: int, default: int = 2) -> List[int]:
    """A list of `n` panel counts from the settings list `values`. The list is kept when it has `n` entries. Else every
    entry gets the rounded mean of the list (at least 1), so the mesh size stays near the settings. An empty list gives
    `default`. A shorter list must never cut the body: `zip` did drop the frames after the end of the list."""
    if not values:
        return [default] * n
    if len(values) == n:
        return [int(v) for v in values]
    return [max(1, int(round(sum(values) / len(values))))] * n


def write_plane(path: Path, name: str, surfaces: List[Dict[str, Any]], body: Dict[str, Any] | None,
                masses: List[Dict[str, Any]], mesh: Dict[str, Any]) -> None:
    """Write a flow5 plane XML.

    surfaces: muas.planform dicts. body: {"frames": [array], "position": xyz} or None. masses: {tag, mass_kg, xyz}. All
    positions are in the design frame (FRD): the writer flips them to the flow5 frame.
    mesh: flow5 settings {"surfaces": {surface_name: {"sections": [{x_panels, x_dist, y_panels, y_dist}],
    "tip_strips"}}, "body": {"type", "x_panels", "panel_stripes"}}.
    """
    root = ET.Element("xflplane", version="1.0")
    u = _sub(root, "Units")
    for k in ("meter_to_length_unit", "m2_to_area_unit", "kg_to_mass_unit", "ms_to_speed_unit", "kgm2_to_inertia_unit"):
        _sub(u, k, 1)
    p = _sub(root, "Plane")
    _sub(p, "Name", name)
    inert = _sub(p, "Inertia")
    for m in masses:
        pm = _sub(inert, "Point_Mass")
        _sub(pm, "Tag", m["tag"])
        _sub(pm, "Mass", _f(m["mass_kg"]))
        _sub(pm, "coordinates", ", ".join(_f(v) for v in flip_point(m["xyz"])))
    if body is not None:
        bm = mesh.get("body", {})
        b = _sub(p, "body")
        _sub(b, "Name", bm.get("name", "Fuselage"))
        _sub(b, "Description", "Written by the AeroPlan flow5 spoke from the ADH document")
        pos = np.asarray(flip_point(body["position"]), float)
        _sub(b, "Position", ", ".join(_f(v) for v in pos))
        _sub(b, "Type", bm.get("type", "FLATPANELS"))
        n_pts = len(body["frames"][0])
        stripes = fit_counts(bm.get("panel_stripes"), n_pts)
        ps = _sub(b, "Panel_Stripes")
        for i, s in enumerate(stripes):
            _sub(ps, f"stripe_{i}", s)
        _sub(_sub(b, "Inertia"), "Volume_Mass", 0)
        nurbs = _sub(b, "NURBS")
        xp = fit_counts(bm.get("x_panels"), len(body["frames"]))
        for fr, nx in zip(body["frames"], xp):
            f = _sub(nurbs, "frame")
            _sub(f, "Angle", 0)
            _sub(f, "x_panels", nx)
            local = flip_array(fr) - pos
            _sub(f, "Position", f"{_f(local[0, 0])}, 0, 0")
            for q in local:
                _sub(f, "point", ", ".join(_f(v) for v in q))
    for s in surfaces:
        sm = mesh.get("surfaces", {}).get(s["surface_name"], {})
        w = _sub(p, "wing")
        _sub(w, "Name", s["surface_name"])
        _sub(w, "Type", s["kind"])
        _sub(w, "Description")
        _sub(w, "Position", ", ".join(_f(v) for v in flip_point(s["position"]["xyz"])))
        _sub(w, "Tip_Strips", sm.get("tip_strips", 10))
        _sub(w, "Rx_angle", _f(s.get("rx_deg", 0.0)))
        _sub(w, "Ry_angle", _f(s.get("ry_deg", 0.0)))
        _sub(w, "symmetric", str(s.get("symmetric", True)).lower())
        _sub(w, "Two_Sided", str(s.get("two_sided", True)).lower())
        _sub(w, "Closed_Inner_Side", "false")
        mass = s.get("structural_mass")
        _sub(w, "AutoInertia", "true")
        if mass is not None:
            _sub(_sub(w, "Inertia"), "Mass", _f(mass["value"]))
        secs = _sub(w, "Sections")
        sec_mesh = sm.get("sections", [])
        for i, sec in enumerate(s["sections"]):
            mm = sec_mesh[i] if i < len(sec_mesh) else {}
            e = _sub(secs, "Section")
            _sub(e, "y_position", _f(sec["y"]))
            _sub(e, "Chord", _f(sec["chord"]))
            _sub(e, "xOffset", _f(sec["x_offset"]))
            _sub(e, "Dihedral", _f(sec["dihedral_deg"]))
            _sub(e, "Twist", _f(sec["twist_deg"]))
            _sub(e, "x_number_of_panels", mm.get("x_panels", 10))
            _sub(e, "x_panel_distribution", mm.get("x_dist", "UNIFORM"))
            _sub(e, "y_number_of_panels", mm.get("y_panels", 10))
            _sub(e, "y_panel_distribution", mm.get("y_dist", "UNIFORM"))
            _sub(e, "Left_Side_FoilName", sec["foil"])
            _sub(e, "Right_Side_FoilName", sec["foil"])
    ET.indent(root, space="    ")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE flow5>\n'
                          + ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")


def read_mesh_settings(path: Path) -> Dict[str, Any]:
    """The flow5 meshing values of a plane XML, in the form of tools/flow5/settings/<aircraft>.yaml `mesh`."""
    root = ET.fromstring(Path(path).read_bytes())
    plane = _child(root, "plane")
    out: Dict[str, Any] = {"surfaces": {}}
    for w in (c for c in plane if _tag(c) == "wing"):
        secs = []
        for s in (c for c in _child(w, "sections") if _tag(c) == "section"):
            secs.append({"x_panels": int(_child(s, "x_number_of_panels").text),
                         "x_dist": _child(s, "x_panel_distribution").text.strip(),
                         "y_panels": int(_child(s, "y_number_of_panels").text),
                         "y_dist": _child(s, "y_panel_distribution").text.strip()})
        out["surfaces"][_child(w, "name").text.strip()] = {"tip_strips": int(_child(w, "tip_strips").text),
                                                           "sections": secs}
    _, _, _, body_mesh = read_body_and_masses(path)
    if body_mesh:
        out["body"] = body_mesh
    return out


def write_foil(path: Path, name: str, contour: np.ndarray) -> None:
    """A Selig .dat foil file."""
    lines = [name] + [f"{x:.6f} {z:.6f}" for x, z in contour]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
