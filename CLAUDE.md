# AeroPlan

AeroPlan is the ADH-based single source of truth (SSOT) for aircraft data. Each aircraft is a source tree in git,
`aircraft/<aircraft>/`: one JSON file for each ADH node and each dataset. Tool spokes in `aeroplan/<tool>/` move data between
their tool and the source tree. `aeroplan pack` makes a `.muas` package (a ZIP archive) from a tree. Aerolink reads it.

The rules live in the ADRs (`docs/decisions/`), one rule for each line of a `## Rules` section. Checks enforce most of them.
This file holds only what you need to find the rules, and the rules that no check can see.

## Before you write code

1. Find the module for the job in the code map below (`python -m aeroplan codemap`). Extend it. Do not write a second copy.
2. Read the rules for each file you change: `python -m aeroplan rules <path>`. The agent hook shows them before an edit.
3. Read the facts that live in ADH fields only through their helpers: `adh_doc.FACTS` names them.
4. A new tool: `python -m aeroplan new-spoke <Name>`, then add the name to `spokes.SPOKES`.

## After you write code

```
ruff check .
python -m pytest tests/architecture      # the rules: each failure names its rule (APnnn) and its ADR
python -m pytest
```

Fix the code when a rule fails. Add an entry to `tests/architecture/allowlist.py` only when the user agrees.

## Rules that no check can see

- ADH decides the design. A fact that ADH has a field for goes in that field, and only there (ADR 0027).
- Ask the user before you add a `muas` key. Then add its row to `standards/adh/EXTENSIONS.md`.
- Never invent a WBS number. A part with no WBS number of its own is a `subcomponent` of its ADH node.
- Never type an unsourced number. A stand-in value has `placeholder: true` and names its source (ADR 0032).
- Nobody edits `aircraft/` by hand. Only spokes and code write it (ADR 0008).
- Never edit `standards/adh/upstream/`. A fix is a patch in `standards/adh/patches/` (ADR 0034).
- Write prose in ASD-STE100 style.
- Move tracked files with `git mv`. Never `git add -A`. Do not commit unless the user asks.

## Install and commands

`docs/tutorials/first-day.md` gives the install. `python -m aeroplan --help` gives every command. The common ones:

```
python -m aeroplan doctor                    # what is missing on this computer, with the fix for each item
python -m aeroplan check currawong
python -m aeroplan build currawong           # author: git config user.name
python -m aeroplan pack currawong --profile aerolink review archive
python -m aeroplan show currawong --md docs/reference/aircraft/currawong.md
python -m aeroplan schema --out standards/schema   # after a model change, with a new MUAS_SCHEMA_VERSION
python -m aeroplan rules --index --write     # after a change of an ADR front matter
python -m aeroplan codemap --write           # after a new module or a changed module docstring
python -m aeroplan setup OpenVSP             # once per computer: OpenVSP has its own Python (ADR 0011)
```

## Code map

Made from the first line of each module docstring. Do not edit it by hand: run `python -m aeroplan codemap --write`.

<!-- codemap:start -->
| Module | Job |
|---|---|
| `__init__.py` | AeroPlan: the ADH-based single source of truth for aircraft data (the .muas file). |
| `__main__.py` | `python -m aeroplan`: the command line (cli.py). |
| `adh_doc.py` | The nested ADH document: one `AircraftSystem` tree, as upstream ADH defines it. |
| `aero_buildup.py` | The aero build-up of contract C (`dml/aero.dml`): coefficients from flow5, written as DAVE-ML 2.0. |
| `aerolink/spoke.py` | Aerolink spoke: the `.muas` package that Aerolink flies. |
| `aerosandbox/component.py` | Components of an aircraft model, and the functions that give a component at a chosen fidelity level. |
| `aerosandbox/mission.py` | The mission of a quadplane: the flight conditions the model evaluates, and the segments that add up to the energy. |
| `aerosandbox/model.py` | Aircraft models. One class for each class of aircraft. A model holds components (component.py) and evaluates one flight |
| `aerosandbox/optimise.py` | The solver driver. It turns a model (model.py) into one `asb.Opti` problem, solves it, and gives a `Result` (result.py). |
| `aerosandbox/plot.py` | Plots of a model, a `Result` or a `Snapshot`. Nothing here calls the solver: the plotter only reads numbers. |
| `aerosandbox/result.py` | The result of a solve, and a snapshot of one iterate. |
| `aerosandbox/spoke.py` | AeroSandbox spoke: the initial sizing -> ADH performance record of the air vehicle, the ADH aircraft -> an AeroSandbox model |
| `aerosandbox/window.py` | The window: change a few params of a model, see the design and the limits change, and optimise the free ones in front of you. |
| `ardupilot/spoke.py` | ArduPilot spoke: flight events and flight files of the autopilot. |
| `assets.py` | The asset register (1.10.2 DataRepository `muas.assets`) and the datasets it names. |
| `build.py` | `aeroplan build <aircraft>`: run the spokes, check the ADH document, write the source tree `aircraft/<aircraft>/`. |
| `checks.py` | `aeroplan check <aircraft>`: every check of the source tree of one aircraft. |
| `cli.py` | aeroplan command line. |
| `codemap.py` | The code map: one row for each module of the package, made from the first line of its docstring (rule AP015). |
| `constants.py` | Physical constants and unit factors, written once (rule AP011). Import them from here: never type the number again. |
| `consumers.py` | Packing profiles and what each consumer of a `.muas` package needs. |
| `creo/spoke.py` | CREO spoke: the CAD part exports -> `muas.visual` of their ADH items (pointer, pose and hinge of each mesh). |
| `datum.py` | Datum checks of the ADH document: every geometry source must agree in the one design frame. |
| `daveml/spoke.py` | DAVEML spoke: published DAVE-ML 2.0 models (for example the NASA F-16 check-case model) -> datasets of the ADH items. |
| `daveml_adh.py` | DAVE-ML 2.0 (ANSI/AIAA S-119) XML <-> the ADH `DAVEfunc` form (upstream behavior.py). |
| `daveml_eval.py` | Evaluate a DAVE-ML model in its ADH `DAVEfunc` form, and run its checkData static shots. |
| `dml_validate.py` | Validate DAVE-ML bytes against the vendored DAVE-ML 2.0 DTD (spec/dave-ml/2p0). |
| `doctor.py` | `aeroplan doctor`: what this computer has and lacks for AeroPlan, with one fix line for each missing item. |
| `flightfiles.py` | The flight files of an aircraft: ArduPilot parameters, the waypoint plan and the geofence. |
| `flow5/buildup.py` | The flow5 sources of the aero build-up (aeroplan.aero_buildup): the T7 stability point, the viscous polar and the |
| `flow5/files.py` | Flow5 geometry and stability files: the plane XML, the foil .dat files and a T7 operating point. |
| `flow5/plane_xml.py` | flow5 plane XML: read the body frames and point masses, and write a plane XML from the ADH document. |
| `flow5/polar.py` | flow5 polar reader: one flow5 7.57 polar text file (`*.csv`, fixed-width text, no commas). |
| `flow5/spoke.py` | flow5 spoke: the flow5 sweep -> ADH geometry, reference, mass model, aero model and trim. The ADH document -> a |
| `flow5/sweep.py` | flow5 sweep runner: write the flow5 script and the polar XML files, run flow5 headless in two passes, check the runs |
| `frame.py` | The design frame: FRD (x forward, y right, z down, metres) with its origin at the wing root leading edge (ADR 0029). |
| `geometry.py` | Shape helpers between the ADH geometry classes and the tool shapes (flow5 wings and bodies, meshes). |
| `gltf.py` | glTF 2.0 binary (GLB): the 3D view of the aircraft in a `.muas` package (`preview/aircraft.glb`). |
| `h5json.py` | JSON <-> HDF5: the data files of a `.muas` package (`data/<name>.h5`). |
| `mass_model.py` | The mass model: point masses -> mass, CG and inertia. Design frame (FRD: x forward, y right, z down), SI. |
| `muas/aircraft.py` | MUAS extension types of the aircraft ADH document. |
| `muas/assets.py` | The asset register: one entry for each large file or dataset, under the `muas` key of 1.10.2 DataRepository. |
| `muas/base.py` | Base model for all MUAS extension types (brief D03: extra="forbid"). |
| `muas/control_surface.py` | Control-surface extension (brief D13). A control surface is a subcomponent of the surface that carries it |
| `muas/control_system.py` | Control-system extensions (user answers 3 and 4, 2026-10-08). Group for a later control-systems analysis. |
| `muas/dataset.py` | Dataset metadata: what every dataset in the asset register carries (source tool, version, fidelity, role, sigma, |
| `muas/flight.py` | Flight events (1.8.1.4 FlightTests) and firmware releases (1.2.9 AirVehicleSoftwareRelease). |
| `muas/ground.py` | Ground contacts (user answer 3, 2026-10-08). Group for a later structural and landing-loads analysis. |
| `muas/ic.py` | Initial-condition spec (brief D17). Rate frame, latitude type and attitude sequence are mandatory. |
| `muas/mass.py` | Mass properties (brief D11). |
| `muas/mission.py` | Missions as ADH requirements (user decision 2026-10-08: "standardise missions inside the ADH"). |
| `muas/node.py` | MUAS extension of an ADH node (rule D03). |
| `muas/propulsion.py` | Electric propulsion extension (brief D12; user answers 3, 4). |
| `muas/provenance.py` | Provenance (brief D09). Hash fields live here. ADH ModelDescription and DAVE-ML Provenance stay as upstream. |
| `muas/reference.py` | Reference data: frames, MRP and signs (brief D05; user answer 7). The reference values (S, b, c) are ADH data: the |
| `muas/requirement.py` | MUAS extensions of an ADH `Requirement` (user answer 5, 2026-10-08: handling targets and analysis speeds are |
| `muas/uncertainty.py` | Uncertainty schema. |
| `muas/units.py` | Quantities with explicit units, normalised to SI at load (brief D04). |
| `multirotor.py` | The multirotor seed: the ADH items of a quadcopter from the numbers of a settings file. |
| `multirotor_aero.py` | The aero model of a multirotor: the body drag, written as DAVE-ML 2.0 (forces only, no moments). |
| `openvsp/runner.py` | Run OpenVSP jobs in the OpenVSP Python, and make that Python (`aeroplan setup OpenVSP`). |
| `openvsp/spoke.py` | OpenVSP spoke: the ADH geometry -> an OpenVSP model (.vsp3), and a changed OpenVSP model -> the ADH geometry. |
| `openvsp/vsp_worker.py` | OpenVSP worker: runs in the OpenVSP Python (aeroplan/openvsp/.venv, made by `aeroplan setup OpenVSP`), not in AeroPlan. |
| `package.py` | The `.muas` package: a ZIP archive that holds one immutable, hashed snapshot of an aircraft or a flight record. |
| `parts.py` | Part meshes of the aircraft in the design frame, made from the `muas.visual` entries of the ADH document. |
| `propalyser/spoke.py` | Propalyser spoke: a contract B file (`propulsion-system` schema version 2) -> the propulsion system of the |
| `propulsion_sizing.py` | First sizing of a quadplane propulsion system from the maximum take-off mass (MTOW). Pure functions, SI units. |
| `rules.py` | The rules of the repository, read from the ADRs in docs/decisions/ (ADR 0031): front matter, `## Rules`, the index. |
| `schema_export.py` | Export one JSON Schema file per MUAS type, committed per version (brief D15). |
| `skin_body.py` | Flow5-style body frames from a closed outer skin mesh (the Creo shrinkwrap of the fuselage). |
| `source_tree.py` | The source tree of an aircraft: `aircraft/<name>/`, committed to git. It is the single source of truth. |
| `specsheet/spoke.py` | SpecSheet spoke: the Master Specification Sheet (weight log and CG sheet) -> the ADH mass model. |
| `spokes.py` | Spokes: one subpackage for each tool, `aeroplan/<tool>/`. A spoke moves data between its tool and the source tree |
| `step_mesh.py` | Triangles of a faceted STEP file (for example a Creo shrinkwrap), with no CAD kernel. |
| `summary.py` | One-page summary of an aircraft as Markdown (`aeroplan show <aircraft> --md <out>`). |
| `visual.py` | Visual parts: CAD meshes in the design frame, for the glTF view of a `.muas` package (aeroplan.gltf). |
| `wing.py` | A lifting surface in the section form of the tools (flow5, OpenVSP, AeroSandbox): the right half, root first. |
<!-- codemap:end -->
