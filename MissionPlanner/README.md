# Mission Planner spoke

The flight files of the aircraft: the ArduPilot parameters, the waypoint plan and the geofence. They go into the
`.muas` package, so one file holds the aircraft and everything it needs to fly.

| Item | Place |
|---|---|
| Input | `MissionPlanner/work/<aircraft>/`: `<name>.parm`, `<name>.waypoints`, `<name>.poly` |
| Settings | `settings/<aircraft>.yaml`: `firmware`, `parameters`, `waypoints`, `geofence` (see below) |
| Writes | datasets on 1.2.5.10 `muas.datasets`: `autopilot.parameters` (role parameters), `autopilot.waypoints` (role waypoints), `autopilot.geofence` (role geofence) |
| Export | `python -m aeroplan export MissionPlanner <aircraft> <out>` writes `<aircraft>.parm`, `<aircraft>.waypoints` and `<aircraft>_fence_<n>_inclusion.poly` (or `_exclusion`) |
| Package | the `aerolink` profile embeds all three. Aerolink extracts them and writes them into the aircraft |

Save the files in Mission Planner:

- `.parm`: Config > Full Parameter List > Save.
- `.waypoints`: Plan > Save WP File (QGC WPL 110).
- `.poly`: the polygon file (`lat lon` for each line, `#` starts a comment).

```yaml
firmware: ArduPlane 4.7.0
parameters: currawong_flight.parm
waypoints: demo.waypoints
geofence:
  source: "drawn by Liam M. in Mission Planner, field survey 2026-10-12"   # required
  return_point: {lat: -27.0, lon: 153.0}                                    # optional
  polygons:
    - {file: boundary.poly, kind: inclusion}
    - {file: lake.poly, kind: exclusion}
  circles:
    - {lat: -27.0, lon: 153.0, radius_m: 300.0, kind: exclusion}
```

Rules:

- A dataset holds the data, not the text. The export writes the file again from the data, so the text is the same each
  time. Comments of the original file stay in the raw file (a linked asset), not in the package.
- A waypoint item has an absolute position (a QGC WPL file has no other form). A mission with positions relative to a
  runway stays an ADH requirement (`muas.mission`).
- The build warns when a fence is present and the parameters do not switch it on (`FENCE_ENABLE`, `FENCE_TYPE`).
- A key that the settings do not name leaves the old dataset in place. A changed raw file gives a new dataset hash.

`optional: true` in the settings skips a missing file with a note.
