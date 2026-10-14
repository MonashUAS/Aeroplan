# AeroPlan

AeroPlan is the ADH-based single source of truth (SSOT) for aircraft data. Each aircraft is a source tree in git,
`aircraft/<aircraft>/`: one JSON file for each ADH node and each dataset. `aeroplan pack` makes a `.muas` package
from it: a ZIP archive that holds one immutable, hashed snapshot (format muas 2.0.0). Tool spokes at the repository
root move data between their tool and the source tree. Aerolink reads the `aerolink` package.

Read README.md first. It holds the layout, the user workflow, the rules and the open items.

## Architecture (user decisions)

- 2026-10-08: The SSOT lives inside AeroPlan (`aircraft/`). The muas-fleet-data repository is deleted and must not be
  used.
- 2026-10-10: Git holds the source tree (`aircraft/<aircraft>/`, committed). The `.muas` package is built from it into
  `dist/` (git ignores it) and is never edited in place. `aeroplan unpack` gives the source tree back.
- Only ADH data goes into the source tree: the ADH tree, the asset register, small geometry and lookup tables, the
  datasets. Large files (STL, STEP, `.fl5`, sweep output, logs) stay in `<spoke>/work/<aircraft>/` (git ignores it).
  The register names each one (`asset:sha256:<hash>`, repo path, URL).
- The asset register is `muas.assets` of 1.10.2 DataRepository. Every item names an asset by its ID, never by a path.
  Storage tiers inline, embedded, linked. Packing profiles `aerolink`, `review`, `flight-record`, `archive`
  (`consumers.py`). Flight events on 1.8.1.4 FlightTests, firmware on 1.2.9 AirVehicleSoftwareRelease.
- Aerolink packaging uses glTF (`preview/aircraft.glb`) for the 3D parts. No STL output (2026-10-10).
- One folder for each tool: `AeroSandbox/` (initial sizing), `flow5/`, `Propalyser/`, `CREO/` (CAD link), `OpenVSP/`,
  `DAVEML/` (published DAVE-ML models), `ArduPilot/` (flight events), `Aerolink/`. A new tool gets a new folder
  with `spoke.py`, `README.md`, `settings/`, `work/`.
- A new aircraft starts from the AeroSandbox sizing output, then moves forward to flow5. A published reference
  model (the NASA F-16, `aircraft/f16/`) starts from the DAVEML spoke.
- Manual changes come in through a spoke, by script only. Nobody edits the source tree by hand.
- 2026-10-14: AeroSandbox runs in its own Python (`AeroSandbox/.venv`, made by `aeroplan setup AeroSandbox` with uv).
  The spoke sends jobs to `AeroSandbox/asb_worker.py`, which imports aerosandbox and proptimiser (CasADi path, no JAX).
  Only that worker file imports them. Tests that need it skip without it.
- The web editor and viewer are shelved for now.
- The changed file wins (2026-10-08): a geometry spoke writes an item only when its input file differs from the
  asset that the item names. `muas.geometry_tool` names the spoke that wrote the geometry last.
- OpenVSP runs in its own Python (`OpenVSP/.venv`, made by `aeroplan setup OpenVSP` with uv). The spoke sends jobs
  to `OpenVSP/vsp_worker.py`, which imports only openvsp and numpy. Tests that need it skip without it.

## Rules

- ADH decides the design. Add a MUAS extension only where ADH is silent or broken, under the `muas` key, with
  `extra="forbid"`. A part with no WBS number of its own is a `subcomponent` of its ADH node. Never invent a WBS number.
- `packages/muas_adh/upstream/` stays pristine. Fixes go in `packages/muas_adh/patches/`. A patch must not break an
  upstream ADH test (CI runs them). `packages/muas_adh/upstream_commit.txt` names the upstream commit.
- Store SI. Angles are radians in the ADH data. Every quantity carries units. Exception: a published reference model
  (DAVE-ML) keeps its own units (`units_system: as-source`), because its check cases use them.
- MRP = the nominal-configuration CG (today the T7 CoG of the flow5 analysis), a fixed point in the design frame.
- Never type an unsourced number. A stand-in value carries `placeholder: true` and names its source.
- Copy data by hand between repos. No symlinks. No hard-coded cross-repo paths. AeroPlan imports no sibling repo.
  Aerolink has a hand copy of the package reader (src/aerolink/muas.py) and the glTF reader (visual/cad.py).
- DAVE-ML must pass the vendored 2.0 DTD (`spec/dave-ml/2p0`).
- Tests use synthetic numbers only. `tests/test_aircraft_files.py` runs every check, the pack and the unpack on each
  committed source tree.
- Write prose in ASD-STE100 style.
- Commits and builds: author "Liam M.", git identity lmca0007.

## Code map

| Module | Job |
|---|---|
| `source_tree.py` | The source tree `aircraft/<aircraft>/` <-> the `Aircraft` in memory (ADH doc, datasets, info) |
| `assets.py` | The asset register: IDs (content hashes), file and dataset entries, references, fetch with hash check |
| `package.py` | `.muas` ZIP package: pack (profiles, deterministic bytes), open (every hash), unpack |
| `consumers.py` | Packing profiles, storage tiers, what Aerolink needs (`missing_for_flight`) |
| `h5json.py` | JSON <-> HDF5 of the data files `data/<name>.h5` (no time stamps) |
| `gltf.py` | glTF 2.0 binary writer and reader of the part view |
| `adh_doc.py` | The nested ADH document: WBS tree from upstream, node access, validation, normalisation |
| `checks.py` | `aeroplan check`: ADH, datasets, DAVE-ML (DTD, round trip, checkData), datums, consumers |
| `daveml_adh.py` | DAVE-ML XML <-> ADH `DAVEfunc` form, `compare` (lossless round trip) |
| `daveml_eval.py` | DAVE-ML evaluator (MathML, n-D tables) and the checkData runner |
| `spokes.py` | Spoke loader and the spoke `Context` (work folder, settings, `source_ref`, `add_dataset`) |
| `build.py` | `aeroplan build`, placeholder list |
| `datum.py` | Datum checks (planforms, reference, CAD meshes when present, stale assets) |
| `geometry.py`, `parts.py`, `visual.py` | ADH shapes <-> tool shapes and meshes |
| `step_mesh.py` | Triangles of a faceted STEP file (the Creo shrinkwrap skin), no CAD kernel |
| `aero_buildup.py` | The flow5 aero build-up and its DAVE-ML writer |

## Commands

```
pip install -e .[test]
python -m pytest
python -m aeroplan build currawong --author "Liam M."
python -m aeroplan check currawong
python -m aeroplan show currawong
python -m aeroplan pack currawong --profile aerolink review archive
python -m aeroplan unpack dist/currawong-<version>-archive.muas <folder>
python -m aeroplan verify dist/currawong-<version>-aerolink.muas
python -m aeroplan generate flow5 currawong
python -m aeroplan setup OpenVSP             # once per computer
python -m aeroplan generate OpenVSP currawong
python -m aeroplan export Aerolink currawong <out>
python -m aeroplan build f16 --author "Liam M."   # the NASA F-16 (DAVEML spoke, downloads when needed)
python -m aeroplan schema --out schema      # after a model change
```

The Currawong source tree came from the retired HDF5 file `aircraft/currawong.muas` (muas-adh 1.0.0) on 2026-10-10,
by a one-time script that is not kept.
