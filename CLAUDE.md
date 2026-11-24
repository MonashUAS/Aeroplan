# AeroPlan

AeroPlan is the ADH-based single source of truth (SSOT) for aircraft data. Each aircraft is a source tree in git,
`aircraft/<aircraft>/`: one JSON file for each ADH node and each dataset. `aeroplan pack` makes a `.muas` package
from it: a ZIP archive that holds one immutable, hashed snapshot (format muas 2.0.0). Tool spokes in `aeroplan/<tool>/`
move data between their tool and the source tree. Aerolink reads the `aerolink` package.

Read README.md first, then `docs/README.md`. The decisions are in `docs/decisions/` (one Nygard ADR for each decision,
numbered, with date). Read the ADR before you change a thing that it covers.

## Layout (ADR 0025, ADR 0026)

```
aircraft/<aircraft>/   source trees: <wbs>.<key>.json for each node, datasets/<name>.json
aeroplan/              core code (*.py, muas/) and one subpackage for each tool: aeroplan/<tool>/
standards/             adh/ (upstream, patches, EXTENSIONS.md)  schema/  spec/
docs/                  tutorials howto reference explanation decisions
tests/                 synthetic tests
work/<tool>/<aircraft>/   raw tool files (git ignores work/)        dist/   packages (git ignores it)
```

- A new tool gets a subpackage `aeroplan/<tool>/` with `__init__.py`, `spoke.py`, `README.md` and `settings/`, and a name in
  `spokes.SPOKES`. The spoke loader imports `aeroplan.<tool>.spoke`.
- The core (`aeroplan/*.py`, `aeroplan/muas/`) never imports a tool package. A tool-neutral form goes in the core (for example
  `aeroplan/wing.py`). A test checks it.
- A tool Python lives in `aeroplan/<tool>/.venv` (AeroSandbox, OpenVSP). After a folder move, run `aeroplan setup <tool>`.
- The root node file `1.0.aircraft_system.json` holds `muas.package` (kind, consumers). The reader moves it to
  `Aircraft.info`. There is no `aircraft.yaml`.
- The ArduPilot spoke holds the flight events and the flight files (ADR 0021). The multirotor contract is the Aerolink
  note `docs/multirotor_contract.md`. AeroPlan keeps no copy.
- The repository root is `aeroplan.REPO_ROOT` (`spokes.repo_root()` checks it). Never compute it from `parents[n]`.

## ADH rules (ADR 0027)

- ADH decides the design. Store each fact once: when ADH has the field, the value goes there, and only there.
- Add a MUAS extension only where ADH is silent or broken, under the `muas` key, with `extra="forbid"`. Before you add a
  key, read `standards/adh/EXTENSIONS.md` and add its row (what ADH has, why MUAS adds it). A test stops the build when a
  key has no row.
- A part with no WBS number of its own is a `subcomponent` of its ADH node. Never invent a WBS number.
- Read and write the facts that live in ADH fields through the helpers:

  | Fact | ADH field | Read | Write |
  |---|---|---|---|
  | S, b, c | node 1.2 `parameters.reference_data` (`Sref`, `BLref`, `Cbar`) | `adh_doc.reference` | `adh_doc.set_reference` |
  | Control surface span and hinge | `parameters.asymmetric_control` or `symmetric_flap` | `adh_doc.control_surface` | `adh_doc.set_control_geometry` |
  | Lifting surface shape | `geometry.lifting_surface` | `geometry.planform_of` | `geometry.set_planform` |

- ADH parameter classes read only their aliases (`Sref`, not `reference_area`). A field name passes the ADH validation as an
  unknown extra key, and the value is lost.
- Use the ADH class when it fits (`behavior.UncertaintyEffect` checks `effect`). Do not copy an ADH class into `muas`. Import
  upstream ADH inside a function, not at module level, so the MUAS models load without it.
- `standards/adh/upstream/` stays pristine. Fixes go in `standards/adh/patches/`. A patch must not break an upstream ADH test
  (CI runs them). `standards/adh/upstream_commit.txt` names the upstream commit. `standards/README.md` lists the patches and
  the known faults of upstream.
- After a change of a MUAS model, raise `MUAS_SCHEMA_VERSION` and run `aeroplan schema --out standards/schema`.

## Data rules

- Store SI. Angles are radians in the ADH data. No field holds degrees. Every quantity carries units: a `{value, units}`
  quantity, a field name with a unit suffix (`_m`, `_s`, `_rad`, `_mps`), or an ADH float whose patched description names the
  SI unit. Exception: a published reference model (DAVE-ML) keeps its own units (`units_system: as-source`), because its
  check cases use them.
- The design frame is FRD: x forward, y right, z down, metres (ADR 0029). A spoke flips at the edge of its tool with
  `aeroplan/frame.py`. The source tree holds FRD only.
- MRP = the nominal-configuration CG (today the T7 CoG of the flow5 analysis), a fixed point in the design frame.
- Never type an unsourced number. A stand-in value carries `placeholder: true` and names its source.
- Only ADH data goes into the source tree. Nobody edits the source tree by hand: only spokes (and code) write it. A one-time
  migration is a script that reads and writes the tree through `source_tree`. Do not keep it.
- Copy data by hand between repos. No symlinks. No hard-coded cross-repo paths. AeroPlan imports no sibling repo.
  Aerolink has a hand copy of the package reader (src/aerolink/muas.py) and the glTF reader (visual/cad.py).
- DAVE-ML must pass the vendored 2.0 DTD (`standards/spec/dave-ml/2p0`).

## Work rules

- Tests use synthetic numbers only. `tests/test_aircraft_files.py` runs every check, the pack and the unpack on each
  committed source tree.
- `ruff check .` must pass (CI runs it, the rules are in `pyproject.toml`).
- Write prose in ASD-STE100 style.
- Move tracked files with `git mv`. Never `git add -A`. Do not commit unless the user asks.
- Commits and builds: author "Liam M.", git identity lmca0007.

## Code map

Core (`aeroplan/`):

| Module | Job |
|---|---|
| `source_tree.py` | The source tree `aircraft/<aircraft>/` <-> the `Aircraft` in memory (ADH doc, datasets, info) |
| `assets.py` | The asset register: IDs (content hashes), file and dataset entries, references, fetch with hash check |
| `flightfiles.py` | The flight files: parse and write `.parm`, QGC WPL `.waypoints`, fence polygons, and the fence parameter check |
| `package.py` | `.muas` ZIP package: pack (profiles, deterministic bytes), open (every hash), unpack |
| `consumers.py` | Packing profiles, storage tiers, what Aerolink needs (`missing_for_flight`) |
| `h5json.py` | JSON <-> HDF5 of the data files `data/<name>.h5` (no time stamps) |
| `gltf.py` | glTF 2.0 binary writer and reader of the part view |
| `adh_doc.py` | The nested ADH document: WBS tree from upstream, node access, validation, normalisation, the reference and control-surface helpers |
| `checks.py` | `aeroplan check`: ADH, datasets, DAVE-ML (DTD, round trip, checkData), datums, consumers |
| `daveml_adh.py` | DAVE-ML XML <-> ADH `DAVEfunc` form, `compare` (lossless round trip) |
| `daveml_eval.py` | DAVE-ML evaluator (MathML, n-D tables) and the checkData runner |
| `spokes.py` | Spoke loader and the spoke `Context` (work folder `work/<tool>/<aircraft>/`, settings, `source_ref`, `add_dataset`) |
| `build.py` | `aeroplan build`, placeholder list |
| `summary.py` | One-page Markdown summary of an aircraft (`aeroplan show <aircraft> --md <file>`) |
| `datum.py` | Datum checks (planforms, reference, CAD meshes when present, stale assets) |
| `frame.py` | The FRD design frame: the flip between x aft, z up (the tools) and FRD (ADR 0029) |
| `wing.py` | The tool-neutral wing form (`Section`, `Wing`: flow5 convention, in memory only) |
| `geometry.py` | ADH shapes <-> tool shapes: `planform_of`, `set_planform`, `lifting_surface_adh`, bodies |
| `parts.py`, `visual.py` | Part meshes and the view (lifting surfaces, bodies, demo shapes) |
| `step_mesh.py` | Triangles of a faceted STEP file (the Creo shrinkwrap skin), no CAD kernel |
| `aero_buildup.py` | The aero build-up model and its DAVE-ML writer (the flow5 sources are in `flow5/buildup.py`) |
| `skin_body.py` | Body frames from a closed skin mesh (slices, wing panel cut, fit report), mesh repair for VSPAERO |
| `multirotor.py` | The multirotor seed: hubs from a CAD arm, rotors, motor outputs, reference, gear, demo shapes |
| `multirotor_aero.py` | The multirotor body-drag DAVE-ML (forces only) |
| `mass_model.py` | Point masses to mass, CG and inertia (parallel axis). Strip distribution of a mass over a planform |
| `muas/` | The MUAS extension models (one row each in `standards/adh/EXTENSIONS.md`) |

Tools (`aeroplan/<tool>/`, each with `spoke.py`, `README.md`, `settings/`): `aerosandbox`, `flow5` (`files.py` and `polar.py`
read the flow5 files, `buildup.py`, `sweep.py`, `plane_xml.py`), `specsheet` (`sheets/`), `propalyser`, `creo`, `openvsp`
(`runner.py`, `vsp_worker.py`), `daveml`, `ardupilot`, `aerolink`.

AeroSandbox model files (ADR 0024, ADR 0028, they run in the AeroSandbox Python as `aeroplan.aerosandbox.*`):
`component.py` (components, level functions, `base_document`: the only read of the source tree), `model.py`
(`QuadplaneModel`, `FixedWingModel`, `MultirotorModel`, the spoke jobs), `mission.py`, `optimise.py` (solver driver,
fidelity ladder), `result.py`, `plot.py` and `window.py`. One model file for each aircraft:
`aeroplan/aerosandbox/settings/<aircraft>.json`. The Rosella sizing is `aeroplan/aerosandbox/notebooks/rosella_sizing.ipynb`,
committed with its outputs. `aeroplan/aerosandbox/data/motor_survey.csv` and `esc_survey.csv` are the sourced maker tables for the mass fits
(`data/vendor_survey_SOURCE.md` gives the rules). The quadplane model is described in `docs/reports/quadplane_model/`.

## Commands

`python -m aeroplan --help` gives the full list. The common ones:

```
pip install -e .[test]
python -m pytest
ruff check .
python -m aeroplan check currawong
python -m aeroplan show currawong --md docs/reference/aircraft/currawong.md
python -m aeroplan build currawong --author "Liam M."
python -m aeroplan pack currawong --profile aerolink review archive
python -m aeroplan setup OpenVSP         # once per computer, and after a folder move
python -m aeroplan setup AeroSandbox     # once per computer, and after a folder move
python -m aeroplan schema --out standards/schema   # after a model change
python standards/adh/build_adh.py        # after a change of standards/adh/patches/
```
