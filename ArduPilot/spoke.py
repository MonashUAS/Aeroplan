"""ArduPilot spoke: flight events -> 1.8.1.4 FlightTests and firmware releases -> 1.2.9 AirVehicleSoftwareRelease.

Input (git ignores it): ArduPilot/work/<aircraft>/
    <log>.bin           the DataFlash log of a flight (kept as a linked asset: it never goes into a package
                        except the archive profile)
    <params>.param      the parameter file of the flight (NAME,VALUE or NAME VALUE lines, # starts a comment)
Settings (committed): ArduPilot/settings/<aircraft>.yaml
    releases    a list of {release_id, firmware, version, git_hash, board, source}
    flights     a list of {event_id, date, log, params, firmware (a release_id), aircraft_version, package_hash,
                mass_kg, cg_m [x, y, z] (design frame), segments [{name, t_start_s, t_end_s, purpose, note}],
                source (who weighed it and how)}

What ingest writes:
  - each release: an item of `muas.software_releases` on 1.2.9
  - each flight: an item of `muas.flight_tests` on 1.8.1.4. The log is a linked asset. The parameters are a
    dataset (form parameters, role parameters, `parameters.<event_id>`).
Later: the decoded log (a normalised record dataset of role flight-record) for system identification.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from aeroplan import adh_doc
from aeroplan.spokes import Context

NAME = "ArduPilot"


def read_params(path: Path) -> Dict[str, float]:
    """The parameters of an ArduPilot .param file. Refuses a line that is not NAME,VALUE or NAME VALUE."""
    out: Dict[str, float] = {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.replace(",", " ").split()
        if len(parts) != 2:
            raise ValueError(f"{path.name} line {i}: {line!r} is not NAME,VALUE")
        try:
            out[parts[0]] = float(parts[1])
        except ValueError:
            raise ValueError(f"{path.name} line {i}: {parts[1]!r} is not a number") from None
    return out


def ingest(doc: Dict[str, Any], ctx: Context):
    st = ctx.settings()
    if not st or not (st.get("flights") or st.get("releases")):
        return None
    changes: List[str] = []
    if st.get("releases"):
        sw = adh_doc.node(doc, "1.2.9", create=True)
        adh_doc.muas(sw, "air_vehicle_software_release")["software_releases"] = list(st["releases"])
        changes.append(f"software releases: {', '.join(r['release_id'] for r in st['releases'])}")
    known = {r["release_id"] for r in st.get("releases") or []}
    events = []
    ft = adh_doc.node(doc, "1.8.1.4", create=True) if st.get("flights") else None
    if ft is not None:
        adh_doc.muas(ft, "flight_tests")
    for f in st.get("flights") or []:
        if f["firmware"] not in known:
            raise ValueError(f"flight {f['event_id']}: firmware {f['firmware']!r} is not a release of the settings")
        log = ctx.work / f["log"]
        if not log.is_file():
            raise ValueError(f"flight {f['event_id']}: the log {log.name} is not in {ctx.work}")
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
                ft, f"parameters.{f['event_id']}", read_params(p), role=f"parameters of flight {f['event_id']}",
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
