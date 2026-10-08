# Currawong integration

Currawong is a 3.3 m, 8.3 kg fixed-wing UAV. Until now Aerolink held its data. This section tells an engineer
what moved into AeroPlan, what did not, and what is still missing.

## State on 2026-10-08

| Area | State |
|---|---|
| Raw artefacts | 51 files copied by hand into `muas-fleet-data/aircraft/currawong/raw/`. All are hashed and classified. |
| Hand config | YAML (`config/currawong.yaml`). Sections for the controls, actuators, autopilot, ground, visual parts, analysis points and requirements. |
| Reference data | `reference.json`: S, b, cbar, nominal CG, MRP. The CG is a placeholder. |
| Mass | ADH node `1.2` holds the whole-aircraft mass. It is a **placeholder**. No weighing exists. |
| Aero | 6 flow5 point datasets, and the build-up `dml/aero.dml` (T7 point, viscous polar, sweep control derivatives). No uncertainty estimate. |
| Propulsion | The flying system `currawongcustom` (Currawong V1, D 0.508 m, stand run, placeholder). |
| Control system | 4 surfaces with actuators, and the servo map of the flight controller (ADH 1.2.5.10). |
| Requirements | The mission `demo_circuit`, 13 targets and the analysis speeds: ADH requirements on node 1.2. |
| Visual | 9 CAD parts, the fin (flow5) and the boom (placeholder tube), with a hinge for each moving part. |
| Export package | `aeroplan package build currawong` writes it. Aerolink reads it, builds JSBSim, passes its trim check and animates the FlightGear model. |
| Ground truth | flow5 sweep `currawongv5_testfuse` (user, 2026-10-08). |

The package carries `placeholder: true`. It flies in simulation. It is not a flight approval: the mass, the CG, the
limits and the servo data are still estimates (see [](missing_data.md)).

## What the integration did

1. Copied the raw files by hand from the Aerolink repo into the fleet-data repo (`cp -p`, no link).
2. Wrote `inventory_notes.yaml`: one entry for each group of raw files, with the facts that the Aerolink
   README, CLAUDE.md and file headers give. A fact that no file gives is `unknown`.
3. Ran `aeroplan integrate currawong`. It wrote the files in [](data_map.md).

## What it did not do

- It did not fix any value. A placeholder stays a placeholder and carries a flag.
- It did not use the Aerolink `aircraft/currawong.h5` as a source. That file is a derived cache.
- It did not choose between two sources. Where two disagree, the page [](data_map.md) lists both.

## Where to go next

- To run the integration again, or to add a file: [](procedure.md).
- To close a gap: [](missing_data.md).
