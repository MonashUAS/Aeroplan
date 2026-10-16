# Folders

| Folder | What it holds |
|---|---|
| `aircraft/<aircraft>/` | The source tree of each aircraft (the SSOT): `aircraft.yaml`, `adh/`, `datasets/` |
| `tools/<tool>/` | One spoke for each tool: `spoke.py`, `README.md`, `settings/<aircraft>.yaml` |
| `standards/adh/` | Upstream ADH (pristine, `upstream/`), its commit (`upstream_commit.txt`), the MUAS patch series (`patches/`), `build_adh.py` |
| `standards/schema/` | JSON Schema of the MUAS extension types, one folder for each version |
| `standards/spec/` | The vendored DAVE-ML 2.0 DTD and MathML 2.0 DTD |
| `src/aeroplan/` | The core code |
| `docs/` | These documents |
| `tests/` | The tests. They use synthetic numbers only |
| `work/<tool>/<aircraft>/` | Raw tool files of your machine (git ignores `work/`) |
| `dist/` | Packages that `aeroplan pack` writes (git ignores it) |

Spokes in `tools/`:

| Spoke | Job |
|---|---|
| `prototype` | Published specs of the team (MTOW) to sizing targets, and the first propulsion sizing |
| `aerosandbox` | Initial sizing, and the AeroSandbox model with the propulsion chain (`aeroplan setup AeroSandbox` first) |
| `flow5` | Geometry, reference dimensions and aero model from a flow5 sweep |
| `specsheet` | The Master Specification Sheet (weight log and CG sheet) to the mass model. Runs after flow5, so it owns the mass. The sheets are in `sheets/<aircraft>/` |
| `propalyser` | The propulsion system (contract B file of Propalyser) |
| `creo` | The CAD link (part meshes, their pose and hinge lines, the fuselage skin) |
| `openvsp` | The ADH geometry to an OpenVSP model and back (`aeroplan setup OpenVSP` first) |
| `daveml` | Published DAVE-ML models (the NASA F-16 of the NESC check cases) |
| `ardupilot` | Flight events (log, parameters, firmware, segments) and flight files (`.parm`, `.waypoints`, geofence) |
| `aerolink` | The simulator export (the `aerolink` package) |

The spokes run in this order (`spokes.SPOKES`): prototype, aerosandbox, flow5, specsheet, propalyser, creo, openvsp, daveml, ardupilot, aerolink.

Rules:

- Only ADH data goes into the source tree. A tool file (STL, STEP, `.fl5`, sweep output, logs) stays in `work/`. The register names it (path, URL and sha256).
- Do not edit the source tree by hand. Every change comes through a spoke, so each value names its source.
- A value with no measurement is marked `placeholder`.
- Upstream ADH stays untouched. A fix goes in `standards/adh/patches/`. A patch must not break an upstream test.
