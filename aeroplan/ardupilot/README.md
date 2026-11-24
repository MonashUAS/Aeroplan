# ArduPilot spoke

Flight events, firmware releases and the flight files of the aircraft. One spoke, one settings file, one work folder.

| Item | Place |
|---|---|
| Input | `work/ardupilot/<aircraft>/`: DataFlash log `<log>.BIN`, flight parameters `<params>.param`, aircraft files `<name>.parm`, `<name>.waypoints`, `<name>.poly` |
| Settings | `settings/<aircraft>.yaml`: `releases`, `flights` (flight events) and `flight_files` (see below) |
| Writes | 1.2.9 `muas.software_releases`. 1.8.1.4 `muas.flight_tests` (one `FlightEvent` for each flight), the parameters of each flight as dataset `parameters.<event_id>`, the log as a linked asset. 1.2.5.10 datasets `autopilot.parameters` (role parameters), `autopilot.waypoints` (role waypoints), `autopilot.geofence` (role geofence) |
| Export | `python -m aeroplan export ArduPilot <aircraft> <out>` writes `<aircraft>.parm`, `<aircraft>.waypoints` and `<aircraft>_fence_<n>_inclusion.poly` (or `_exclusion`) |
| Package | the `aerolink` profile embeds the three flight files. Aerolink extracts them and writes them into the aircraft |

## Flight events

`releases`: release_id, firmware, version, git_hash, board, source. `flights`: event_id, date, log, params, firmware,
aircraft_version, package_hash, mass_kg, cg_m, segments, source.

`package_hash` names the `.muas` package of the configuration that flew. The as-flown mass and CG come from the weighing
of that flight (say who weighed it in `source`). `wait_for_log: true` on a flight skips it with a note until the log is
in the work folder. `mass_kg: document` and `cg_m: document` take the mass model of node 1.2.

A flight (`params`) and the aircraft (`flight_files.parameters`) need two files with different content. AeroPlan registers one dataset for each file hash and refuses one file in two roles. Use the PARM messages of the log for the flight and a Mission Planner save for the aircraft.

Open item: the spoke does not decode the log yet. The decoded record (a dataset of role `flight-record`) comes later.

## Flight files

Save the files in Mission Planner:

- `.parm`: Config > Full Parameter List > Save.
- `.waypoints`: Plan > Save WP File (QGC WPL 110).
- `.poly`: the polygon file (`lat lon` for each line, `#` starts a comment).

```yaml
flight_files:
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

- A dataset holds the data, not the text. The export writes the file again from the data, so the text is the same each time. Comments of the original file stay in the raw file (a linked asset), not in the package.
- A waypoint item has an absolute position (a QGC WPL file has no other form). A mission with positions relative to a runway stays an ADH requirement (`muas.mission`).
- The build warns when a fence is present and the parameters do not switch it on (`FENCE_ENABLE`, `FENCE_TYPE`).
- A key that the section does not name leaves the old dataset in place. A changed raw file gives a new dataset hash.
- `optional: true` in `flight_files` skips a missing file with a note.
