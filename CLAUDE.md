# AeroPlan

AeroPlan is the ADH-based single source of truth (SSOT) for aircraft data. Each aircraft is a source tree in git,
`aircraft/<aircraft>/`: one JSON file for each ADH node and each dataset. `aeroplan pack` makes a `.muas` package
from it: a ZIP archive that holds one immutable, hashed snapshot (format muas 2.0.0). Tool spokes in `tools/` move data
between their tool and the source tree. Aerolink reads the `aerolink` package.

Read README.md first, then `docs/README.md`. The decisions are in `docs/decisions/` (one Nygard ADR for each decision,
numbered, with date). Read the ADR before you change a thing that it covers.

## Layout (ADR 0020)

```
aircraft/   source trees        tools/    one spoke for each tool (lower case)     standards/  adh/ schema/ spec/
src/aeroplan/  core code        docs/     tutorials howto reference explanation decisions
tests/      synthetic tests     work/     raw tool files, work/<tool>/<aircraft>/ (git ignores it)     dist/  packages
```

A new tool gets a new folder `tools/<tool>/` with `spoke.py`, `README.md` and `settings/`. The ArduPilot spoke holds the
flight events and the flight files (ADR 0021). The Aerolink note `docs/multirotor_contract.md` copies
`docs/reference/multirotor_contract.md`.

## Rules

- ADH decides the design. Add a MUAS extension only where ADH is silent or broken, under the `muas` key, with
  `extra="forbid"`. A part with no WBS number of its own is a `subcomponent` of its ADH node. Never invent a WBS number.
- `standards/adh/upstream/` stays pristine. Fixes go in `standards/adh/patches/`. A patch must not break an
  upstream ADH test (CI runs them). `standards/adh/upstream_commit.txt` names the upstream commit.
- Store SI. Angles are radians in the ADH data. Every quantity carries units. Exception: a published reference model
  (DAVE-ML) keeps its own units (`units_system: as-source`), because its check cases use them.
- MRP = the nominal-configuration CG (today the T7 CoG of the flow5 analysis), a fixed point in the design frame.
- Never type an unsourced number. A stand-in value carries `placeholder: true` and names its source.
- Only ADH data goes into the source tree. Nobody edits the source tree by hand: only spokes (and code) write it.
- Copy data by hand between repos. No symlinks. No hard-coded cross-repo paths. AeroPlan imports no sibling repo.
  Aerolink has a hand copy of the package reader (src/aerolink/muas.py) and the glTF reader (visual/cad.py).
- DAVE-ML must pass the vendored 2.0 DTD (`standards/spec/dave-ml/2p0`).
- Tests use synthetic numbers only. `tests/test_aircraft_files.py` runs every check, the pack and the unpack on each
  committed source tree.
- Write prose in ASD-STE100 style.
- Move tracked files with `git mv`. Never `git add -A`. Do not commit unless the user asks.
- Commits and builds: author "Liam M.", git identity lmca0007.

## Code map

| Module | Job |
|---|---|
| `source_tree.py` | The source tree `aircraft/<aircraft>/` <-> the `Aircraft` in memory (ADH doc, datasets, info) |
| `assets.py` | The asset register: IDs (content hashes), file and dataset entries, references, fetch with hash check |
| `flightfiles.py` | The flight files: parse and write `.parm`, QGC WPL `.waypoints`, fence polygons, and the fence parameter check |
| `package.py` | `.muas` ZIP package: pack (profiles, deterministic bytes), open (every hash), unpack |
| `consumers.py` | Packing profiles, storage tiers, what Aerolink needs (`missing_for_flight`) |
| `h5json.py` | JSON <-> HDF5 of the data files `data/<name>.h5` (no time stamps) |
| `gltf.py` | glTF 2.0 binary writer and reader of the part view |
| `adh_doc.py` | The nested ADH document: WBS tree from upstream, node access, validation, normalisation |
| `checks.py` | `aeroplan check`: ADH, datasets, DAVE-ML (DTD, round trip, checkData), datums, consumers |
| `daveml_adh.py` | DAVE-ML XML <-> ADH `DAVEfunc` form, `compare` (lossless round trip) |
| `daveml_eval.py` | DAVE-ML evaluator (MathML, n-D tables) and the checkData runner |
| `spokes.py` | Spoke loader and the spoke `Context` (work folder `work/<tool>/<aircraft>/`, settings, `source_ref`, `add_dataset`) |
| `build.py` | `aeroplan build`, placeholder list |
| `summary.py` | One-page Markdown summary of an aircraft (`aeroplan show <aircraft> --md <file>`) |
| `datum.py` | Datum checks (planforms, reference, CAD meshes when present, stale assets) |
| `geometry.py`, `parts.py`, `visual.py` | ADH shapes <-> tool shapes and meshes |
| `step_mesh.py` | Triangles of a faceted STEP file (the Creo shrinkwrap skin), no CAD kernel |
| `aero_buildup.py` | The flow5 aero build-up and its DAVE-ML writer |
| `skin_body.py` | Body frames from a closed skin mesh (slices, wing panel cut, fit report), mesh repair for VSPAERO |
| `multirotor.py` | The multirotor seed: hubs from a CAD arm, rotors, motor outputs, reference, gear, demo shapes |
| `multirotor_aero.py` | The multirotor body-drag DAVE-ML (forces only) |
| `mass_model.py` | Point masses to mass, CG and inertia (parallel axis). Strip distribution of a mass over a planform |

AeroSandbox model files outside the package (ADR 0024, they run in the AeroSandbox Python): `tools/aerosandbox/component.py` (components,
level functions), `model.py` (`QuadplaneModel`, `FixedWingModel`, `MultirotorModel`, the spoke jobs), `mission.py`, `optimise.py`
(solver driver, fidelity ladder), `result.py`, `plot.py` and `window.py`. One model file for each aircraft:
`tools/aerosandbox/settings/<aircraft>.json`. The Rosella sizing is `tools/aerosandbox/notebooks/rosella_sizing.ipynb`, committed with
its outputs. `tools/aerosandbox/data/motor_survey.csv` is the sourced motor table for the mass fits.

## Commands

The full list is in `docs/reference/commands.md`. The common ones:

```
pip install -e .[test]
python -m pytest
python -m aeroplan check currawong
python -m aeroplan show currawong --md docs/reference/aircraft/currawong.md
python -m aeroplan build currawong --author "Liam M."
python -m aeroplan pack currawong --profile aerolink review archive
python -m aeroplan setup OpenVSP         # once per computer
python -m aeroplan setup AeroSandbox     # once per computer
python -m aeroplan schema --out standards/schema   # after a model change
```
