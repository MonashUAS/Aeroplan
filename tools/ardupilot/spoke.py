"""ArduPilot spoke: flight events and flight files of the autopilot.

Input (git ignores it): work/ardupilot/<aircraft>/
    <log>.BIN           the DataFlash log of a flight (kept as a linked asset: it never goes into a package
                        except the archive profile)
    <params>.param      the parameter file of the flight (NAME,VALUE or NAME VALUE lines, # starts a comment)
    <name>.parm         the parameters of the aircraft (Mission Planner: Config > Full Parameter List > Save)
    <name>.waypoints    the plan (Mission Planner: Plan > Save WP File, format QGC WPL 110)
    <name>.poly         a fence polygon (the polygon file, `lat lon` for each line)
Settings (committed, one file for each aircraft): tools/ardupilot/settings/<aircraft>.yaml
  Flight events (node 1.8.1.4 and 1.2.9):
    releases    a list of {release_id, firmware, version, git_hash, board, source}
    flights     a list of {event_id, date, log, params, firmware (a release_id), aircraft_version, package_hash,
                mass_kg, cg_m [x, y, z] (design frame), segments [{name, t_start_s, t_end_s, purpose, note}],
                source (who weighed it and how), wait_for_log}
    wait_for_log   true: the flight is a stub. When its log is not in the work folder, the spoke skips the flight and prints a
                   note (the other flights and the releases are still written). Without it, a missing log is an error.
    mass_kg, cg_m  the word `document` takes the mass or the CG of node 1.2 muas.mass_properties (the as-built mass model)
  Flight files (node 1.2.5.10), the section `flight_files`:
    firmware    the firmware release that the parameters belong to, for example "ArduPlane 4.7.0"
    parameters  the file name of the .parm
    waypoints   the file name of the .waypoints
    geofence    source (who drew the fence and where), polygons [{file, kind: inclusion|exclusion}],
                circles [{lat, lon, radius_m, kind}], return_point {lat, lon}
    optional    true: a file that is not in the work folder is skipped with a note (the user has not copied it yet). When
                no file is left, the section has no input. Without `optional`, a missing file is an error.
    Each key is optional. A key that is not in the section leaves the old dataset in place.

What ingest writes:
  - each release: an item of `muas.software_releases` on 1.2.9
  - each flight: an item of `muas.flight_tests` on 1.8.1.4. The log is a linked asset. The parameters of the flight are a
    dataset (form parameters, role parameters, `parameters.<event_id>`).
  - the flight files: datasets of role parameters, waypoints, geofence on 1.2.5.10 `muas.datasets`:
    autopilot.parameters, autopilot.waypoints, autopilot.geofence. The `aerolink` package embeds them.
`aeroplan export ArduPilot <aircraft> <out>` writes the files that Mission Planner loads. Aerolink extracts the same
files from the package and can write them into the aircraft.
Later: the decoded log (a normalised record dataset of role flight-record) for system identification.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from aeroplan import adh_doc, flightfiles
from aeroplan.assets import item_dataset
from aeroplan.consumers import FLIGHT_PARAMETERS
from aeroplan.spokes import Context

NAME = "ArduPilot"
AUTOPILOT = "1.2.5.10"
WAYPOINTS, GEOFENCE = "autopilot.waypoints", "autopilot.geofence"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


# ------------------------------------------------------------------------------------------------ flight events
def _as_built(doc: Dict[str, Any], f: Dict[str, Any]) -> Dict[str, Any]:
    """The flight with `mass_kg: document` and `cg_m: document` replaced by the mass model of node 1.2."""
    f = dict(f)
    if "document" in (f.get("mass_kg"), f.get("cg_m")):
        mp = (adh_doc.node(doc, "1.2").get("muas") or {}).get("mass_properties")
        if mp is None:
            raise ValueError(f"flight {f['event_id']}: mass_kg or cg_m is `document`, but node 1.2 has no mass_properties")
        if f.get("mass_kg") == "document":
            f["mass_kg"] = mp["mass"]["value"]
        if f.get("cg_m") == "document":
            f["cg_m"] = list(mp["cg"]["xyz"])
    return f


def _ingest_events(doc: Dict[str, Any], ctx: Context, st: Dict[str, Any]) -> Optional[List[str]]:
    if not st or not (st.get("flights") or st.get("releases")):
        return None
    changes: List[str] = []
    if st.get("releases"):
        sw = adh_doc.node(doc, "1.2.9", create=True)
        adh_doc.muas(sw, "air_vehicle_software_release")["software_releases"] = list(st["releases"])
        changes.append(f"software releases: {', '.join(r['release_id'] for r in st['releases'])}")
    known = {r["release_id"] for r in st.get("releases") or []}
    events = []
    flights = []
    for f in st.get("flights") or []:
        log = ctx.work / f["log"]
        if not log.is_file() and f.get("wait_for_log"):
            print(f"ArduPilot: flight {f['event_id']}: the log {log.relative_to(ctx.root).as_posix()} is not here: flight "
                  "skipped. Copy the DataFlash log into that folder by hand.")
            continue
        flights.append(f)
    if not flights and not st.get("releases"):
        return None
    ft = adh_doc.node(doc, "1.8.1.4", create=True) if flights else None
    if ft is not None:
        adh_doc.muas(ft, "flight_tests")
    for f in flights:
        if f["firmware"] not in known:
            raise ValueError(f"flight {f['event_id']}: firmware {f['firmware']!r} is not a release of the settings")
        log = ctx.work / f["log"]
        if not log.is_file():
            raise ValueError(f"flight {f['event_id']}: the log {log.name} is not in {ctx.work}")
        f = _as_built(doc, f)
        log_ref = ctx.source_ref(log, f"DataFlash log of flight {f['event_id']}")
        ev = {"event_id": f["event_id"], "date": str(f["date"]), "aircraft_version": f["aircraft_version"],
              "mass": {"value": f["mass_kg"], "units": "kg"}, "cg": {"xyz": list(f["cg_m"])},
              "firmware": f["firmware"], "log": log_ref["asset"], "segments": list(f.get("segments") or []),
              "source": f["source"]}
        if f.get("package_hash"):
            ev["package_hash"] = f["package_hash"]
        if f.get("params"):
            p = ctx.work / f["params"]
            p_ref = ctx.source_ref(p, f"parameter file of flight {f['event_id']}")
            ev["parameters"] = ctx.add_dataset(
                ft, f"parameters.{f['event_id']}", flightfiles.parse_parm(_text(p), p.name), role=f"parameters of flight {f['event_id']}",
                dataset_role="parameters", derived_from=[p_ref["asset"]],
                meta={"form": "parameters", "fidelity": "L4", "units_system": "as-source",
                      "model_description": {"generation_tool": "ArduPilot parameter file",
                                            "version": f["firmware"]}})
        events.append(ev)
        changes.append(f"flight {f['event_id']}: {len(ev['segments'])} segments")
    if ft is not None:
        m = ft["muas"]
        m["flight_tests"] = events
        # one parameters dataset for each flight: the item points at the last one, each event names its own
        m.pop("datasets", None)
    return changes


# ------------------------------------------------------------------------------------------------ flight files
def _file(ctx: Context, name: str, what: str) -> Path:
    p = ctx.work / name
    if not p.is_file():
        raise flightfiles.FlightFileError(f"{what}: {name} is not in {ctx.work}")
    return p


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
            print(f"ArduPilot: {st[key]} is not in {ctx.work.relative_to(ctx.root).as_posix()}: {key} skipped. "
                  "Copy the file there by hand.")
            st.pop(key)
    g = st.get("geofence")
    if g and any(not (ctx.work / e["file"]).is_file() for e in g.get("polygons") or []):
        print("ArduPilot: a fence polygon file is missing: geofence skipped.")
        st.pop("geofence")
    return st


def _ingest_files(doc: Dict[str, Any], ctx: Context, st: Dict[str, Any]) -> Optional[List[str]]:
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
        raise ValueError(f"ArduPilot spoke: {err}") from err
    # the fence works only when the parameters of the aircraft switch it on (old datasets count too)
    changes += flightfiles.fence_param_warnings(_dataset(ctx, ap, "geofence"), _dataset(ctx, ap, "parameters"))
    return changes

def ingest(doc: Dict[str, Any], ctx: Context):
    """Flight events first (they read the mass model of node 1.2), then the flight files. None: no input."""
    st = ctx.settings()
    if not st:
        return None
    a = _ingest_events(doc, ctx, st)
    b = _ingest_files(doc, ctx, st.get("flight_files") or {})
    return None if a is None and b is None else (a or []) + (b or [])


def export(doc: Dict[str, Any], ctx: Context, out: Path) -> List[Path]:
    """The files that Mission Planner loads, from the datasets of the aircraft."""
    ap = adh_doc.node(doc, AUTOPILOT)
    got = {r: _dataset(ctx, ap, r) for r in ("parameters", "waypoints", "geofence")}
    if not any(got.values()):
        raise ValueError(f"{ctx.aircraft} has no flight files: run the ArduPilot spoke first")
    return flightfiles.write_all(Path(out), ctx.aircraft, parameters=got["parameters"], waypoints=got["waypoints"],
                                 geofence=got["geofence"],
                                 header=f"Parameters of {ctx.aircraft} {ctx.acft.version}. Generated by AeroPlan, DO NOT EDIT.")
