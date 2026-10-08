# Data map

Where each Aerolink data source goes in AeroPlan. Status: **ingested**, **pending** (readable, adapter not written),
**context** (kept as evidence), **not a source** (derived).

## Sources

| Aerolink source | AeroPlan object | Status | Gaps |
|---|---|---|---|
| `imports/config/currawong.json` (hand values) | `config/currawong.yaml`, `reference.json`, ADH node `1.2` | ingested | M-01 to M-04, M-10, M-12, M-16 to M-18, M-21 |
| `sweeps/currawong.json` (sweep settings) | `raw/sweep_config/` | context | none |
| `imports/flow5/sweeps/currawongv5_testfuse/*.csv` | `datasets/processed/aero.flow5.*` (6 sets) | ingested | M-05, M-06, M-07, M-09, M-20 |
| `.../t7_reference_opoint.txt` | `dml/aero.dml` of the package (stability and rate derivatives, trim point) | ingested by the package build | M-05, M-11, F-10 |
| `imports/flow5/xml/*.xml`, `.../plane_with_body.xml` and foil `.dat` | the fin part of the package, the datum check. ADH geometry nodes `1.2.2.x` and an airfoil library are not written | in part | M-01, M-12 |
| `imports/flow5/Currawongv5_withfuse.fl5` | foils and hinges (binary project) | context | M-07, M-12 |
| `imports/cad/*.stl` | `visual/parts/` and `visual/parts.json` of the package, the datum check. No mass data in STL | ingested by the package build | M-03, M-12, M-19, F-11, F-13, F-14 |
| Propalyser `currawongcots.v2.h5` (contract B, clean commit 31adc1c) | `datasets/processed/prop.ctcp.propalyser.currawongcots` | ingested | M-10, M-15 |
| Propalyser `currawongcustom.v2.h5` (contract B, clean commit 31adc1c) | `datasets/processed/prop.ctcp.propalyser.currawongcustom` | ingested, gates D1, D2, P5 fail | M-10, F-9 |
| Propalyser `currawongcots.h5` (v1, dirty commit) | none. The adapter refuses version 1 | context | F-5 |
| Proptimiser `currawong_v2_structural.h5` (contract A) | read by Propalyser only. Not wired to a Propalyser system | pending | F-9 |
| Aerolink `missions/demo_circuit.json` | `missions/demo_circuit.yaml`, ADH Requirement (category mission) on node 1.2 | ingested | none |
| `currawong_v5_fuse.stp` (125 MB, in `raw/cad/`, git-ignored) | hash only | context | M-03, M-19 |
| `aircraft/currawong.h5` (Aerolink derived cache) | none. Never an input | not a source | none |

## Sections of the hand config

| Section | Goes to | Note |
|---|---|---|
| `atmosphere`, `reference`, `mass` | SSOT (`reference.json`, node `1.2`) | placeholders marked |
| `controls`, `actuators` | control-surface nodes (1.2.2.3.3 Ailerons, 1.2.2.4 Empennage) | `placeholder: true` |
| `autopilot` | node 1.2.5.10 AutomaticFlightControl (`muas.autopilot`) | `placeholder: true` |
| `ground` | node 1.2.2 Airframe (`muas.ground_contacts`) | `placeholder: true` |
| `propulsion` (system, spin, thrust line) | node 1.2.3.9 (`muas.propeller`), `propulsion/<system>.h5` | `placeholder: true` |
| `stall` | the CL_basic table of `dml/aero.dml` | `placeholder: true` |
| `requirements`, `analysis_points` | ADH requirements on node 1.2 (`muas.target`, `muas.analysis_points`) | targets, `placeholder: true` |
| `visual` | `visual/parts.json` of the package (CAD transforms, the boom diameter) | the old viewer settings (colours, shapes) are deleted |

## Findings: where the sources disagree or look odd

| # | Finding | Evidence | Action |
|---|---|---|---|
| F-1 | Propeller diameter: 0.4064 m (16 in) in the hand config, 0.508 m (APC 20x8E) in the Propalyser file. | hand config `propulsion.prop_diameter_m` (placeholder). Propalyser `manifest/thruster/propeller`. | Closed in part: the custom V1 flies (F-9). The ingested COTS table is not the flying propeller. |
| F-2 | The 2026-10-04 sweep ran on an earlier Aerolink aircraft file. | `results.json` `aircraft_sha256` d2a624c1... differs from the current file b625c214... | None for the data. The sweep inputs came from older hand values. |
| F-3 | The hand config has elevator, aileron, rudder "max" 20 deg. The sweep uses 15 deg. | hand config `controls`. `sweeps/currawong.json`. | The 20 deg is a command scale, not a limit. Physical limits are missing (M-06). |
| F-4 | The viscous alpha polar stops at 6 deg. The sweep asked for 12 deg. | `alpha_viscous.csv` has 6 points. `results.json` says 17 lost points. | Lost points are not in the CSV. The flow5 logs in `raw/` may show why (M-09). |
| F-5 | The Propalyser file came from a **dirty** repo state. | `manifest/generator/repo_state`: commit 9126b26, dirty true | Closed 2026-10-08. The v2 files come from clean commit 31adc1c. The v1 file stays as context only. |
| F-6 | `S` and `cbar` are "implied" values, not read from flow5. | hand config comment | Confirm in flow5 reference dimensions (M-21). |
| F-7 | The flight CSV looked like a SITL recording. | Mode MANUAL at start, battery 12.6 V, 10 Hz | Deleted on the user's order (2026-10-08). |
| F-9 | Propeller diameter of the flying system `currawongcustom`. The user said 0.55 m, then "may be 0.57 m, please check". | Four sources give 0.508 m: the Propalyser component, the old Proptimiser table, the design `Currawong_V1` (tip radius 0.254 m) and the mould insert export at Proptimiser 588118a (last station r = 0.2540 m). Only the `currawong_v2*` designs give 0.57 m. No source shows a v2 blade was made. | The package uses 0.508 m from the contract B file. Open question: is a v2 blade on the aircraft now? |
| F-8 | Moments are about the polar CoG. This is Aerolink's statement. | Aerolink CLAUDE.md | Confirm in flow5 documentation (M-05). |
| F-10 | Clr = -0.0082 and Cnp = -0.0004 in the T7 point. Strip theory for a straight wing gives about +CL/4 and -CL/8 (+0.21 and -0.10 at CL 0.84). | T7 file. Etkin and Reid, Dynamics of Flight, 3rd ed., Wiley 1996 [reference/index needed]. | Kept as written. Check the flow5 rate convention (M-11). |
| F-11 | The CAD propeller has an 8 in pitch: chord-line pitch 16.5 deg at r = 0.10 m and 11.8 deg at 0.15 m, against 17.9 and 12.2 deg for 8 in. It can be the APC 20x8E, not the custom blade. Its diameter is 0.508 m, as both. | datum check, CAD `propeller.stl` | The spin comes from this blade. Confirm the spin on the aircraft. |
| F-12 | Static margin 0.285 from the T7 neutral point (NP x 0.2231 m, CG x 0.1291 m, cbar 0.33 m). The target is 0.05 to 0.15. | T7 file, hand config | A handling requirement fails. The CG is a placeholder (M-02). |
| F-13 | The flow5 fin ends 0.10 m above the CAD rudder top. The CAD rudder starts 0.035 m below the fin root. | datum check | The visual parts show it. Check the fin in the CAD and in flow5. |
| F-14 | The CAD has no nose wheel and no boom. | CAD folder | The package has a nose ground contact (hand value) but no nose-wheel part. The boom is a placeholder tube. |
| F-15 | `currawongathenaoutputs.txt` gives S 0.9745 m^2 and b 3.0625 m. The hand config gives 1.0762 m^2 and 3.3 m. | the file, hand config. User 2026-10-08: Athena, the old MUAS optimiser, wrote it for the preliminary sizing | Not used. A sizing result is not the built aircraft. |

## What each dataset holds

Each flow5 dataset holds inputs, outputs, the reference and notes.

- Inputs: alpha, beta, bank, speed and (for a control polar) the deflection.
- Outputs: CL, CD, CY, Cm, Cl and Cn.
- Reference: S, b, cbar and the MRP. The hash of the analysed plane XML is in the provenance.

- **Cl and Cn are stored as flow5 wrote them.** Their sign is the opposite of the aeronautical roll and yaw moments.
  The output record says so. A user must flip them. Source: Aerolink `polar.py`. Not re-verified.
- **Control deflection** = lo + Ctrl x (hi - lo). The sign of a positive flap is unverified (M-06).
- **Uncertainty is `unavailable`** for all aero data (NASA-STD-7009B [M&S 33] c).
- **The Propalyser tables** (contract B v2). Contract B states `u_model` as absolute 1-sigma columns `CT_sigma` and
  `CP_sigma`, so M-08 is closed. The Monte Carlo intervals for Ct0 and Cp0 are in `derived`.
  - `currawongcots`: APC 20x8E (D 0.508 m), basis vendor, L0, uncertainty quantitative. It is not the flying propeller.
  - `currawongcustom`: Currawong V1, basis stand, L3, uncertainty `unavailable`. Its file states D 0.508 m. The user
    states D 0.55 m (F-9). Gates D1, D2 and P5 fail. The adapter writes each failed gate into the manifest notes.
- **Proptimiser contract A** (`currawong_v2_structural`, D 0.57 m, 176 points) passes the Propalyser reader. No
  Propalyser system uses it yet, because the flown design is not known (F-9).
