"""CREO spoke: the CAD part exports -> `muas.visual` of their ADH items (pointer, pose and hinge of each mesh).

Input (git ignores it): CREO/work/<aircraft>/cad/*.stl, exported from the Creo assembly.
Settings (committed): CREO/settings/<aircraft>.yaml
    units           units of the STL files
    parts           part name -> {file, instance (the ADH item), axes, origin_m}
    skins           skin name -> {file, instance, axes, origin_m}: an outer skin (a faceted STEP file, for example
                    the shrinkwrap of the fuselage). It is a reference shape for the datum checks and the OpenVSP view.

The meshes stay raw files on the user's machine. The `.muas` file holds, for each part: a pointer (path, sha256),
the transform into the design frame, and for a movable part (aileron_l, aileron_r, elevator, rudder) its hinge axis.
The hinge is a line through the front edge of the mesh (aeroplan.visual.front_edge_axis).

Later: mass properties from the Creo mass report.
"""
from __future__ import annotations

from typing import Any, Dict

from aeroplan import adh_doc
from aeroplan.spokes import Context
from aeroplan.visual import MOVABLE, front_edge_axis, read_stl, to_design

NAME = "CREO"


def ingest(doc: Dict[str, Any], ctx: Context):
    st = ctx.settings()
    cad = ctx.work / "cad"
    if not st or not cad.is_dir():
        return None
    changes = []
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

            tri, unit = read_step_faceted(path)
            note = f"{len(tri)} triangles, file unit {unit}"
        else:
            note = f"units {st['units']}"
        item = adh_doc.find(doc, spec["instance"])
        item["muas"]["skin"] = {
            "mesh": ctx.source_ref(path, f"outer skin {name} ({'faceted STEP' if fmt == 'step_faceted' else 'STL'})"),
            "format": fmt, "units": "m" if fmt == "step_faceted" else st["units"],
            "transform": {"axes": spec["axes"], "origin_m": spec.get("origin_m", [0.0, 0.0, 0.0])},
            "source": f"Creo export {spec['file']} with the CREO settings transform ({note})"}
        changes.append(f"{spec['instance']}: outer skin {spec['file']} ({note})")
    return changes
