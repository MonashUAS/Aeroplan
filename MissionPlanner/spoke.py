"""Mission Planner spoke: the flight files of the aircraft -> datasets of the autopilot node (1.2.5.10).

Input (git ignores it): MissionPlanner/work/<aircraft>/
    <name>.parm           the parameters of the aircraft (Mission Planner: Config > Full Parameter List > Save)
    <name>.waypoints      the plan (Mission Planner: Plan > Save WP File, format QGC WPL 110)
    <name>.poly           a fence polygon (the polygon file, `lat lon` for each line)
Settings (committed): MissionPlanner/settings/<aircraft>.yaml
    firmware    the firmware release that the parameters belong to, for example "ArduPlane 4.7.0"
    parameters  the file name of the .parm
    waypoints   the file name of the .waypoints
    geofence    source (who drew the fence and where), polygons [{file, kind: inclusion|exclusion}],
                circles [{lat, lon, radius_m, kind}], return_point {lat, lon}
Each key is optional. A key that is not in the settings leaves the old dataset in place.
    optional    true: a file that is not in the work folder is skipped with a note (the user has not copied it yet). When
                no file is left, the spoke has no input. Without `optional`, a missing file is an error.

What ingest writes (datasets of role parameters, waypoints, geofence, on 1.2.5.10 `muas.datasets`):
    autopilot.parameters, autopilot.waypoints, autopilot.geofence
The `aerolink` package embeds them. `aeroplan export MissionPlanner <aircraft> <out>` writes the files that
Mission Planner loads. Aerolink extracts the same files from the package and can write them into the aircraft.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from aeroplan import adh_doc, flightfiles
from aeroplan.assets import item_dataset
from aeroplan.consumers import FLIGHT_PARAMETERS
from aeroplan.spokes import Context

NAME = "MissionPlanner"
AUTOPILOT = "1.2.5.10"
WAYPOINTS, GEOFENCE = "autopilot.waypoints", "autopilot.geofence"


def _file(ctx: Context, name: str, what: str) -> Path:
    p = ctx.work / name
    if not p.is_file():
        raise flightfiles.FlightFileError(f"{what}: {name} is not in {ctx.work}")
    return p


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


def _dataset(ctx: Context, ap: Dict[str, Any], role: str):
    d = item_dataset(ap, role)
    return ctx.dataset(d["ref"]) if d else None


def _kind(e: Dict[str, Any]) -> bool:
    if e.get("kind") not in ("inclusion", "exclusion"):
        raise flightfiles.FlightFileError(f"geofence entry {e}: kind must be inclusion or exclusion")
    return e["kind"] == "inclusion"


def _fence(ctx: Context, g: Dict[str, Any]):
    if not g.get("source"):
        raise flightfiles.FlightFileError("geofence: `source` says who drew the fence and where (no unsourced number)")
    polys, refs = [], []
    for e in g.get("polygons") or []:
        p = _file(ctx, e["file"], "geofence")
        polys.append({"inclusion": _kind(e), "points": flightfiles.parse_poly(_text(p), p.name)})
        refs.append(ctx.source_ref(p, "fence polygon of the aircraft")["asset"])
    circles = [{**c, "inclusion": _kind(c)} for c in g.get("circles") or []]
    return flightfiles.make_geofence(polys, circles, g.get("return_point")), refs


def _drop_missing(st: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    """The settings without the keys whose file is not in the work folder (a note says which)."""
    st = dict(st)
    for key in ("parameters", "waypoints"):
        if st.get(key) and not (ctx.work / st[key]).is_file():
            print(f"MissionPlanner: {st[key]} is not in {ctx.work.relative_to(ctx.root).as_posix()}: {key} skipped. "
                  "Copy the file there by hand.")
            st.pop(key)
    g = st.get("geofence")
    if g and any(not (ctx.work / e["file"]).is_file() for e in g.get("polygons") or []):
        print("MissionPlanner: a fence polygon file is missing: geofence skipped.")
        st.pop("geofence")
    return st


def ingest(doc: Dict[str, Any], ctx: Context):
    st = ctx.settings()
    if not st or not (st.get("parameters") or st.get("waypoints") or st.get("geofence")):
        return None
    if st.get("optional"):
        st = _drop_missing(st, ctx)
        if not (st.get("parameters") or st.get("waypoints") or st.get("geofence")):
            return None
    ap = adh_doc.node(doc, AUTOPILOT, create=True)
    adh_doc.muas(ap, "autopilot")
    base = {"generation_tool": "Mission Planner", "version": str(st.get("firmware") or "unknown")}
    changes: List[str] = []
    try:
        if st.get("parameters"):
            p = _file(ctx, st["parameters"], "parameters")
            params = flightfiles.parse_parm(_text(p), p.name)
            ref = ctx.source_ref(p, "ArduPilot parameter file of the aircraft")
            ctx.add_dataset(ap, FLIGHT_PARAMETERS, params, role="autopilot parameters", dataset_role="parameters",
                            derived_from=[ref["asset"]],
                            meta={"form": "parameters", "fidelity": "L4", "units_system": "as-source",
                                  "model_description": base})
            changes.append(f"parameters: {len(params)} from {p.name}")
        if st.get("waypoints"):
            p = _file(ctx, st["waypoints"], "waypoints")
            wp = flightfiles.parse_wpl(_text(p), p.name)
            ref = ctx.source_ref(p, "waypoint plan of the aircraft")
            ctx.add_dataset(ap, WAYPOINTS, wp, role="autopilot waypoint plan", dataset_role="waypoints",
                            derived_from=[ref["asset"]],
                            meta={"form": "waypoints", "fidelity": "L4", "units_system": "as-source",
                                  "model_description": base})
            changes.append(f"waypoints: {len(wp['items']) - 1} items and home from {p.name}")
        if st.get("geofence"):
            fence, refs = _fence(ctx, st["geofence"])
            ctx.add_dataset(ap, GEOFENCE, fence, role="autopilot geofence", dataset_role="geofence",
                            derived_from=refs,
                            meta={"form": "geofence", "fidelity": "L4", "units_system": "as-source",
                                  "model_description": base, "notes": [str(st["geofence"]["source"])]})
            changes.append(f"geofence: {len(fence['polygons'])} polygons, {len(fence['circles'])} circles")
    except flightfiles.FlightFileError as err:
        raise ValueError(f"MissionPlanner spoke: {err}") from err
    # the fence works only when the parameters of the aircraft switch it on (old datasets count too)
    changes += flightfiles.fence_param_warnings(_dataset(ctx, ap, "geofence"), _dataset(ctx, ap, "parameters"))
    return changes


def export(doc: Dict[str, Any], ctx: Context, out: Path) -> List[Path]:
    """The files that Mission Planner loads, from the datasets of the aircraft."""
    ap = adh_doc.node(doc, AUTOPILOT)
    got = {r: _dataset(ctx, ap, r) for r in ("parameters", "waypoints", "geofence")}
    if not any(got.values()):
        raise ValueError(f"{ctx.aircraft} has no flight files: run the MissionPlanner spoke first")
    return flightfiles.write_all(Path(out), ctx.aircraft, parameters=got["parameters"], waypoints=got["waypoints"],
                                 geofence=got["geofence"],
                                 header=f"Parameters of {ctx.aircraft} {ctx.acft.version}. Generated by AeroPlan, DO NOT EDIT.")
