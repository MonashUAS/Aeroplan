# AeroPlan

AeroPlan keeps each aircraft as a source tree in git: `aircraft/<aircraft>/`. This tree is the single source of truth
(SSOT). It holds one [Aircraft Data Hierarchy](https://github.com/Boeing/aircraft-data-hierarchy) (ADH) document,
one JSON file for each ADH node, and one JSON file for each dataset. `aeroplan pack` makes a `.muas` package from it:
a ZIP archive that holds one immutable, hashed snapshot of the aircraft.

Each tool has a **spoke**: a folder that moves data between the tool and the source tree. A tool member works in the
tool, then runs `aeroplan build`. AeroPlan reads the tool output, checks it and writes the source tree.

```
      AeroSandbox/  flow5/  SpecSheet/  Propalyser/  CREO/  OpenVSP/  DAVEML/  ArduPilot/
            |          |         |           |         |        |        |         |
            +----------+---------+-----+-----+---------+--------+--------+---------+
                                      |  aeroplan build
                                      v
                       aircraft/currawong/   (ADH source tree, committed)
                                      |  aeroplan pack --profile aerolink
                                      v
                dist/currawong-<version>-aerolink.muas  ->  Aerolink  ->  fly
```

## First day (about 15 minutes)

1. Install Python 3.10 or newer and git.
2. Clone the repository and install AeroPlan in editable mode (the spokes need the repository folders):
   ```
   git clone <AeroPlan repository URL>
   cd Aeroplan
   pip install -e .[test]
   ```
3. Check the aircraft: `python -m aeroplan check currawong`. The last line says "All checks pass."
4. Look at the ADH tree and the asset register: `python -m aeroplan show currawong`.
5. Run the tests: `python -m pytest`.

The first command builds the patched ADH package in `packages/muas_adh/build/` (git ignores it).

## Change the aircraft with your tool

Example: a member changes the wing in flow5.

1. Write the flow5 input from the SSOT: `python -m aeroplan generate flow5 currawong`. This writes
   `flow5/work/currawong/generated/currawong.xml` and the foil files.
2. Open the plane in flow5, change it, and run the sweep. Put the sweep folder in `flow5/work/currawong/sweeps/`.
3. Name the sweep in `flow5/settings/currawong.yaml` (`sweep:` and `sweep_date:`).
4. Build: `python -m aeroplan build currawong --author "Your Name"`. Read the datum table. A failed check writes
   nothing.
5. Commit `aircraft/currawong/` (and the settings file, if you changed it). Raw files stay in `work/`.

Each spoke folder has a README with its input files and settings. Example for OpenVSP: `OpenVSP/README.md`.

The changed file wins. A geometry spoke (flow5, OpenVSP) writes the geometry of an item only when its input file
differs from the file asset that the item names. After an OpenVSP change, the datum table warns that the aero model
comes from older geometry until you run a new flow5 sweep.

## Fly it in Aerolink

1. `python -m aeroplan export Aerolink currawong <out>` writes `<out>/currawong-<version>-aerolink.muas`.
2. Copy the file into `Aerolink/aircraft/` as `currawong.muas`.
3. In Aerolink: `aerolink inspect`, `aerolink check`, `aerolink fg build`, then fly.

The package holds the 3D view as glTF (`preview/aircraft.glb`). The parts come from the CAD files when they are on
your machine (`CREO/work/`). Without CAD files, they come from the ADH shapes (lifting surfaces, body, control
surfaces). They then look simpler, but they move the same.

## Folders

| Folder | What it holds |
|---|---|
| `aircraft/<aircraft>/` | The source tree of each aircraft (the SSOT): `aircraft.yaml`, `adh/`, `datasets/` |
| `AeroSandbox/` | Spoke: initial sizing (the first source of a new aircraft), and the AeroSandbox model with the propulsion chain (`aeroplan setup AeroSandbox` first) |
| `flow5/` | Spoke: geometry, mass model, reference dimensions and aero model from a flow5 sweep |
| `SpecSheet/` | Spoke: the Master Specification Sheet (weight log and CG sheet) to the mass model of the ADH. Runs after flow5, so it owns the mass |
| `Propalyser/` | Spoke: the propulsion system (contract B file of Propalyser) |
| `CREO/` | Spoke: the CAD link (part meshes, their pose and hinge lines, the fuselage skin) |
| `OpenVSP/` | Spoke: the ADH geometry to an OpenVSP model and back (`aeroplan setup OpenVSP` first) |
| `DAVEML/` | Spoke: published DAVE-ML models (the NASA F-16 of the NESC check cases) |
| `ArduPilot/` | Spoke: flight events (log, parameters, firmware, segments) and firmware releases |
| `Aerolink/` | Spoke: the simulator export (the `aerolink` package) |
| `src/aeroplan/` | The core: source tree, asset register, package, ADH document rules, checks, DAVE-ML |
| `packages/muas_adh/` | Upstream ADH (pristine), its commit (`upstream_commit.txt`) and the MUAS patch series |
| `schema/` | JSON Schema of the MUAS extension types, one folder for each version |
| `dist/` | Packages that `aeroplan pack` writes (git ignores it) |

## The source tree

```
aircraft/<aircraft>/
  aircraft.yaml                 name, kind (aircraft or flight-record), consumers (the profiles it serves)
  adh/<wbs>.<key>.json          one file for each ADH node, without its child nodes (subcomponents stay inside)
  datasets/<name>.json          one file for each dataset of the asset register
```

- A child node sits under the snake_case name of its upstream class (`air_vehicle`, `airframe`, `wing`).
- MUAS additions sit under the `muas` key of a node, typed with `extra="forbid"`.
- **The asset register** is `muas.assets` of node `1.10.2 DataRepository`. Each large file or dataset has one entry
  and one ID: `asset:sha256:<hash>`. Every other item names the ID, never a path. A file asset has the hash of its
  bytes. A dataset has the hash of its canonical JSON. A dataset is never edited: a change gives a new dataset.
- A derived asset records `derived_from` and `built_against`. An input that left the register makes the datum
  check warn that the asset is stale.
- Each dataset entry carries the source tool and version (ADH `ModelDescription`), the fidelity, the role, the
  sigma (ADH `Uncertainty`) and the moment reference point.

| Content | ADH node |
|---|---|
| Asset register | `1.10.2 DataRepository` |
| Flight events: configuration flown, as-flown mass and CG, firmware and parameters, segments | `1.8.1.4 FlightTests` |
| Firmware releases | `1.2.9 AirVehicleSoftwareRelease` |
| Geometry, mass, aero and propulsion data of a part | the node of the part |

## The `.muas` package (format muas 2.0.0)

```
<aircraft>-<version>-<profile>.muas     (ZIP64 when needed)
  mimetype                              "application/vnd.muas+zip", the first entry, not compressed
  manifest.json                         kind, format version, ADH fork, MUAS schema version, profile, consumers,
                                        the files {path, sha256, size, role, storage, asset}, the package hash
  aircraft.adh.json                     the monolithic ADH tree
  data/<name>.h5                        embedded datasets (not compressed in the ZIP, gzip by chunk inside HDF5)
  assets/<sha256>-<name>                embedded raw files (archive profile)
  preview/aircraft.glb                  the glTF view of the parts
```

| Profile | Embedded | Linked |
|---|---|---|
| `aerolink` | ADH JSON, aero and propulsion datasets, glTF | everything else |
| `review` | ADH JSON, glTF preview, summary plots | data and CAD |
| `flight-record` | flight-record, segment and parameter datasets | raw logs, video |
| `archive` | everything that can be fetched | nothing |

- A package is never edited. A pack with other content and the same name is refused: build a new version first.
- The same source tree gives the same package bytes.
- `aeroplan unpack` and `aeroplan verify` check the mimetype, every file hash, the package hash and every dataset
  hash. Every fetch of a linked asset checks its hash.
- A consumer states what it needs. `pack --profile aerolink` refuses an aircraft that lacks an item Aerolink needs.
  A linked asset that is missing on this machine does not make a package invalid.

## Rules

- Only ADH data goes into the source tree. A tool file (STL, STEP, `.fl5`, sweep output, logs) stays in
  `<spoke>/work/<aircraft>/` on your machine. Git ignores every `work/` folder. The register names it (path, URL and
  sha256).
- Do not edit the source tree by hand. Every change comes through a spoke, so each value names its source.
- A value with no measurement is marked `placeholder`. `python -m aeroplan show currawong --placeholders` lists them.
- ADH decides the layout. A part that has no WBS number of its own (left aileron, fin, elevator) is a
  `subcomponent` of its ADH node. No WBS number is invented.
- Upstream ADH stays untouched. A fix goes in `packages/muas_adh/patches/`. A patch must not break an upstream test.

## Commands

| Command | What it does |
|---|---|
| `aeroplan build <aircraft> --author NAME` | Runs the spokes with input, checks, writes `aircraft/<aircraft>/` |
| `aeroplan check <aircraft>` | Every check: ADH tree, dataset hashes, DAVE-ML (DTD, round trip, checkData), datums, consumers |
| `aeroplan show <aircraft>` | Prints the ADH tree and the asset register (`--placeholders`: the stand-in values) |
| `aeroplan pack <aircraft> --profile P` | Writes `dist/<aircraft>-<version>-<P>.muas` |
| `aeroplan unpack <file> <folder>` | Checks a package and writes its source tree |
| `aeroplan verify <file>` | Checks a package: mimetype, every hash, the package hash |
| `aeroplan generate <spoke> <aircraft>` | Writes the tool input files from the source tree (flow5, OpenVSP, AeroSandbox: the model, the jobs and `work/<aircraft>/asb/report.md`) |
| `aeroplan export <spoke> <aircraft> <out>` | Writes the tool files of a spoke (Aerolink: the `aerolink` package) |
| `aeroplan spokes <aircraft>` | Lists the spokes and the files in their work folders |
| `aeroplan setup OpenVSP` | Makes the OpenVSP Python on this machine (`--vsp <folder>` when it does not find OpenVSP) |
| `aeroplan setup AeroSandbox` | Makes the AeroSandbox Python on this machine (`--proptimiser <checkout>`, or the git source in the settings) |
| `aeroplan schema --out schema` | Exports the JSON Schema of the MUAS types |

## Open items

- The flow5 sweep runner is not in AeroPlan yet. A member runs the sweep in flow5 by hand.
- OpenVSP spoke: no VSPAERO runs yet. The fuselage is not fitted to the CAD skin (the body frames are up to 43 mm
  wider than the skin at the wing root, x = -0.08 to 0.35 m).
- Mass: the `SpecSheet` spoke writes the mass model from the Master Specification Sheet (weighed subassembly totals, x
  positions of the CG sheet). y and z are zero, because the sheet has none (stand-ins). The CREO spoke reads no mass
  report yet. The sheet is an xlsx in the repository. A link to the Google Sheet (download of
  `export?format=xlsx` into `SpecSheet/work/<aircraft>/`, the URL in the asset entry) is not done.
- The MRP is the CoG of the flow5 T7 analysis. The mass CG moved 22 mm forward of it. Run `aeroplan generate flow5
  currawong`, run a new flow5 sweep of that plane, copy the sweep and build again. Until then the datum check warns,
  `aerolink` is not a consumer of Currawong (put it back in `aircraft.yaml` with `--consumers aerolink review archive`),
  and Aerolink needs MRP = CG within 1 mm.
- flow5 and AeroSandbox disagree on the lift slope and the neutral point. The gap study
  (`AeroSandbox/notebooks/03_gap_study.ipynb`, report `AeroSandbox/docs/methods_report.md`) finds: the VLM and the
  textbook build-up put the neutral point at x 0.11 to 0.13 m, near the sheet CG (x 0.110 m). flow5 puts it at
  x 0.223 m. AeroBuildup agrees with flow5 only because NeuralFoil gives the NACA 0012 tail a 2D slope of about 8 per
  rad at Re 2e5. Open: ask for a flow5 T7 run of the wing alone, the tail alone and wing plus tail, and copy the sweep
  folder to `flow5/work/currawong/sweeps/`. Do not fly at the T7 CoG on the strength of the flow5 margin until then.
- The tail boom is a CREO spoke tube (`tail_boom` under 1.2.2.4, radius 0.0175 m, placeholder). Replace it with a Creo
  export of the boom. The flow5 plane XML and the OpenVSP model do not have it yet: put it in the flow5 plane for the
  new sweep (confirm that flow5 takes a second body).
- The flow5 export does not give the air density, so the initial altitude 0 m is a placeholder.
- AeroSandbox model: the quadplane retrofit (VTOL rotors on the wings) is the next stage. The worker already takes a
  list of propulsors in the airplane. The mission and the lift rotors are not in it yet.
- Battery: contract B gives no internal resistance, so the chain uses the nominal voltage. The energy is the full capacity.
- Propeller airfoil: the Currawong_V1 blade file does not store it. Proptimiser uses Clark-Y (see Propalyser
  `components/props/Currawong_V1`). Confirm it with the mould or a stand test at J > 0.
- Proptimiser commit 3346e66 (Currawong_V1, the motor chain, the CasADi path without JAX) and the Propalyser commit
  39c770c are local commits. Push them, so `aeroplan setup AeroSandbox` can install Proptimiser from git.
- Contract B `/motor` has three new optional attributes (`chain_kappa_nd`, `chain_r_tot_ohm`, `chain_q0_Nm`). Record
  them on the AeroPlan exchange page (section B): AeroPlan owns the contract.
- ArduPilot spoke: the log is not decoded yet (no normalised flight record).
- The web editor (glTF and JSON in the browser, HDF5 slices from a backend) is shelved.
- No dataset has a sigma yet: no source gives an uncertainty estimate.
