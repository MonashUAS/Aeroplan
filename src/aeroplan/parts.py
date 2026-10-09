"""Part meshes of the aircraft in the design frame, made from the `muas.visual` entries of the ADH document.

For each entry:
  - a CAD mesh (`mesh`, an asset of the register): read the raw file when it is on this machine with the
    registered hash. Else the part has no CAD mesh here (`missing`).
  - generator "planform": the lifting surface of the item (planform and foils). On the fin it stops at the rudder
    hinge, so the CAD rudder fits behind it.
  - generator "tube": the boom, from the aft end of the fuselage to the root quarter chord of the horizontal tail.
    Rule of Aerolink 6f7edb7 visual/airframe.py.

Fallback when a CAD mesh is missing: an item with a planform gets its full lifting surface, an item with an ADH body
gets the lofted body. The note says so. A part with no fallback is left out.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from . import adh_doc, assets
from .geometry import body_mesh, foils_of, planform_wing, surface_mesh
from .visual import PIVOT, _wing_to_design, lifting_surface, mirror_y, read_stl, to_design, tube


@dataclass
class Part:
    name: str
    instance: str
    tri: np.ndarray
    hinge: Optional[List[List[float]]]
    material: Optional[str]
    source: str
    placeholder: bool = False


@dataclass
class PartSet:
    parts: Dict[str, Part] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


def _local(doc: Dict[str, Any], ref: Dict[str, Any], root: Path) -> Optional[Path]:
    """The local file of a SourceRef when it is on this machine with the registered hash, else None."""
    try:
        return assets.local_path(assets.entry(doc, ref["asset"]), root)
    except assets.AssetError:
        return None


def mesh_name(doc: Dict[str, Any], ref: Dict[str, Any]) -> str:
    """The registered name of the file of a SourceRef (for notes)."""
    try:
        return assets.entry(doc, ref["asset"])["name"]
    except assets.AssetError:
        return ref["asset"]


def _cad(doc: Dict[str, Any], entry: Dict[str, Any], root: Path) -> Optional[np.ndarray]:
    path = _local(doc, entry["mesh"], root)
    if path is None:
        return None
    return to_design(read_stl(path.read_bytes(), path.name), entry.get("units", "m"), entry.get("transform"))


def skin_mesh(doc: Dict[str, Any], item: Dict[str, Any], root: Path) -> Optional[np.ndarray]:
    """The `muas.skin` of an item in the design frame (m), or None when the file is not on this machine (or changed)."""
    skin = (item.get("muas") or {}).get("skin")
    if not skin:
        return None
    path = _local(doc, skin["mesh"], root)
    if path is None:
        return None
    if skin["format"] == "step_faceted":
        from .step_mesh import read_step_faceted

        return to_design(read_step_faceted(path)[0], "m", skin["transform"])
    return to_design(read_stl(path.read_bytes(), path.name), skin.get("units", "m"), skin["transform"])


def part_meshes(doc: Dict[str, Any], root: Path) -> PartSet:
    out = PartSet()
    entries = []
    for _, item, _ in adh_doc.iter_nodes(doc):
        for v in (item.get("muas") or {}).get("visual") or []:
            entries.append((item, v))
    generated = []
    for item, v in entries:
        inst = item["muas"]["instance"]
        if "mesh" in v:
            tri = _cad(doc, v, root)
            if tri is not None:
                out.parts[v["part"]] = Part(v["part"], inst, tri, v.get("hinge"), v.get("material"), v["source"],
                                            v.get("placeholder", False))
                continue
            fb = _fallback(doc, item)
            if fb is None:
                out.notes.append(f"{v['part']}: CAD mesh {mesh_name(doc, v['mesh'])} is not on this machine (or changed). "
                                 "No fallback shape: the part is left out")
            else:
                out.parts[v["part"]] = Part(v["part"], inst, fb[0], fb[2], v.get("material"), fb[1], True)
                out.notes.append(f"{v['part']}: CAD mesh not on this machine, {fb[1]}")
        else:
            generated.append((item, v))
    for item, v in generated:
        inst = item["muas"]["instance"]
        if v["generator"] == "planform":
            tri = _planform_part(item, out)
        else:
            tri = _tube_part(doc, v, out)
        out.parts[v["part"]] = Part(v["part"], inst, tri, None, v.get("material"), v["source"], v.get("placeholder", False))
    return out


def _fallback(doc: Dict[str, Any], item: Dict[str, Any]):
    """(triangles, note, hinge) of an item with no CAD mesh here, made from its ADH shape, or None."""
    m = item.get("muas") or {}
    if m.get("control_surface"):
        return _control_surface(doc, m["control_surface"])
    if m.get("planform") and "lifting_surface" in (item.get("geometry") or {}):
        return surface_mesh(item), "full lifting surface from the ADH planform (no control surface cut)", None
    if "body" in (item.get("geometry") or {}):
        return body_mesh(item["geometry"]["body"]), "body lofted from the ADH body cross sections", None
    return None


def _hinge_point(wing, h: float, y: float) -> np.ndarray:
    """The point at chord fraction h on the chord line at span station y (twist about the quarter chord)."""
    secs = wing.sections
    sy = np.array([s.y for s in secs])
    zd = np.concatenate([[0.0], np.cumsum(np.diff(sy) * np.tan(np.radians([s.dihedral_deg for s in secs[:-1]])))])
    k = int(min(max(np.searchsorted(sy, y, side="right") - 1, 0), len(secs) - 2))
    t = (y - sy[k]) / (sy[k + 1] - sy[k])
    a, b = secs[k], secs[k + 1]
    c, xo = a.chord + t * (b.chord - a.chord), a.x_offset + t * (b.x_offset - a.x_offset)
    tw = np.radians(a.twist_deg + t * (b.twist_deg - a.twist_deg))
    local = np.array([[xo + PIVOT * c + (h - PIVOT) * c * np.cos(tw), y,
                       zd[k] + t * (zd[k + 1] - zd[k]) - (h - PIVOT) * c * np.sin(tw)]])
    return _wing_to_design(local, wing)[0]


def _control_surface(doc: Dict[str, Any], cs: Dict[str, Any]):
    """A control surface from its parent planform: the span fraction eta_span, from the hinge to the trailing edge."""
    parent = adh_doc.find(doc, cs["parent"])
    wing = planform_wing(parent["muas"]["planform"])
    semi = wing.sections[-1].y
    tri = lifting_surface(wing, foils_of(parent), 1.0, x_over_c_min=cs["hinge_x_over_c"],
                          y_range=(cs["eta_span"][0] * semi, cs["eta_span"][1] * semi))
    side = cs.get("side", "both")
    if side == "left":
        tri = mirror_y(tri)
    elif side == "both" and wing.mirrored:
        tri = np.concatenate([mirror_y(tri), tri])
    ends = [_hinge_point(wing, cs["hinge_x_over_c"], e * semi) for e in cs["eta_span"]]
    if side == "left":
        ends = [e * np.array([1.0, -1.0, 1.0]) for e in ends[::-1]]
    elif side == "both" and wing.mirrored:
        ends = [ends[1] * np.array([1.0, -1.0, 1.0]), ends[1]]
    hinge = [[round(float(c), 6) for c in p] for p in ends]
    note = (f"control surface from the {cs['parent']} planform (span {cs['eta_span']}, hinge at "
            f"{cs['hinge_x_over_c']} of the chord)")
    return tri, note, hinge


def _planform_part(item: Dict[str, Any], out: PartSet) -> np.ndarray:
    """The lifting surface of an item. A fin stops at the rudder hinge when the rudder part has one."""
    rudder = out.parts.get("rudder")
    if item["muas"]["planform"]["kind"] != "FIN" or rudder is None or rudder.hinge is None:
        return surface_mesh(item)
    wing = planform_wing(item["muas"]["planform"])
    h0, h1 = (np.array(p) for p in rudder.hinge)

    def cut(y, le_x, chord):
        z = wing.position[2] + y
        hx = float(h0[0] + (z - h0[2]) / (h1[2] - h0[2]) * (h1[0] - h0[0]))
        return min(1.0, (hx - le_x) / chord)

    return surface_mesh(item, cut)


def _tube_part(doc: Dict[str, Any], v: Dict[str, Any], out: PartSet) -> np.ndarray:
    fus = out.parts.get("fuselage")
    if fus is None:
        raise ValueError("the boom tube needs the fuselage part")
    pts = fus.tri.reshape(-1, 3)
    aft = pts[pts[:, 0] >= pts[:, 0].max() - 0.02]
    start = np.array([aft[:, 0].max() - 0.001, 0.0, aft[:, 2].mean()])
    htail = adh_doc.find(doc, v["tube"]["to_instance"])
    wing = planform_wing(htail["muas"]["planform"])
    s0 = wing.sections[0]
    end = np.array([wing.position[0] + s0.x_offset + PIVOT * s0.chord, 0.0, wing.position[2]])
    return tube(start, end, float(v["tube"]["radius_m"]))
