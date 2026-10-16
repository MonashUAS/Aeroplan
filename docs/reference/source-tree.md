# The source tree

```
aircraft/<aircraft>/
  aircraft.yaml                 name, kind (aircraft or flight-record), consumers (the profiles it serves)
  adh/<wbs>.<key>.json          one file for each ADH node, without its child nodes (subcomponents stay inside)
  datasets/<name>.json          one file for each dataset of the asset register
```

- A child node sits under the snake_case name of its upstream class (`air_vehicle`, `airframe`, `wing`).
- MUAS additions sit under the `muas` key of a node, typed with `extra="forbid"`.
- The asset register is `muas.assets` of node `1.10.2 DataRepository`. Each large file or dataset has one entry and one ID: `asset:sha256:<hash>`. Every other item names the ID, never a path. A file asset has the hash of its bytes. A dataset has the hash of its canonical JSON. A dataset is never edited: a change gives a new dataset.
- A derived asset records `derived_from` and `built_against`. An input that left the register makes the datum check warn that the asset is stale.
- Each dataset entry carries the source tool and version (ADH `ModelDescription`), the fidelity, the role, the sigma (ADH `Uncertainty`) and the moment reference point.

| Content | ADH node |
|---|---|
| Asset register | `1.10.2 DataRepository` |
| Flight events: configuration flown, as-flown mass and CG, firmware and parameters, segments | `1.8.1.4 FlightTests` |
| Firmware releases | `1.2.9 AirVehicleSoftwareRelease` |
| Flight files: parameters, waypoints, geofence | `1.2.5.10 AutomaticFlightControl` (datasets) |
| Geometry, mass, aero and propulsion data of a part | the node of the part |

Source code map:

| Module | Job |
|---|---|
| `source_tree.py` | The source tree `aircraft/<aircraft>/` <-> the `Aircraft` in memory |
| `assets.py` | The asset register: IDs, file and dataset entries, references, fetch with hash check |
| `flightfiles.py` | Parse and write `.parm`, QGC WPL `.waypoints`, fence polygons, the fence parameter check |
| `package.py` | `.muas` ZIP package: pack, open, unpack |
| `consumers.py` | Packing profiles, storage tiers, what Aerolink needs |
| `h5json.py` | JSON <-> HDF5 of `data/<name>.h5` |
| `gltf.py` | glTF 2.0 binary writer and reader |
| `adh_doc.py` | The nested ADH document |
| `checks.py` | `aeroplan check` |
| `daveml_adh.py`, `daveml_eval.py`, `dml_validate.py` | DAVE-ML conversion, evaluator, DTD check |
| `spokes.py` | Spoke loader and the spoke `Context` |
| `build.py` | `aeroplan build`, placeholder list |
| `summary.py` | The one-page aircraft summary (`show --md`) |
| `datum.py` | Datum checks |
| `geometry.py`, `parts.py`, `visual.py` | ADH shapes <-> tool shapes and meshes |
| `step_mesh.py`, `skin_body.py` | Creo skin triangles, body frames, fit report |
| `aero_buildup.py` | The flow5 aero build-up and its DAVE-ML writer |
| `multirotor.py`, `multirotor_aero.py` | The multirotor seed and the body-drag DAVE-ML |
| `mass_model.py` | Point masses to mass, CG and inertia |

A spoke module defines `NAME`, `ingest(doc, ctx)`, and optionally `generate(doc, ctx)` and `export(doc, ctx, out)`.
