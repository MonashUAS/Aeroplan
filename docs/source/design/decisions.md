# Decisions after checkpoint 1

Source of authority: the implementation brief (D01 to D22) and the user answers of 2026-10-08.
ADH decides the design. A MUAS extension is allowed only where ADH is silent or broken.

## User answers and how the code applies them

| # | Answer | Applied as |
|---|---|---|
| 1 | Aerolink keeps `aircraft/*.h5` as a derived cache. | The `.h5` is rebuilt from the export package. It is never an input to AeroPlan. |
| 2 | Flow5, CAD and config ingestion live in AeroPlan. | `src/aeroplan/adapters/`. Config works. Flow5 and CAD are contracts only (P4, P3). |
| 3 | Proptimiser writes through Propalyser. | Proptimiser has no AeroPlan interface. Propalyser is the only propulsion adapter source. |
| 4 | Propeller schema is Ct/Cp tables. | `PropCtCpManifest` in `muas/propulsion.py`. |
| 5 | Follow the implementation plan. | Decisions D01 to D22 stay. The package is a folder (ADH JSON + DAVE-ML + manifest + IC) with an `.h5` wrapper. |
| 6 | Hand config moves to YAML. | `config.py`. YAML in, sorted-key JSON out, round-trip check (D14). |
| 7 | MRP is the CoG. | See "MRP" below. |
| 8 | Propulsion reaches Aerolink through the package. | The package holds the contract B file as `propulsion/<system_id>.h5`, unchanged. Aerolink reads it only from the package. |
| 9 | Create an uncertainty schema. | `muas/uncertainty.py`. See "Uncertainty". |
| 10 | NESC F-16 is verification. Test suites follow ADH methods. | See "Test method". |

## Package format (resolved)

The user chose the folder plus a wrapper. The folder is the immutable package (`manifest.json` plus listed files, each with a sha256).
`aeroplan package pack` wraps one verified folder into ONE `.h5` for hand copy. `unpack` rebuilds the folder and verifies it.
The round trip is byte-identical (tested). Aerolink reads the folder form.
Gap: the `.h5` holds the files as bytes. It does not yet hold CPACS. CPACS generation is not in the brief's P0 scope.

## MRP

Finding: a literal "instantaneous CG" cannot be the MRP. The CG moves with battery and payload.
A dataset tied to a moving point goes stale at each mass change. JSBSim keeps AERORP fixed and moves moments to the current CG itself (brief 6.4).

Decision: **MRP = the CG of the nominal configuration, stored as a fixed point in the design frame.**
- The model `Mrp` records `config_id` and an optional mass-properties hash. A mass change makes the hash stale and CI can flag it.
- `ReferenceData` rejects an MRP that differs from `nominal_cg`.
- Every dataset stores its own MRP (D05). `frames.transfer_moment_coefficients` moves moments between points: `M_to = M_from + d x F`.
- Tests: lift aft of the target point gives nose-down. A transfer there and back returns the input at an asymmetric point.

Recommendation for the upcoming aerotoolbox (upstream, needs your decision):
1. Tools should write forces and moments about a **geometry-fixed datum** (the design-frame origin), not about the CG.
   Aerodynamic results depend on geometry. The CG is a mass-model result. If a tool bakes the CG in, each mass change forces a new aero run.
2. Tools must always write the reference point with the data (`mrp` field) and the body-axis force coefficients.
3. AeroPlan then transfers to the nominal CG at composition. This keeps your answer 7 at export and removes the coupling upstream.
Textbook support: the neutral point is defined by geometry, the CG by mass. See docs/references.md A10.

## Uncertainty

Sources, in order of weight:
1. **NASA-STD-7009B** (approved 2024-03-05). Text checked in the PDF.
   - [M&S 29]: record uncertainty in (a) input, (b) results, including margins and factors of safety and what they cover, (c) derived quantities. Field `scope`, list `factors`.
   - [M&S 28], [M&S 34]: record the process and rationale. Field `basis` (required), field `method`.
   - [M&S 33]: report a quantitative estimate, a qualitative description, or a clear statement that none is available. Field `status`.
2. **ADH / DAVE-ML (S-119)**: `effect`, normal and uniform PDF, `num_sigmas`, correlation. `Uncertainty.to_adh()` builds the ADH class. A test checks that ADH accepts the result.
3. **MGP (AIAA 2023-1185)**: per-dataset or per-point sigma and the method. Field `per_point_column` and `method`.

ADH has no home for per-point sigma (brief D21). It exports as a companion table.
Gap: NASA-STD-7009B asks for uncertainty to be recorded. It does not define a data format. The format here is a MUAS design, not a NASA schema.
Not done: sensitivity analysis ([M&S] section 4.3.5) and propagation. They belong to a later phase.

## Test method

ADH tests use pytest with Pydantic validation checks, import checks and unittest style. The brief adds tiers T0 to T4.
- T0 (static) is done in this repo: schema validation, units, frame transforms, YAML round trip, schema export, ADH compatibility, tool independence.
- The patched ADH passes its own 95 upstream tests. The unpatched upstream fails the schema export. Patch 0001 fixes it and a test guards it.
- T1 and T2 (NESC cases, F-16 compiler acceptance) belong to Aerolink. The F-16 case is a **verification** test only. It never judges MUAS data.
- Tolerances for T1 and T2 follow the brief: NESC envelope plus margin, margin set by a stock JSBSim run.
- Every test number is synthetic and labelled so.

## DAVE-ML validation

The 2.0 DTD is vendored in `spec/dave-ml/2p0/` with its source and hash (see `SOURCE.md`).
Two DTDs exist on daveml.org. The file at `/DAVEfunc.dtd` is revision 1.4 (preliminary, no `ungriddedTableDef`, `uncertainty` or `checkData`).
The 2.0 file is at `/DTDs/2p0/DAVEfunc.dtd`. It validates a NASA sample (HL-20, nasa/DAVEtools).
Result of the first check: the brief's snippet 6.3 layout was invalid. The writer put `provenance` at the root and mixed tables with functions.
The DTD wants provenance inside `fileHeader` and all tables before all functions. The writer is fixed.
`build_package` now rejects any S-119 file that fails the DTD. Open: the DTD checks structure only, not meaning (for example interpolation rules).

## CI

CI is allowed for AeroPlan only. The Aerolink "No CI service" rule stays in Aerolink.
The workflows copy the ADH process (Boeing/aircraft-data-hierarchy at `96179ca`, `.github/workflows/`):
- `python-package.yml`: build on push and pull request to main, over a Python version matrix. Same as ADH.
- `test-package.yml`: build, install the wheel, `pip install .[test]`, run `pytest`. Same triggers as ADH.
- Added for the patch series (D01): build the patched ADH copy, then run the 95 upstream ADH tests on it.
- `sphinx-docs.yml`: copy of the ADH Sphinx docs workflow.
- The workflows were not run on GitHub. I checked each step locally, including `python -m build`.
- Gap: the wheel does not carry `spec/` (the DTD). Tests run from the repo checkout, so they find it.

## Exchange round trip (2026-10-08)

Real files, copied by hand, no shared code:

| Link | File | Result |
|---|---|---|
| A: Proptimiser to Propalyser | `currawong_v2_structural.h5` (Proptimiser 175ab8c) | First run stopped: `m/s` against `m_s`. After the fix: 176 rows read, J and CQ identities hold |
| B: Propalyser to AeroPlan | `currawongcots.h5`, `currawongcustom.h5` (Propalyser 31adc1c) | Both ingested. The new unit check first refused 3 attrs (`N_m`, `kg_m3`) |

Decision: an `.h5` `units` attr uses the pint spelling. DAVE-ML keeps the S-119 spelling. The adapter checks every
`units` attr in a contract B file with pint ([](exchange.md)). The chained run (a Proptimiser design inside a
Propalyser system) waits for the flown design (F-9).

## Currawong package (2026-10-08, second round)

User answers and how the code applies them:

| # | Answer | Applied as |
|---|---|---|
| 1 | The propeller that flies is `currawongcustom`, "may have D = 0.57 m, please check". | Checked: four sources give 0.508 m, only the v2 designs give 0.57 m (finding F-9). The package uses the contract B value 0.508 m. |
| 2 | Author git commits as lmca0007, Liam M. | Commits and exports carry the author "Liam M." (git identity lmca0007). |
| 3 | Schema for the actuators, the ground contacts and the other gaps, grouped for later structural and control-system analyses. | `muas/control_system.py` (`Actuator`, `Autopilot`, `ServoOutput`), `muas/ground.py` (`GroundContact`). Contract B gets `ixx_kgm2`. See the key table in [](exchange.md). |
| 4 | SITL servos are managed in AeroPlan: the ground truth for SITL and the Cube. | `muas.autopilot` on node 1.2.5.10. Aerolink reads its servo map only from the package. |
| 5 | Handling targets and analysis speeds become ADH requirements. | `muas.target` and `muas.analysis_points` requirements on node 1.2. Aerolink reads them only from the package. |
| 6 | Next checkpoint: an animated, well-datumed Currawong that exports to Aerolink. No higher-order corrections. | `aeroplan package build currawong` and the datum checks (below). |

Node numbers. The old layout used 1.2.2.4 as "ControlSurface" and 1.2.5 as "LandingGear". In ADH those are Empennage
and Avionics. The package now uses the ADH names: ailerons on 1.2.2.3.3 Ailerons, elevator and rudder on 1.2.2.4
Empennage, the stabilizers on 1.2.2.4.1, the ground contacts on 1.2.2 Airframe, the flight controller on 1.2.5.10.

Aero sources (no new method, no correction):

- The T7 stability point of the ground-truth sweep gives the lift slope, the pitch terms and every rate and lateral
  derivative, with the rules of the old Aerolink.
- CD0 and K come from the viscous alpha polar (least squares of CD on CL^2, 6 points). The T7 point is inviscid.
- The 8 control derivatives come from the sweep `results.json`. Its validation passed.
- The stall shape stays the old placeholder table.

Datum check. One design frame (flow5: x aft, y right, z up, m). The build compares every geometry source and stops on
a failure: the CAD wing span against b_ref, the CAD wing and tail leading edges against the flow5 positions, the
aileron mirror, the CAD propeller hub, diameter and spin against the hand values and contract B, the main wheels
against the CAD gear, and the MRP, mass CG and T7 moment point. The result goes into the package as `checks/datum.json`.

The Aerolink run of the first package: `inspect`, `build`, `linearise`, `stability`, `check` (trim alpha 4.74 deg
against 4.84 deg predicted, both doublets OK), `fg build` (ailerons, elevator, rudder and propeller animate), and `fg preview`.

## Status against the roadmap

P0 items done: vendored ADH with a patch series, extension models (units, frames, provenance, mass, propulsion, control surface, dataset, uncertainty), JSON Schema v0.1.0, config compile, adapter contract, export package v1 (manifest, hashes, immutability, `.h5` wrapper), initial-condition spec, DAVE-ML writer for point datasets (DTD-validated), synthetic placeholder package, CI workflows.
Currawong integration (2026-10-08): raw files copied by hand to `muas-fleet-data`, 6 flow5 point datasets and 1 Ct/Cp dataset ingested, hand config moved to YAML, 21 gaps logged (see the Currawong section). Schema changes forced by the real data: `Distribution.INTERVAL`, `ScalarResult`, `Term`, `AxisSystem.DESIGN`, `Inertia.unverified_products`, optional `Provenance.created`, `ReferenceData.placeholder_fields`.
P0 items open: split into three repos, a DAVE-ML profile document, first CI run on GitHub.
