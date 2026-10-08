# Missing data register

Every gap that blocks or weakens the Currawong SSOT. **No value was assumed.** Each item says what is missing, why it
matters, where it enters the data model, and what would close it.

Priority: **P1** blocks the first export package. **P2** blocks a good model. **P3** improves confidence.
Status values: `open`, `needs-confirmation` (a value exists but nobody verified it), `closed`.

To close an item: add the source (see [](procedure.md)), then set the status here and write the date and the person.

## P1: blocks the first export package

| ID | Missing | Why it matters | Enters at | Source that would close it | Status |
|---|---|---|---|---|---|
| M-01 | Position of the **flow5 origin relative to the nose datum**. A session doc states the origin is the wing root leading edge (not confirmed). | All Currawong values use the flow5 origin. The plan's design frame uses a nose datum. | `reference.json` `design_frame` | The flow5 or CAD document that fixes the origin. | needs-confirmation: the CAD fuselage front is at x = -0.6564 m and the CAD wing root leading edge at x = -0.0744 m (datum check, 2026-10-08). The package keeps the flow5-origin frame, which Aerolink reads |
| M-02 | **Weighed mass and measured CG** of the aircraft. | The CG is the MRP. The mass and CG in the hand config come from a retired plane export, flagged placeholder. | node `1.2` `mass_properties`, `reference.json` | Weighing record with the CG method and the configuration that was weighed. | open |
| M-07 | **Off-nominal effects** (gear, payload, battery position). The nominal configuration is closed: the user named `currawongv5_testfuse` as the ground-truth aircraft (2026-10-08). | The build-up model needs named corrections. | `configs.json` | A short statement from the team. | open (nominal closed 2026-10-08) |
| M-10 | **Propeller installation**: thrust axis, spin, hub, diameter. | The propeller node and the thrust line need all of these. The schema has no defaults. | node `1.2.3.9`, hand config `propulsion` | The blade on the aircraft and its diameter. | needs-confirmation: system `currawongcustom` flies (user). D 0.508 m from four sources (F-9). Hub from the CAD (datum check within 2.1 mm). Spin cw from the CAD blade pitch, but the CAD blade can be the APC 20x8E (F-11) |

## P2: blocks a good model

| ID | Missing | Why it matters | Enters at | Source that would close it | Status |
|---|---|---|---|---|---|
| M-03 | **Origin of the mass and inertia numbers**, and a **CAD mass-property export** (mass, CG, inertia for each part). | The hand values say only "from a retired plane export". The origin of its inertia is not recorded. | node `1.2` and child nodes | Creo mass properties for each part, with the axes used. | open |
| M-04 | **Sign convention of Ixz** in the flow5 export. | The hand config has `ixz_sign` 1.0 and asks to check against CAD. The value is stored as written and flagged. | `Inertia.unverified_products` | A CAD inertia tensor, or the flow5 documentation. | needs-confirmation |
| M-05 | Confirmation that the **flow5 polar moments are about the polar CoG**. | The MRP of every aero dataset relies on it. Source today: the Aerolink CLAUDE.md. | `reference.mrp` of each aero dataset | flow5 documentation page, or a test with a point force. | needs-confirmation |
| M-06 | **Sign of a positive flow5 flap** for elevator, aileron and rudder, and the **physical deflection limits** of each surface. | Aerolink flips its fit so that Cmde is negative. That is a physical assumption, not a check. The hand config's 20 deg is a command scale, and the package uses it as the limit. | control datasets, control-surface nodes | A test sweep with a known flap direction. Servo and linkage limits. | needs-confirmation |
| M-09 | **Choice between the inviscid and viscous alpha sets.** The viscous set stops at 6 deg. XFoil settings. | Two nominal candidates exist for one term. | `dml/aero.dml` CD0 and K | Team decision. The flow5 log for the lost points. | needs-confirmation: the package takes CD0 0.0162 and K 0.0458 from the viscous polar (all 6 points). The T7 point is inviscid. It is not known if flow5 adds fuselage friction drag |
| M-11 | **Rate-derivative definition** in flow5: how p, q and r are made nondimensional. | The damping terms (CLq, Cmq, Clp, Clr, Cnp, Cnr, CYp, CYr) come only from the T7 file. The package reads them as the old Aerolink did (c/2V and b/2V, aeronautical signs). | `dml/aero.dml` | flow5 documentation. | needs-confirmation (see F-10) |
| M-12 | **Control-surface geometry and hinge data**, and the **foil and flap data** behind the plane XML. | The span and hinge fractions of the surface nodes are placeholders. The visual hinges come from the front edge of each CAD part. | control-surface nodes, `visual/parts.json` | CAD hinge axes. The flap hinges of the `.fl5` foils. | needs-confirmation |
| M-15 | **Thrust-stand data.** Also data for the real motor, ESC and battery. | The propulsion data is a vendor model. No stand run exists. The source says placeholder. | Propalyser file, then the Ct/Cp dataset | Stand runs. The `Thrust_test_stand` repo may hold them: **not scanned yet**. | open |
| M-16 | **Stall and post-stall data** (CL max, CL min). | The hand config marks them placeholder. T1 stops at 12 deg. | `stall` in hand config | A higher-alpha sweep with viscous data. Wind-tunnel or flight data. | open |
| M-20 | **Uncertainty estimates for all aero data.** | flow5 gives none. Every aero dataset is `unavailable` ([M&S 33] c). | `uncertainty` of each dataset | A second tool for tool-spread (see M-13). A grid study. Flight identification. | open |

## P3: improves confidence

| ID | Missing | Why it matters | Enters at | Source that would close it | Status |
|---|---|---|---|---|---|
| M-08 | **Meaning of Propalyser `u_model`** (relative or absolute, coverage) and the **Monte Carlo level**. Export from a clean Propalyser commit. | The per-point uncertainty of the Ct/Cp table cannot be used until the meaning is known. | `prop.ctcp` dataset | Propalyser spec section on `u_model`. A new export. | closed 2026-10-08: contract B v2 gives absolute 1-sigma columns, Monte Carlo coverage 0.95, export from clean commit 31adc1c |
| M-13 | **`currawongathenaoutputs.txt`** in the AeroPlan folder. On 2026-10-08 it holds 34 lines of sizing outputs: wing area 0.9745 m^2, span 3.0625 m, MAC 0.3669 m, total mass 8.0228 kg, and scores. | The values differ from the hand config (S 1.0762 m^2, b 3.3 m). It is a design-sizing result, not the built aircraft (F-15). | none | none | closed 2026-10-08: the user says Athena, the old MUAS optimiser, wrote it for the preliminary sizing |
| M-14 | **Flight data.** None exists. The SITL recording `pdarcs_circuit.csv` was deleted on the user's order (2026-10-08). | Flight data is the only truth source (role `truth`, fidelity L4). | truth datasets | Real flight logs (`.BIN`), test cards, the matching configuration. | open |
| M-17 | **Ground contact data**: spring, damping, gear geometry. The CAD holds no nose wheel. | Placeholders in the hand config. The structure contacts use 3 times the gear values (old Aerolink rule). | `muas.ground_contacts` on node 1.2.2 | Drop test or measurement. A nose-gear CAD part. | open |
| M-18 | **Requirements targets.** | Placeholders. The team has not agreed them. The T7 static margin (0.285) is above the target maximum 0.15 (F-12). | ADH requirements on node 1.2 (`muas.target`) | Team decision. | open |
| M-19 | **Per-component mass list** (bill of materials or CAD). | The mass roll-up needs items with mass, CG and sigma. | child nodes of `1.2` | BOM with weights. | open |
| M-22 | **Servo data**: the PWM range and trim of each surface output, SERVOn_REVERSED of the Cube, the servo model, its lag and rate limit. | The package holds the channel and sign only. The lag 0.04 s and rate 300 deg/s are old estimates. | `muas.autopilot` on 1.2.5.10, `muas.actuator` on each surface | The Cube parameter file (Mission Planner, full parameter list). The servo data sheet. | open |
| M-23 | **Propeller inertia** about the shaft. | The 0.0008 kg m^2 is a placeholder for a 16 in propeller (Propalyser component Currawong_V1). | contract B `/propeller ixx_kgm2` | Blade mass and a CAD inertia, or a pendulum test. | open |
| M-21 | **Confirmation of S, cbar and root chord.** S and cbar are "implied" values. The root chord is from old sizing scripts that are no longer in the repo. | These are the reference of every coefficient. | `reference.json` | flow5 reference dimensions screen. | needs-confirmation |

## Data sources to ask for (short list)

1. A weighing record with the CG, or a statement that none exists (M-02).
2. The Cube parameter file and the servo data sheet (M-22, M-06).
3. The blade on the aircraft: Currawong V1 (0.508 m) or a v2 blade (0.57 m) (M-10, F-9).
4. Creo mass properties and a parts list (M-03, M-19).
5. Real flight logs (M-14).

## Not yet checked

- The `Thrust_test_stand` repository (M-15).
- The Aerolink docs `aircraft_file.md`, `cad_to_flightgear.md` and `flow5_sweeps.md`. Only the README, CLAUDE.md, the hand config, the sweep files and the data files were read.
- The Propalyser repository beyond its README.
- The plane XML geometry beyond the fin (the package makes the fin from it). The datum check compares the wing and
  the tail positions only.
