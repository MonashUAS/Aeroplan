"""The flight files of an aircraft: ArduPilot parameters, the waypoint plan and the geofence.

Three Mission Planner files go into the `.muas` package as datasets of the autopilot node (1.2.5.10):

| Dataset role | Form       | JSON value                                                             | File on disk        |
|--------------|------------|------------------------------------------------------------------------|---------------------|
| `parameters` | parameters | `{NAME: number}`                                                       | `.parm` NAME,VALUE  |
| `waypoints`  | waypoints  | `{"format": "QGC WPL 110", "items": [{seq, frame, command, ...}]}`     | `.waypoints`        |
| `geofence`   | geofence   | `{"return_point"?, "polygons": [...], "circles": [...]}`               | `.poly` (one each)  |

A dataset holds the data, not the text of the file. The writers below make the file again, byte for byte the same
for the same data. So the file that Mission Planner loads comes from the package, and a change of the data gives a
new dataset hash.

Rules of the forms (the HDF5 mapping of `h5json` keeps the JSON value exact only when these hold):
  - every number of a waypoint item is a float, except seq, frame, command and autocontinue (int);
  - every number of a parameter is a float;
  - a geofence point is `{"lat": float, "lon": float}` in degrees. The fence is bound to the place, so it has
    absolute positions. A waypoint item has absolute positions too (a QGC WPL file has no other form).

Sources of the formats:
  - QGC WPL 110: https://mavlink.io/en/file_formats/#mission_plain_text_file
  - Parameter file: https://ardupilot.org/planner/docs/mission-planner-parameters.html (NAME,VALUE)
  - Fence commands MAV_CMD_NAV_FENCE_*: https://mavlink.io/en/messages/common.html#MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION
  - Polygon file: one `lat lon` pair for each line, `#` starts a comment (the Mission Planner polygon file)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

WPL_HEADER = "QGC WPL 110"
WPL_INT = ("seq", "frame", "command", "autocontinue")
WPL_FLOAT = ("p1", "p2", "p3", "p4", "lat", "lon", "alt")
WPL_FIELDS = WPL_INT[:3] + WPL_FLOAT[:4] + ("lat", "lon", "alt") + ("autocontinue",)

#: ArduPilot FENCE_TYPE bit values (ArduPlane): the polygon fence is bit 2 (value 4)
FENCE_TYPE_POLYGON = 4


class FlightFileError(ValueError):
    """A flight file is not readable, or its data breaks a rule."""


# ---------------------------------------------------------------------------------------------------- parameters
def parse_parm(text: str, name: str = "parameter file") -> Dict[str, float]:
    """The parameters of a `.parm` / `.param` text: `NAME,VALUE` or `NAME VALUE`, `#` starts a comment.

    Refuses a line that is not a name and one number, and a name that appears twice with other values."""
    out: Dict[str, float] = {}
    for i, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.replace(",", " ").split()
        if len(parts) != 2:
            raise FlightFileError(f"{name} line {i}: {line!r} is not NAME,VALUE")
        try:
            value = float(parts[1])
        except ValueError:
            raise FlightFileError(f"{name} line {i}: {parts[1]!r} is not a number") from None
        if not np.isfinite(value):
            raise FlightFileError(f"{name} line {i}: {parts[0]} is not a finite number")
        if parts[0] in out and out[parts[0]] != value:
            raise FlightFileError(f"{name} line {i}: {parts[0]} appears twice with other values")
        out[parts[0]] = value
    if not out:
        raise FlightFileError(f"{name} holds no parameter")
    return out


def format_parm(params: Dict[str, float], header: str = "") -> str:
    """Sorted `NAME,VALUE` lines. The value is the shortest text that gives the same float32 (the type of an
    ArduPilot parameter), so Mission Planner shows the number that the autopilot holds."""
    lines = [f"# {h}" for h in header.splitlines()] if header else []
    lines += [f"{k},{np.format_float_positional(np.float32(v), unique=True, trim='-')}" for k, v in sorted(params.items())]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------------- waypoints
def parse_wpl(text: str, name: str = "waypoint file") -> Dict[str, Any]:
    """A QGC WPL 110 text -> the `waypoints` dataset value. Item 0 is the home position."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("QGC WPL"):
        raise FlightFileError(f"{name} is not a QGC WPL file (the first line is {WPL_HEADER!r})")
    if lines[0].strip() != WPL_HEADER:
        raise FlightFileError(f"{name}: format {lines[0].strip()!r}. Only {WPL_HEADER!r} is read")
    items: List[Dict[str, Any]] = []
    for i, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        f = line.split()
        if len(f) != 12:
            raise FlightFileError(f"{name} line {i}: {len(f)} fields, a QGC WPL line has 12")
        try:
            item = {"seq": int(f[0]), "frame": int(f[2]), "command": int(f[3]),
                    "p1": float(f[4]), "p2": float(f[5]), "p3": float(f[6]), "p4": float(f[7]),
                    "lat": float(f[8]), "lon": float(f[9]), "alt": float(f[10]), "autocontinue": int(f[11])}
        except ValueError as err:
            raise FlightFileError(f"{name} line {i}: {err}") from None
        items.append(item)
    return check_waypoints({"format": WPL_HEADER, "items": items}, name)


def check_waypoints(value: Dict[str, Any], name: str = "waypoints") -> Dict[str, Any]:
    """Check a `waypoints` dataset value. Returns it."""
    items = value.get("items")
    if value.get("format") != WPL_HEADER or not isinstance(items, list) or len(items) < 2:
        raise FlightFileError(f"{name}: needs format {WPL_HEADER!r} and at least two items (home and one command)")
    for n, it in enumerate(items):
        if set(it) != set(WPL_FIELDS):
            raise FlightFileError(f"{name} item {n}: fields must be {', '.join(WPL_FIELDS)}")
        if it["seq"] != n:
            raise FlightFileError(f"{name} item {n}: seq is {it['seq']}, items must run 0, 1, 2, ...")
        for k in WPL_INT:
            if type(it[k]) is not int:
                raise FlightFileError(f"{name} item {n}: {k} must be an integer")
        for k in WPL_FLOAT:
            if type(it[k]) is not float or not np.isfinite(it[k]):
                raise FlightFileError(f"{name} item {n}: {k} must be a finite float")
        if abs(it["lat"]) > 90 or abs(it["lon"]) > 180:
            raise FlightFileError(f"{name} item {n}: lat {it['lat']}, lon {it['lon']} is not a position")
    return value


def format_wpl(value: Dict[str, Any]) -> str:
    """The QGC WPL 110 text of a `waypoints` dataset value (tab separated). Item 0 is the current item."""
    check_waypoints(value)
    lines = [WPL_HEADER]
    for it in value["items"]:
        lines.append("\t".join([
            str(it["seq"]), "1" if it["seq"] == 0 else "0", str(it["frame"]), str(it["command"]),
            f"{it['p1']:.8g}", f"{it['p2']:.8g}", f"{it['p3']:.8g}", f"{it['p4']:.8g}",
            f"{it['lat']:.8f}", f"{it['lon']:.8f}", f"{it['alt']:.6f}", str(it["autocontinue"])]))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------------- geofence
def parse_poly(text: str, name: str = "polygon file") -> List[Dict[str, float]]:
    """The points of a polygon file (`lat lon` for each line). A last point equal to the first closes the
    polygon in some tools: it is dropped. A polygon has three points at least."""
    pts: List[Dict[str, float]] = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.replace(",", " ").split()
        if len(parts) != 2:
            raise FlightFileError(f"{name} line {i}: {line!r} is not `lat lon`")
        try:
            pts.append({"lat": float(parts[0]), "lon": float(parts[1])})
        except ValueError:
            raise FlightFileError(f"{name} line {i}: {line!r} is not `lat lon`") from None
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return _check_points(pts, name)


def _check_points(pts: List[Dict[str, float]], name: str) -> List[Dict[str, float]]:
    if len(pts) < 3:
        raise FlightFileError(f"{name}: a polygon needs three points at least")
    for p in pts:
        if type(p["lat"]) is not float or type(p["lon"]) is not float or abs(p["lat"]) > 90 or abs(p["lon"]) > 180:
            raise FlightFileError(f"{name}: lat {p['lat']}, lon {p['lon']} is not a position")
    return pts


def make_geofence(polygons: List[Dict[str, Any]], circles: Optional[List[Dict[str, Any]]] = None,
                  return_point: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """The `geofence` dataset value. A polygon is {"inclusion": bool, "points": [{lat, lon}]}, a circle is
    {"inclusion": bool, "lat", "lon", "radius_m"}. The fence has an inclusion polygon or circle at least."""
    out: Dict[str, Any] = {"polygons": [], "circles": []}
    for i, p in enumerate(polygons):
        out["polygons"].append({"inclusion": bool(p["inclusion"]),
                                "points": _check_points([{"lat": float(q["lat"]), "lon": float(q["lon"])}
                                                         for q in p["points"]], f"polygon {i}")})
    for i, c in enumerate(circles or []):
        r = float(c["radius_m"])
        if r <= 0:
            raise FlightFileError(f"circle {i}: radius_m must be above 0")
        out["circles"].append({"inclusion": bool(c["inclusion"]), "lat": float(c["lat"]), "lon": float(c["lon"]),
                               "radius_m": r})
    if return_point is not None:
        out["return_point"] = {"lat": float(return_point["lat"]), "lon": float(return_point["lon"])}
    if not any(s["inclusion"] for s in out["polygons"] + out["circles"]):
        raise FlightFileError("a geofence needs an inclusion polygon or circle")
    return out


def format_poly(points: List[Dict[str, float]], header: str = "") -> str:
    """A polygon file: one `lat lon` line for each point."""
    lines = [f"# {h}" for h in header.splitlines()] if header else []
    lines += [f"{p['lat']:.8f} {p['lon']:.8f}" for p in points]
    return "\n".join(lines) + "\n"


def fence_files(fence: Dict[str, Any], stem: str) -> Dict[str, str]:
    """The polygon files of a geofence: {file name: text}. `<stem>_fence_<n>_<inclusion|exclusion>.poly`. Circles
    and the return point have no polygon file: they go to the autopilot by MAVLink (Aerolink) or by hand."""
    return {f"{stem}_fence_{n}_{'inclusion' if p['inclusion'] else 'exclusion'}.poly":
            format_poly(p["points"], f"Geofence {'inclusion' if p['inclusion'] else 'exclusion'} polygon {n} of {stem}")
            for n, p in enumerate(fence["polygons"], 1)}


def write_all(out: Path, stem: str, *, parameters: Optional[Dict[str, float]] = None,
              waypoints: Optional[Dict[str, Any]] = None, geofence: Optional[Dict[str, Any]] = None,
              header: str = "") -> List[Path]:
    """Write the files that Mission Planner loads into `out`. Returns the paths."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    files: Dict[str, str] = {}
    if parameters is not None:
        files[f"{stem}.parm"] = format_parm(parameters, header)
    if waypoints is not None:
        files[f"{stem}.waypoints"] = format_wpl(waypoints)
    if geofence is not None:
        files.update(fence_files(geofence, stem))
    paths = []
    for name, text in files.items():
        p = out / name
        p.write_text(text, encoding="ascii", newline="\n")
        paths.append(p)
    return paths


# ---------------------------------------------------------------------------------------------------- checks
def fence_param_warnings(fence: Optional[Dict[str, Any]], params: Optional[Dict[str, float]]) -> List[str]:
    """Why the parameters do not switch the fence on. ArduPlane needs FENCE_ENABLE = 1 and the polygon bit
    (value 4) in FENCE_TYPE. A warning, not an error: the parameter file may come from a bench set-up."""
    if not fence or params is None:
        return []
    out = []
    if params.get("FENCE_ENABLE", 0.0) != 1.0:
        out.append("geofence: FENCE_ENABLE is not 1 in the parameters, so the autopilot ignores the fence")
    if fence["polygons"] and int(params.get("FENCE_TYPE", 0.0)) & FENCE_TYPE_POLYGON == 0:
        out.append("geofence: FENCE_TYPE has no polygon bit (value 4), so the autopilot ignores the polygons")
    return out
