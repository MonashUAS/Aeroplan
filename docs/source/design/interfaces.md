# Repository interfaces

Status: DRAFT proposal, updated after the 2026-10-08 answers. Source: README.md of Proptimiser, Propalyser and Aerolink, and CLAUDE.md of Aerolink.
"AeroPlan" appears in none of those files. Every interface below is a proposal. Items marked "not stated" are not in the source files.
No repository was scanned beyond those four files.

## Data flow

```
Proptimiser --(propeller JSON)--> Propalyser --(system .h5)--> AeroPlan --(export package)--> Aerolink
                                                                  ^                              |
                                                                  +----(identified datasets)-----+
```

Cross-repo rule: copy files by hand. No symlinks. No hard-coded cross-repo paths.
Format rule: YAML for hand config, JSON for machine files, ONE .h5 (CPACS + DAVE-ML inside) for cross-repo aircraft data.

## Proptimiser (propeller design)

- Role: BEMT propeller design and optimisation. Not an aircraft data store. Source: README.
- Reads: its own `Inputs`, `BladeSpec`, `Propeller` classes (Python). APC `.PE0` import.
- Writes today: `propellers/<name>.json`, `.ibl` CAD curves, CSV station tables.
- Direction to AeroPlan: writes only. It does not read the aircraft package.
- Proposed artefact: propeller geometry record, plus a performance map (Ct, Cp against J and rpm). ADH node: 1.2.3.9.
- It must declare: SI units, blade frame (x chord, y radial, z thrust), twist sign (nose-up positive), diameter, pitch axis, sweep and rake signs.
- Mount transform to the airframe: not stated. Proposal: AeroPlan owns it.

## Propalyser (thrust-stand analysis)

- Role: analyse stand runs of motor, ESC, battery and propeller. Compare with vendor data and Proptimiser. Report uncertainty.
- Writes today: `export/<system>.h5` with a DAVE-ML payload (spec: `docs/propulsion_h5_spec.md` in Propalyser, not read), and `reports/<system>/compare.md`.
- Direction to AeroPlan: writes only. It replaces the current direct hand copy to Aerolink.
- Proposed artefact: one propulsion-system dataset, the existing `.h5`. ADH nodes: motor, ESC, battery and propeller 1.2.3.9 under 1.2.3.
- It must carry the static-chain (J=0) limit as metadata. The README says this chain overstates power in forward flight.
- Constraint: Propalyser and Aerolink share `h5map.py` and the h5 spec byte for byte. AeroPlan must not change the layout without a three-repo sync.

## Aerolink (JSBSim twin)

- Role today: owns one aircraft in `aircraft/currawong.h5`. Builds JSBSim, MATLAB linear models, ArduPlane SITL, flight-test files.
- Direction to AeroPlan: reads the export package. Writes identified results back as datasets.
- Proposed new import kind: `aerolink import package`. The existing `daveml.py` and `jsbsim_xml.py` are the candidate compiler.
- Conventions: SI. Axes x aft, y right, z up. Surface signs: elevator TE down positive, aileron rolls right positive, rudder TE left positive.
- Change: Aerolink `aircraft/*.h5` becomes a derived working file once AeroPlan is the SSOT.
- Placeholder flags (`"placeholder": true`) must pass through the package.

## Conflicts between the repos and the plan

| # | Conflict | Proposed resolution |
|---|---|---|
| C1 | Aerolink CLAUDE.md says hand config is JSON with `_` comment keys. The cross-repo rule says YAML. | Open question Q6. No change until the user decides. |
| C2 | Aerolink is the SSOT today. The plan makes AeroPlan the SSOT. | Aerolink .h5 becomes a derived file. Needs user approval (Q1). |
| C3 | The package is "ADH JSON + DAVE-ML + manifest + IC". The cross-repo rule says ONE .h5. | Open question Q5. Do not decide here. |
| C4 | Aerolink reference point is the flow5 origin, derivatives about the CoG. The plan stores MRP per dataset. | AeroPlan stores the flow5 origin and the CoG. MRP value: not stated. |
| C5 | Proptimiser blade frame (z thrust) differs from the aircraft frame. | AeroPlan holds the mount transform. |
| C6 | The Propalyser h5 layout is shared with Aerolink. | Freeze the layout. Change it in one coordinated step. |

## Open questions

Questions 1 to 4 and 6 to 10 of checkpoint 1 are answered. See `docs/decisions.md`.
Still open: package format, folder or ONE `.h5` (decisions.md "Tension").

Updates from the answers:
- Proptimiser has no AeroPlan interface. It feeds Propalyser.
- Aerolink flow5, CAD and config importers move to AeroPlan adapters. Aerolink keeps its importers until each adapter works.
- Aerolink `aircraft/*.h5` is a derived cache built from the package.
- Aerolink hand config moves from JSON to YAML.
- The MRP is the nominal-configuration CG (fixed point).
