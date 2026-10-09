# ArduPilot spoke

Flight events and firmware releases. A flight keeps its ArduPilot DataFlash log as a linked asset.

| Item | Place |
|---|---|
| Input | `ArduPilot/work/<aircraft>/<log>.bin` and `<params>.param` (NAME,VALUE lines) |
| Settings | `settings/<aircraft>.yaml`: `releases` (release_id, firmware, version, git_hash, board, source) and `flights` (event_id, date, log, params, firmware, aircraft_version, package_hash, mass_kg, cg_m, segments, source) |
| Writes | 1.2.9 `muas.software_releases`, 1.8.1.4 `muas.flight_tests` (one `FlightEvent` for each flight), the parameters of each flight as a dataset `parameters.<event_id>`, the log as a linked asset |

`package_hash` names the `.muas` package of the configuration that flew. The as-flown mass and CG come from the
weighing of that flight (say who weighed it in `source`).

Open item: the spoke does not decode the log yet. The decoded record (a dataset of role `flight-record`) comes later.
