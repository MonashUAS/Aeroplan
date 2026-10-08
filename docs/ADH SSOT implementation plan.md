# ADH-based SSOT: AeroPlan / AeroLink implementation plan

Scope: an architecture and implementation plan only. No team data is integrated here. No public Currawong data was sought. Every value in the snippets is a placeholder.

Citation keys used throughout:

| Key | Source |
|---|---|
| [ADH §x] | NASA/CR-20250007045 |
| [ADH repo: file] | Boeing/aircraft-data-hierarchy at commit `96179ca` |
| [TM …] | NASA/TM-2015-218675 Vol I/II, plus the companion paper AIAA 2015-1810 and the NESC site |
| [MGP …] | Scoggins et al., AIAA 2023-1185 |
| [Prev] | the earlier plan, *Aerolink AeroPlan data pipeline.md*, and its notes |
| [Inference] | my own reasoning |

---

## 1. Verdict

- **Yes, the split is sound.** AeroPlan should be the ADH-based SSOT manager and AeroLink the consumer of the export package, running JSBSim.
  - ADH's core argument is a central repository that separates "data from processes", so that tools can be re-ordered freely and fewer interfaces need maintaining [ADH §6].
  - The TM separates the vehicle model data from the sim framework. In the TM, most models were shipped as DAVE-ML and each framework had to translate them locally [TM Vol I p.13; AIAA 2015-1810; TM notes §4 inference].
- **Adopt ADH as a pinned fork plus a pattern, not as a dependency.** ADH is a prototype "still in development" [ADH §16]: no releases or tags, last code change March 2025 [ADH repo: git log]; leaves undefined [ADH §15.1]; JSON Schema export is broken (`Component.model_json_schema()` returns an Enum default, `ControlType`, that `json.dumps` cannot serialise) [ADH repo: smoke test, re-run on `96179ca` with pydantic 2.13.5]; free-text units and implicit frames [ADH §15.2]; no electric propulsion, rotors, mass properties, control-surface linkage, fidelity field or variants [ADH repo]. MUAS therefore owns a namespaced extension layer.
- **Of ADH's leaves, only DAVE-ML is standards-based.** It is not turnkey: no tests, tables held as strings, no DAVE-ML XML reader or writer, and the core `Behavior` class has no `DAVEfunc` slot [ADH repo]. `behavior.py` transcribes ANSI/AIAA S-119 (DAVE-ML) with gridded and ungridded tables, `Uncertainty` (normal or uniform PDF), `Provenance` and `CheckData` [ADH repo: behavior.py; ADH §13.3]. The same format carries the TM's F-16 model and S-119 names [TM Vol I p.13]. It can also hold scattered points, σ and provenance, which MGP needs [MGP §Q3]. **DAVE-ML is the bridge format for aero and propulsion tables.**
- **AeroLink's core job is a verified DAVE-ML → JSBSim compiler.** JSBSim cannot read DAVE-ML: a grep of the full repository finds nothing [TM notes §4; re-checked at JSBSim `0f4a5d6`], and no maintained converter exists [Prev: standards notes Q2]. The compiler must be accepted against the TM's F-16 (ACC11, ACC13.x) before it touches MUAS data [Inference from TM Vol I Table 6.3-1].
- **The master aero data is ungridded point datasets with σ and roles, never JSBSim tables.** Gridding and composition are export-time operations, which keeps MGP's nominal-plus-corrections structure available later [MGP §Q4 inference; Inference].
- **AeroPlan's sizing functions become a client of the SSOT core,** like Flow5 or OpenVSP. They are not privileged writers. This preserves ADH's tool-independence principle [ADH §6; Inference].
- **Expect reconciliation effort.** Even NASA tools needed many iterations, and "nearly every" framework found at least one significant error [TM Vol I F-2, F-10, F-12]. Budget for compiler verification first.

---

## 2. Reference summaries

### 2.1 ADH: NASA/CR-20250007045 (Aug 2025)

Engelbeck, Ocampo, Gablonsky et al. (Boeing, with GE, Collins and U. Michigan), "Model-Based Systems Analysis and Engineering: Aircraft Data Hierarchy". Code is in the Boeing/aircraft-data-hierarchy repository (Apache-2.0).

**What it is:** a Pydantic v2 data standard. A MIL-STD-881F WBS, aligned to SAWE RP A-8, gives the address space. Each WBS item is a recursive MSoSA node with four views: Architecture, Requirements, Performance and Behavior [ADH §10.3–10.4, §12.6].

**Facts that drive MUAS decisions:**
- A centralised repository with swappable tools and a digital thread [ADH §6, §11].
- WBS nested classes carry only `wbs_no`; children attach via `extra="allow"`/`adh_root`, so they are namespaces, not typed trees [ADH repo: work_breakdown_structure.py].
- `Component` has geometry, parameters, metadata, subcomponents, requirements, performance and behavior; `Propulsion` lacks behavior and performance [ADH repo: airframe.py, propulsion.py].
- `DAVEfunc` is the one standards-based leaf; the pyCycle demo stores engine decks in it [ADH repo: behavior.py; ADH §13.5]. Core `Behavior` is only `name`/`description`/`sequence: List[Activity]`/`metadata`, and `behavior.py` defines its own plain-`BaseModel` base, so extra keys on a `Behavior` are silently dropped. The demo reaches DAVE-ML through a subclass, `PropulsionCycleBehavior(Behavior).engine_decks: List[DAVEfunc]` [ADH repo: behavior.py; demos/PropulsionDemo/behaviorLib].
- WBS numbers in code: `1.2.2.2` Fuselage, `1.2.2.3` Wing (`1.2.2.3.3` Ailerons), `1.2.2.4` Empennage, `1.2.3.9` PropellerOrFanInstallation, `1.2.3.11` FuelSystem [ADH repo: work_breakdown_structure.py].
- JSON is the persistence format; YAML and XML are claimed but have no code [ADH §12.4; repo grep].
- Provenance hooks: `ModelDescription`, DAVE-ML `Provenance`, `Metadata.uncertainty/bounds` [ADH repo: performance.py, common_base_model.py]. Principle of Similar Treatment [ADH §10.5].

**Limitations:** a prototype with undefined leaves [ADH §15.1, §16]. No unit validation or frame model ("planned" [ADH §15.2]). Broken schema export, duplicate classes, no tests for behavior.py, and an Empennage copy-paste defect (no Rudder or Elevator class) [ADH repo]. DATCOM parameters are in feet. No mission or mass classes. Uncertainty quantification is future work [ADH §15.3].

### 2.2 TM: NASA/TM-2015-218675 Vol I (NESC-RP-12-00770)

"Check-cases for verification of 6-DOF flight vehicle simulations". Vol II holds the appendices; AIAA 2015-1810 is the companion paper.

**What it is:** a reference set of time histories for 16 completed atmospheric cases and the orbital cases. Seven tools took part, JSBSim among them. Tools were compared as a "family of solutions" with no pass/fail tolerance [TM Vol I §1; AIAA 2015-1810].

**Facts that drive MUAS decisions:**
- Cases build up from sphere and brick through Earth models, wind and ballistic flight to F-16 trim, manoeuvre, pole and dateline, then a rocket [TM Vol I Table 6.3-1].
- Most vehicle models are DAVE-ML with S-119 names; the F-16 has mass, non-linear aero and control laws [TM Vol I p.13; Vol II App. A].
- Frames: body FRD, NED, ECI/ECEF; 3-2-1 Euler angles relative to NED [TM datum page; AIAA 2015-1810 Table 3].
- Outputs are CSV with `<quantity>_<unit>_<axis>` columns [TM output_specs]; Vol I §12 asks for a binary format instead.
- Errors came from IC ambiguity (Earth-relative vs inertial rates), similar-sounding variables, revision drift, sign and transposition slips, and integrators [TM Vol I §7, §12; AIAA 2015-1810 lesson 13]. Recommendations R-5 and R-6 call for S-119 IC and time-history standards.
- Atmospheric cases are in US customary units (except the ACC17 rocket model, which uses SI) and orbital cases in SI; US 1976 atmosphere; WGS-84 with J2 [TM Vol II App. A, B].

**Limitations:** this is verification, not validation. There are no numeric tolerances ("acceptable agreement" was subjective). Case 14 was not completed, and the NESC site carries errata. The JSBSim repo contains only Atmos_02 and does not run it in CI [TM notes §6].

### 2.3 MGP: Scoggins, Wignall, Nakamura-Zimmerer, Bibb, AIAA 2023-1185 (SciTech 2023)

"Multihierarchy Gaussian Process Models for Probabilistic Aerodynamic Databases using Uncertain Nominal and Off-Nominal Configuration Data". NASA LaRC; NTRS 20220017623.

**What it is:** the true coefficient is f = f₀ + Σ wᵢ Δfᵢ. The nominal f₀ is a multifidelity GP, and each off-nominal effect has a correction hierarchy fᵢ = ρᵢ f₀ + δᵢ (Kennedy–O'Hagan AR1). The whole model is jointly Gaussian [MGP Q2].

**Facts that drive MUAS decisions:**
- Trained on scattered, binned raw data, not gridded tables. The noise model allows a separate σₙ per dataset; the demo in fact used one σₙ = 0.1 (normalised) for all datasets, set conservatively from within-bin variance of repeats (noise floor ≈ 0.05, doubled) [MGP Q2, Q3].
- Each record needs inputs, a coefficient in a consistent axis system and MRP, σ, and a role (nominal, correction-for-effect, held-out truth). Moments were transferred to a common CG [MGP Q3].
- Weights wᵢ need "truth" data or explicit priors [MGP limitations].
- Discrete configurations become correction GPs; continuous parameters are kernel inputs [MGP Q2 inference].
- Query modes: mean and variance, sampled functions, per-correction variance attribution [MGP Q2].

**Limitations:** the Gaussian output is "not currently easy to incorporate into existing aerodatabases" [MGP conclusions]. The demo used zero sideslip and 3 inputs. No uncertain inputs: only output noise and model uncertainty are modelled [MGP Q2 inference]. Outputs are modelled independently, so cross-coefficient correlation is lost. Cholesky cost becomes prohibitive at scale.

---

## 3. Architecture

```
                          muas-fleet-data (git + DVC)
                 ┌───────────────────────────────────────────┐
 Flow5 / OpenVSP │  aircraft/<ac>/adh/   ADH nodes (JSON)    │
 AeroSandbox ───►│  aircraft/<ac>/datasets/raw|processed     │◄── identified datasets
 Creo massprops  │  library/ (props, motors, airfoils)       │    (role=truth/correction)
 thrust stand    └──────────────────┬────────────────────────┘          ▲
 flight logs           AeroPlan core│ (validate, assemble,              │
 (adapters)                         │  compose, grid-check, export)     │
                                    ▼                                   │
                 ┌─────────────────────────────────────┐                │
                 │ EXPORT PACKAGE (immutable, sha256)  │                │
                 │ ADH JSON + DAVE-ML + manifest + IC  │                │
                 └──────────────────┬──────────────────┘                │
                                    ▼                                   │
                 AeroLink: compile DAVE-ML→JSBSim ─► verify (T1–T4) ─► run │
                           trim / SITL / replay / sysID ────────────────┘
```

**AeroPlan owns** [ADH §6; Inference]: the forked ADH and MUAS extension schemas, versions and migrations; ingestion adapters and provenance; configuration ids and roles; frames, MRP and reference geometry; moment transfer to the export MRP; build-up composition and the gridding plan; DAVE-ML generation and export packaging. Its sizing module is just another adapter that writes datasets, like Flow5's.

**AeroLink owns** [TM; Inference]: the DAVE-ML→JSBSim compiler and its acceptance suite; JSBSim version, integrator, dt, Earth and atmosphere settings; the IC spec, the S-119 output dictionary and check-case CI; trim, linearisation, SITL bridges, replay and sysID.

**The boundary is the single interchange artefact:** the *aircraft export package*. AeroLink does not import AeroPlan or ADH code. It validates the package against a versioned JSON Schema and the DAVE-ML DTD [Inference; ADH §6 tool independence; TM "translate locally" practice].

**Return path:** flight-identified results come back to AeroPlan as new datasets (role `truth`, or a named `correction`) with sysID covariance as σ. AeroLink never edits a package. A new package is cut by AeroPlan [MGP Q3 truth-data requirement; Inference].

**Changes from [Prev]:**
- `aircraft.yaml` and netCDF give way to ADH JSON, point datasets and DAVE-ML.
- These carry over unchanged: the L0–L4 ladder, the design frame, the tool adapters (Flow5 XML, OpenVSP API, Creo `.ibl`/parameters), the Creo topology contract, and the SITL bridges.

---

## 4. Decision register

Key: ✔ = consistent with ADH. **ext** = a MUAS extension where ADH is silent or broken. ✖ = deliberate deviation.

| ID | Decision | Rationale | ADH | TM | MGP-ready? |
|---|---|---|---|---|---|
| D01 | Vendor ADH `96179ca` into `aeroplan/packages/muas_adh/upstream/` with its LICENSE. Fixes go in a patch series (Enum schema default, graphviz/IPython imports, duplicate classes, Pydantic v2 config, a typed `DAVEfunc` slot on `Behavior`). Typed fields only, no `adh_root` dictionary store. | Upstream is stalled and unversioned. Two stores would drift. | ✔ pattern / ext fixes [ADH notes §6 options b/c; §3 inference] | n/a | n/a |
| D02 | Keep the MIL-STD-881F/SAWE `wbs_no` exactly as published. MUAS nodes attach under the nearest ADH slot, plus an `instance` id. Never invent new numbers. | Keeps an export path to "real" ADH and avoids collisions with 881F. | ✔ [ADH §10.3; work_breakdown_structure.py] | Supports one shared variable dictionary [TM lesson 13] | ✔ stable addressing for dataset→node links |
| D03 | All MUAS additions live under one key, `muas`, on each node, validated by MUAS models with `extra="forbid"`. Upstream fields stay untouched. | `extra="allow"` hides typos. A namespace keeps upstream merges clean. | ext [ADH repo: common_base_model.py] | n/a | n/a |
| D04 | Store **SI internally**. Every quantity carries an explicit `units` tag, checked by a units library at load. Convert only in exporters. Use S-119 names with unit suffixes at the boundary (`totalMass_kg`, `elevatorDeflection_deg`). | ADH units are free text; the TM uses US customary for atmospheric cases. S-119 suffixes make units explicit and SI-compatible (the TM's rocket files use `_kg`, `_kg-m2`). | ext (ADH "planned" [§15.2]) | ✔ names; ✖ deliberately not US customary [TM Vol II Tables 13, 18] | ✔ global normalisation needs consistent units [MGP Q3] |
| D05 | **Frames.** Geometry and mass in the design frame (m, nose datum, x aft, y right, z up = JSBSim structural frame ≈ ADH station/BL/WL). Dynamics in body FRD, NED, 3-2-1 Euler. Aero datasets declare `axis_system` (body/stability/wind) and sign. **Every aero dataset stores its MRP** and reference geometry. DAVE-ML has no MRP element (it only recommends forces and moments about "a defined reference point, given in aircraft coordinates" [daveml.org Ref, Moment reference]), so each `.dml` carries the MRP as constant `variableDef`s as well as in the package manifest. | Frame/sign errors and IC ambiguity were among the main TM error sources [TM Vol I §7, §12]; Flow5 has changed axes between versions [Prev]. | ext (ADH has only `ReferenceAxis.relative_to` and DAVE-ML `axis_system` strings) [ADH repo: airframe_geometry.py, behavior.py] | ✔ FRD/NED/3-2-1 [TM datum; AIAA 2015-1810 Table 3; Vol I §12] | ✔ MRP is required for moment transfer [MGP Q3] |
| D06 | The master aero data is an **ungridded point dataset**: a manifest plus a columnar table, holding processed points with per-point or per-dataset σ, alongside retained raw data. It maps to DAVE-ML `ungriddedTableDef` and provenance; role, effect, raw links and per-point σ have no DAVE-ML home and travel as MUAS fields or companion tables (D21), so the mapping is not lossless. JSBSim tables are generated only. | Gridded tables discard σ, repeats and coverage. | ✔ DAVEfunc ungridded [ADH repo: behavior.py] | ✔ DAVE-ML is the model format [TM Vol I p.13] | ✔ core requirement [MGP Q3, Q4] |
| D07 | Use a **build-up model**: static C(α, β[, V]); control increments ΔC(α, δ); rate derivatives (p̂, q̂, r̂); power-on increments. Configuration variants are **named correction datasets** Δfᵢ relative to a declared nominal, each with role and `effect` tags. | This is the conventional decomposition and keeps the input dimension per GP low. Only the configuration corrections map 1:1 to the Σ wᵢ Δfᵢ terms; build-up increments (control, rate, power) are separate terms, each with its own nominal-plus-corrections model, not MGP corrections. | ✔ list of `Behavior` entries (needs the D01 `DAVEfunc` slot, since core `Behavior` drops extras); ext for roles | ✔ multidimensional table look-up exercised by ACC13 [TM Table 6.3-1] | ✔ [MGP Q2; Q3 inference on dimensionality] |
| D08 | `fidelity` uses L0 handbook, L1 AeroSandbox, L2 Flow5/VSPAERO, L3 CFD/stand/CAD, L4 flight. `source_tool` is recorded separately. | ADH has no fidelity field. | ext [ADH notes §4] | n/a | ✔ fidelity levels inside each hierarchy (AR1) [MGP Q2; > 2 levels per hierarchy is MGP Q2 inference] |
| D09 | **Provenance** on every dataset and node: tool, tool version, input sha256, geometry/config hash, author, date and method. Reuse `ModelDescription` and DAVE-ML `Provenance`; put the hash fields in `muas`. | Reproducibility, and detecting stale data after geometry changes. | ✔ + ext [ADH repo: performance.py, behavior.py] | ✔ model revision drift caused errors [TM Vol I §7] | ✔ |
| D10 | **Retain raw data, including repeats**, immutable and hashed (DVC). Processed points record their binning method. | σ estimation needs within-bin scatter. | ext | n/a | ✔ [MGP Q3] |
| D11 | A `MassProperties` extension on every node: mass, CG in the design frame, inertia about the node's own CG with axes parallel to the design frame, product-of-inertia sign convention stated, source and σ. It rolls up through the WBS groups. | ADH has no mass class. The WBS groups are already a SAWE-style roll-up taxonomy. | ext; aligned to SAWE RP A-8 grouping [ADH §5.1; WBS docstring]; conventions per SAWE STD A-6 (2023) [Prev] | ✔ the F-16 DAVE-ML includes an inertia model [TM Vol I p.13] | n/a |
| D12 | **Electric propulsion and rotor extension.** `Motor`, `ESC` and `Battery` under `1.2.3` (battery treated like 1.2.3.11 FuelSystem). `Propeller`/`Rotor` under `1.2.3.9` with role {cruise, lift}, hub position, thrust axis and spin. Behaviour tables (CT, CP vs J, RPM) are DAVE-ML. | ADH propulsion covers turbofan and piston only, and `Propulsion` has no behavior field. | ext [ADH repo: propulsion_cycle.py; ADH §10.5 similar treatment] | n/a | ✔ same point-dataset model as aero |
| D13 | A `ControlSurface` extension: parent surface ref, η span, hinge x/c, limits, positive-deflection sign, S-119 name, JSBSim property. Rudder and elevator are `ControlSurface` instances under `1.2.2.4` Empennage with `muas.instance` ids, not new WBS numbers (D02); the missing classes are logged as an upstream defect. | ADH has no linkage, and the empennage list is a copy of the wing's (Ailerons…Slats at `1.2.2.4.3–.8`). | ext / fix [ADH repo: work_breakdown_structure.py] | ✔ S-119 control names [TM Vol II Tables 9, 11] | ✔ deflection is a continuous GP input |
| D14 | **Canonical JSON:** one file per node plus manifests, with sorted keys; `aeroplan assemble` makes a single ADH JSON. YAML only as a hand-edit overlay compiled to JSON, with a CI round-trip check. | Small diffs; fewer student merge conflicts. | ✔ JSON chosen [ADH §12.4] | n/a | n/a |
| D15 | **Schema versioning.** A root `muas_schema_version` (semver). The JSON Schema is exported and committed per version. Migrations run through `aeroplan migrate`. CI validates every aircraft against the current schema and does not rely on the upstream setuptools_scm version. | ADH has no schema versioning. | ext [ADH repo: pyproject.toml] | ✔ revision-drift lesson [TM Vol I §7] | ✔ long-lived datasets |
| D16 | AeroLink time histories use **S-119-style names** `<quantity>_<unit>_<axis>`, written as Parquet with a CSV view. Run metadata records the JSBSim commit, integrator, dt, atmosphere, Earth constants and IC rate frame. | Variable-definition mismatches; integrator differences. | n/a | ✔ [TM output_specs; Vol I §12, R-6; AIAA 2015-1810] | ✔ flight replay → truth datasets |
| D17 | **Initial-condition spec.** A JSON IC object in which the rate frame (`wrt: local_NED` or `inertial`), latitude type and attitude sequence are mandatory fields. | "A significant portion" of the TM effort went on misinterpreted ICs. | n/a | ✔ [TM Vol I §12, F-6, R-5; per-case errata] | n/a |
| D18 | **Check-case CI tiers** T0–T4 (§8). Two tolerance types: an NESC multi-tool envelope plus a margin, and golden-file regression with a pinned JSBSim. | The TM gives no numeric tolerance. | n/a | ✔ method [AIAA 2015-1810; TM notes §7] | n/a |
| D19 | **Export packages are immutable.** Content-addressed, never edited. A new version supersedes the old. Flight results return as datasets (§3). | Reproducible twin builds. | ✔ digital thread [ADH §11] | ✔ R-2 dissemination of models with results | ✔ the truth role stays separate from the nominal |
| D20 | **Probabilistic path.** Now: mean tables plus the DAVE-ML `uncertainty` element and companion σ tables. Every correction is exported as a separate JSBSim term × weight property (default 1). Later: σ dispersion properties, pre-sampled function table sets, and wᵢ dispersions. | Option (c) needs separable corrections from day one. | ✔ DAVE-ML Uncertainty [ADH repo: behavior.py] | n/a | ✔ [MGP Q4 options a–c] |
| D21 | **Per-point σ.** For gridded exports, σ goes in `normalPDF/bounds` as a `dataTable` shaped like the parent table. For ungridded tables, per-point σ is exported as a companion `<id>_sigma` ungridded table, with the dataset σ in `bounds`. | DAVE-ML 2.0 allows a per-point `bounds` `dataTable` only for an "identically shaped function table"; its use with ungridded tables is not specified [daveml.org Ref: bounds, statistics]. | ext [ADH repo: behavior.py `Bounds.value` accepts str, `DataTable`, `VariableDef` or `VariableRef`] | n/a | ✔ |
| D22 | **Gridding for JSBSim is a compiler step** with a declared grid. The error at the original points is reported, and the compiler rejects interpolation or extrapolation modes JSBSim cannot honour. | JSBSim tables are gridded, (multi)linear and clamped at the edge breakpoints, with no extrapolation in any dimension; > 3-D tables (`lookup="axis4"`…) exist only from v1.3.1 [JSBSim `src/math/FGTable.cpp` GetValue; PR #1443]. So DAVE-ML `extrapolate="neither"` + `linear` is the only mode honoured. DAVE-ML does not define ungridded interpolation [daveml.org Ref: function], so the compiler's gridding defines it. | ✔ InterpolateEnum/ExtrapolateEnum exist [behavior.py] | ✔ ACC13 exists to exercise multidimensional table look-up [TM Vol I Table 6.3-1] | ✔ the point store stays the master |

---

## 5. Repository structure

**Decision:** use three repositories.

| Repo | Contents |
|---|---|
| `aeroplan` | Software |
| `aerolink` | Software |
| `muas-fleet-data` | One data repository for all aircraft |

Why not a monorepo:
- ADH's centralised *data* repository is distinct from its tool library [ADH §6].
- The TM's separation of model from framework suggests AeroLink should be testable with no MUAS data at all (NESC and F-16 only) [TM; Inference].

Why one fleet repository:
- Shared component libraries (propellers, motors, airfoils) follow the Principle of Similar Treatment [ADH §10.5].
- Large files go through DVC or LFS [Prev].

```
aeroplan/
  packages/muas_adh/
    upstream/            # ADH @96179ca, LICENSE+NOTICE kept, untouched
    patches/             # numbered fixes (enum default, imports, dup classes)
    ext/                 # MUAS extension models: mass, propulsion_electric,
                         #   control_surface, aero_dataset, provenance, frames
    schema/v0.1.0/       # exported JSON Schema (committed per version)
    migrations/          # v0.1→v0.2 …
  spec/export-package/v1/  # package JSON Schema + DAVE-ML profile + S-119 dictionary
  aeroplan/              # core: validate, assemble, compose, export
  adapters/              # aerosandbox/, flow5/, openvsp/, creo/, stand/, sysid_import/
  sizing/                # conceptual sizing (a client of core)
  tests/
  .github/workflows/

aerolink/
  spec/                  # vendored copy of export-package spec (pinned version)
  compiler/              # DAVE-ML → JSBSim (aero, propulsion, mass, metrics)
  runtime/               # trim, linearise, run, SITL bridges, replay
  sysid/                 # emits dataset bundles for AeroPlan
  verification/
    nesc2015/            # pinned NESC zips + sha256 + errata version (DVC)
      scripts/ACC01.xml … ACC13_4.xml
      envelopes/         # derived min/max per case/variable
    f16_daveml/          # acceptance test for compiler (ACC11, ACC13.x)
    golden/<jsbsim-ver>/ # self-regression CSVs
    aircraft_checks/     # trim, sign, mass sanity rules
  .github/workflows/

muas-fleet-data/
  library/{airfoils,propellers,motors,escs,batteries}/   # datasets + manifests
  aircraft/currawong/
    reference.json       # frames, datum, MRP, S_ref/b_ref/c_ref, sign conventions
    configs.json         # config ids: nominal + named off-nominal effects
    adh/                 # one JSON per node, e.g. 1.2.2.3_wing.json
    datasets/
      raw/<ds-id>/       # immutable, hashed (DVC)
      processed/<ds-id>/ # manifest.json + points.parquet
    inventory.yaml       # artefact register (step 1, §7)
    exports/             # package index only (packages in DVC remote)
  dvc.yaml
  .github/workflows/validate.yml
```

---

## 6. Snippets

The snippets illustrate data shapes only. Placeholders are in `<…>`.

**6.1 An ADH-aligned node with a MUAS extension** [ADH repo: airframe.py, common_base_model.py, work_breakdown_structure.py; D02–D03, D09, D11]. `Component` has no `wbs_no` field, so `wbs_no` and `muas` are kept as extras under `extra="allow"` (checked: this JSON validates as `Component` at `96179ca`).

```json
{
  "wbs_no": "1.2.2.3",
  "name": "Wing",
  "description": "<main wing>",
  "metadata": {"key": "node_provenance", "value": "prov:<uuid>"},
  "subcomponents": [{"wbs_no": "1.2.2.3.3", "name": "Ailerons", "muas": {"instance": "ail_L"}}],
  "behavior": [], "performance": [], "requirements": [],
  "muas": {
    "ext_version": "0.1.0",
    "instance": "wing_main",
    "planform": {"frame": "design", "units": "m", "sections": [
      {"id": "root", "y": "<y0>", "x_le": "<x0>", "z_le": "<z0>",
       "chord": "<c0>", "twist": {"value": "<t0>", "units": "deg"},
       "airfoil_ref": "library/airfoils/<id>@sha256:<h>"}]},
    "mass_properties": {"mass": {"value": "<m>", "units": "kg"},
      "cg": {"frame": "design", "xyz": ["<x>", "<y>", "<z>"], "units": "m"},
      "inertia_about_cg": {"axes": "parallel_to_design", "units": "kg*m^2",
        "products_convention": "+integral(xy dm)", "Ixx": "<…>", "Ixz": "<…>"},
      "source": "estimate|cad|weighed", "sigma": {"mass": "<σm>"}},
    "fidelity": "L1",
    "provenance": {"tool": "<tool>", "tool_version": "<ver>",
      "input_sha256": "<h>", "config_id": "<cfg>", "author": "<name>",
      "created": "<iso8601>"}
  }
}
```

**6.2 Manifest for a processed aero point dataset** (shown as YAML for readability; canonical form is JSON) [D05–D10, D21; MGP Q3]

```yaml
dataset_id: aero.cm_static.<tool>.<cfg>.<n>
kind: aero_point
role: nominal            # nominal | correction | truth | validation
effect: null             # e.g. "stopped_lift_rotors" when role=correction
nominal_ref: null        # dataset/config this corrects
config_id: <cfg>
geometry_hash: sha256:<h>
fidelity: L2
inputs:   # all coordinates stored, including held-fixed ones
  - {name: angleOfAttack,       id: alpha, units: deg, range: [<a_min>, <a_max>]}
  - {name: angleOfSideslip,     id: beta,  units: deg, fixed: 0}
  - {name: elevatorDeflection,  id: de,    units: deg, range: [<de_min>, <de_max>]}
  - {name: trueAirspeed,        id: vt,    units: m/s, fixed: <V>}
outputs:
  - {name: pitchingMomentCoefficient, id: Cm, units: nd,
     axis_system: body, sign: "nose-up positive"}
reference: {S_ref: <S_ref> m^2, b_ref: <b_ref> m, c_ref: <c_ref> m,
            mrp: {frame: design, xyz: [<x_mrp>, 0, <z_mrp>], units: m}}
uncertainty: {level: per_point, column: Cm_sigma,
              method: repeat_scatter|binning|grid_study|tool_spread|sysid_cov|engineering,
              basis: "<short justification>"}
raw_ref: datasets/raw/<raw-id>  # repeats retained
processing: {binning: "<method, tolerances>", n_raw: <N>, n_points: <n>}
provenance: {tool: <tool>, tool_version: <ver>, input_sha256: <h>,
             run_settings_ref: <file>, author: <name>, date: <iso8601>}
data: points.parquet            # columns: alpha, beta, de, vt, Cm, Cm_sigma
```

**6.3 DAVE-ML ungridded table with uncertainty** [ADH repo: behavior.py; TM S-119 naming; element names checked against the DAVE-ML 2.0 reference manual pages (daveml.org: ungriddedTableDef, function, statistics, bounds, signal, documentRef); not yet validated against DAVEfunc.dtd. Fragment of a `DAVEfunc` body; `ref_ds_<n>` is a `<reference refID=…>` in `fileHeader`]

```xml
<variableDef name="angleOfAttack" varID="alpha" units="deg" axisSystem="body"/>
<variableDef name="elevatorDeflection" varID="de" units="deg" sign="TED positive"/>
<variableDef name="pitchingMomentCoefficient_static" varID="Cm_static" units="nd"/>
<provenance provID="prov_ds_<n>">
  <author name="<name>" org="MUAS"/><creationDate date="<yyyy-mm-dd>"/>
  <documentRef refID="ref_ds_<n>"/>   <!-- refID required; docID is deprecated -->
</provenance>
<ungriddedTableDef utID="Cm_static_nominal" units="nd">
  <provenanceRef provID="prov_ds_<n>"/>
  <uncertainty effect="additive">
    <normalPDF numSigmas="1"><bounds><σ_Cm_dataset></bounds></normalPDF>
  </uncertainty>
  <dataPoint> <a1> <de1> <Cm11> </dataPoint>
  <dataPoint> <a2> <de1> <Cm21> </dataPoint>
</ungriddedTableDef>
<function name="Cm_static">
  <independentVarRef varID="alpha" min="<a_min>" max="<a_max>" extrapolate="neither"/>
  <independentVarRef varID="de" min="<de_min>" max="<de_max>" extrapolate="neither"/>
  <dependentVarRef varID="Cm_static"/>
  <functionDefn name="Cm_static_fn"><ungriddedTableRef utID="Cm_static_nominal"/></functionDefn>
</function>
<checkData><staticShot name="cm_pt1">   <!-- check signals use signalName/signalUnits, not varID -->
  <checkInputs>
    <signal><signalName>angleOfAttack</signalName><signalUnits>deg</signalUnits><signalValue><a1></signalValue></signal>
    <signal><signalName>elevatorDeflection</signalName><signalUnits>deg</signalUnits><signalValue><de1></signalValue></signal>
  </checkInputs>
  <checkOutputs><signal><signalName>pitchingMomentCoefficient_static</signalName><signalUnits>nd</signalUnits>
    <signalValue><Cm11></signalValue><tol><tol_Cm></tol></signal></checkOutputs>
</staticShot></checkData>
```

**6.4 The resulting JSBSim function: gridded, with nominal and weighted correction** [D20, D22; property names checked in JSBSim source (`aero/qbar-psf`, `aero/alpha-deg` in FGAuxiliary.cpp; `metrics/Sw-sqft`, `metrics/cbarw-ft` in FGAircraft.cpp; `fcs/elevator-pos-deg` in FGFCS.cpp). A `<property value=…>` that is a direct child of `<aerodynamics>` is read by `FGModelFunctions::Load`, as in `aircraft/ah1s/ah1s.xml`; a system file also works.]

```xml
<property value="1.0">aero/w/<effect_id></property>   <!-- direct child of <aerodynamics>, before the axes -->
<axis name="PITCH">   <!-- ROLL/PITCH/YAW default to body axes, about AERORP -->

  <function name="aero/moment/Pitch_static">
    <description>Cm_static: nominal + w_i * dCm_i ; pkg <pkg_id></description>
    <product>
      <property>aero/qbar-psf</property>
      <property>metrics/Sw-sqft</property>
      <property>metrics/cbarw-ft</property>
      <sum>
        <table name="aero/coefficient/Cm_static_nominal">
          <independentVar lookup="row">aero/alpha-deg</independentVar>
          <independentVar lookup="column">fcs/elevator-pos-deg</independentVar>
          <tableData>
                     <de1>    <de2>
            <a1>    <Cm11>   <Cm12>
            <a2>    <Cm21>   <Cm22>
          </tableData>
        </table>
        <product>
          <property>aero/w/<effect_id></property>   <!-- default 1.0 or 0.0 per config -->
          <table name="aero/coefficient/dCm_<effect_id>"> … </table>
        </product>
      </sum>
    </product>
  </function>
</axis>
```

The `metrics` block takes SI with unit attributes (e.g. `unit="M2"`, `unit="M"`) [Prev: JSBSim ref manual; FGXMLElement.cpp conversion table]. AERORP = the export MRP (D05); JSBSim transfers moments from AERORP to the CG.

Force axes need explicit sign mapping in the compiler [FGAerodynamics.cpp]. `LIFT`/`DRAG` values are entered positive up and aft. JSBSim negates them and rotates them to body axes with Tw2b(α, β). `SIDE` is the wind-axis Y force. `X|Y|Z` with `frame="STABILITY"` also has X and Z negated (drag-like and lift-like). Body `X|Y|Z` values are used as given, while `AXIAL`/`NORMAL` are negated (positive aft and up). Force axis systems may not be mixed. So S-119 CL/CD/CY and body CX/CZ must each be mapped explicitly, and T0 tests use asymmetric (β ≠ 0) points.

**6.5 Export package manifest** [D19; ADH repo: performance.py ModelDescription]

```json
{
  "package_spec": "muas-export/1.0.0",
  "package_id": "currawong.<cfg>.<semver>",
  "sha256": "<hash of canonical file list>",
  "supersedes": "<previous package_id|null>",
  "source": {"repo": "muas-fleet-data", "commit": "<git sha>",
             "muas_schema_version": "0.1.0", "adh_upstream": "96179ca+patches.<n>"},
  "config_id": "<cfg>", "fidelity_summary": {"aero": "L1", "prop": "L1", "mass": "L0"},
  "frames": {"design": "x_aft_y_right_z_up_m_noseDatum", "body": "FRD", "euler": "3-2-1/NED"},
  "reference": {"S_ref": "<S_ref>", "b_ref": "<b_ref>", "c_ref": "<c_ref>",
                "mrp_design_m": ["<x>", "<y>", "<z>"]},
  "files": [
    {"path": "adh/aircraft.adh.json",  "sha256": "<h>"},
    {"path": "dml/aero.dml",           "sha256": "<h>", "standard": "ANSI/AIAA S-119-2011"},
    {"path": "dml/propulsion.dml",     "sha256": "<h>"},
    {"path": "mass/mass_items.json",   "sha256": "<h>"},
    {"path": "ic/initial_conditions.json", "sha256": "<h>"},
    {"path": "visual/<ac>.glb",        "sha256": "<h>"}],
  "datasets_used": [{"id": "<ds-id>", "role": "nominal", "sha256": "<h>"}],
  "corrections": [{"effect": "<effect_id>", "default_weight": 1.0}],
  "known_limits": ["beta_range: ±<b> deg", "no power-on increments"]
}
```

**6.6 Check-case CI sketch** (aerolink) [TM notes §7; D18]

```yaml
jsbsim: {version: <pinned>, integrator: <name>, dt_s: <dt>}
tiers:
  T0_static:   {on: [push], run: [schema_validate, units_tags, frame_transform_tests, dml_lint]}
  T1_env_eom:  {on: [nightly, jsbsim_bump],
                cases: [ACC01, ACC02, ACC03, ACC06, ACC07, ACC08, ACC09, ACC10],
                compare: nesc_envelope, margin: max(0.02*range, inter_tool_spread)}
  T2_compiler: {on: [compiler_change, nightly], model: f16_daveml,
                cases: [ACC11, ACC13.1, ACC13.2, ACC13.3, ACC13.4],
                pre: dml_checkdata_static_shots, compare: nesc_envelope}
  T3_aircraft: {on: [new_package], run: [checkdata_reproduce, grid_error, trim_points,
                stability_signs, mass_sanity, nan_range_scan, short_run_bounded]}
  T4_golden:   {on: [push], compare: golden/<jsbsim-ver>, abs_tol: 1.0e-5, same_timebase: true}
```

**6.7 CLI interface sketch** (command names only)

```
aeroplan init <ac> | inventory add <file> | ingest {geometry|mass|prop|aero} --tool <t>
aeroplan validate | migrate --to <ver> | assemble | compose --config <cfg>
aeroplan export --config <cfg> [--fidelity-floor L1] | import-dataset <bundle>
aerolink compile <pkg> | checkdata <pkg> | verify --tier T1..T4 | trim <pkg> --point <id>
aerolink run <pkg> --ic <ic.json> | sitl <pkg> | replay <log> | identify <log> --out <bundle>
```

---

## 7. Currawong → ADH integration, step by step

Rules for this procedure:
- Use categories and placeholders only. Do not integrate team data until Phase 1 exits (§10).
- Every step produces a committed artefact in `muas-fleet-data/aircraft/currawong/`.

| # | Entry criterion | Action | Output artefact | Done when | Governs |
|---|---|---|---|---|---|
| 0 | `muas_adh` v0.1 schema released; export spec v1 drafted | `aeroplan init currawong` creates an empty `1.0 AircraftSystem` with `1.2 AirVehicle` and `1.2.2`/`1.2.3` skeleton nodes | `adh/` skeleton, `reference.json` stub | Schema validates; CI is green | [ADH §10.3–10.4] |
| 1 | Step 0 | **Inventory artefacts** by type: shape (CAD, Flow5, OpenVSP, airfoils), coefficients (polars, derivatives, CFD, spreadsheets), propulsion (datasheets, prop tables, stand CSV), mass (CAD, weighings, estimates), flight (`.bin`, params, test cards). Record format, tool and version, date, configuration, candidate fidelity, whether frame/units/MRP are known, raw availability, hash. | `inventory.yaml` | Every artefact has a row and a hash; unknowns are flagged, never guessed | [MGP Q3; ADH §5.1; Inference] |
| 2 | Step 1 | **Define configurations:** nominal `<cfg_nominal>` (as-designed, clean) plus named off-nominal effects `<effect_A>`… Tag each row. | `configs.json` | Each row has exactly one configuration, or is marked "unresolved" | [MGP Q3 roles; ADH notes §4] |
| 3 | Step 2 | **Fix frames and references first:** datum, body FRD, MRP, S_ref/b_ref/c_ref, surface sign conventions; each artefact's native frame and transform. | `reference.json`, per-row `frame_map` | An asymmetric test point set round-trips; each coefficient artefact has an MRP or is marked "MRP unknown → σ inflated or excluded" | [TM Vol I §12; MGP Q3; D05] |
| 4 | Step 3 | **Map to WBS:** ADH `wbs_no` + `muas.instance`, or a MUAS extension type. | `wbs_map` in inventory | No orphans; no invented WBS numbers | [ADH repo: WBS; D02] |
| 5 | Step 4 | **Ingest geometry:** sections, airfoils (library ref + hash), fuselage stations, control-surface linkage, rotor placement. | `adh/1.2.2.*.json`, `adh/1.2.3.9*.json` | Flow5/OpenVSP generators reproduce the source within a stated tolerance; `geometry_hash` computed | [ADH airframe_geometry.py + ext; Prev topology contract] |
| 6 | Step 5 | **Ingest mass:** per-node items (estimate/CAD/weighed) with σ; roll up. | `muas.mass_properties` | Roll-up = independent total within σ; inertia is valid; CG in the design frame | [ADH §5.1 SAWE RP A-8; D11] |
| 7 | Step 4 | **Ingest propulsion:** motor, ESC, battery parameters; prop CT and CP vs J, RPM as point datasets. | `datasets/processed/prop.*`, `1.2.3` nodes | Reference static thrust and power match the source within σ | [D12; ADH §13.5] |
| 8 | Steps 3, 5 | **Ingest aero as points:** raw to `raw/` (repeats kept). σ by repeats/binning → convergence study → tool spread → engineering estimate. Tag role, effect, fidelity, `geometry_hash`. Transfer moments to the export MRP. | `datasets/processed/aero.*` | Manifest schema passes; all inputs explicit; `sigma.method` set | [MGP Q3; D06–D10] |
| 9 | Step 8 | **Compose the build-up:** per term (static, Δcontrol, rates), the nominal source per region plus corrections; define the JSBSim grid. | `compose/<cfg>.json` (source map) | Full envelope at ≥ L0/L1; gaps listed in `known_limits` | [D07, D22; Prev ladder] |
| 10 | Step 9 | **First export** at L0/L1 (L2 where available): ADH JSON, DAVE-ML with checkData, IC, manifest. | `currawong.<cfg>.0.1.0` | Spec, DTD and lint pass | [D19; ADH behavior.py] |
| 11 | Step 10; T1 and T2 green | `aerolink compile` → T3 → trim at `<V_trim>`. | Verification report | T3 passes, or each failure is explained and recorded | [TM method; §8] |
| 12 | Step 11 | Tag the baseline; open an issue for every `unknown`. | tag `currawong-baseline-v0` | Issues triaged | [Inference] |

---

## 8. AeroLink verification plan

**Tier T1: environment and EOM.** These cases are vehicle-agnostic, and every MUAS model depends on them [TM Vol I Table 6.3-1; TM notes §7].

| Case | Verifies | Why it matters to MUAS |
|---|---|---|
| ACC01 | gravity, translational EOM | baseline |
| ACC02, ACC03 | rotational EOM, inertia coupling, damping derivatives | quad and quadplane coupling; rate derivative path |
| ACC06 | WGS-84 + J2 | JSBSim default, as used in SITL |
| ACC07, ACC08 | steady wind, wind shear | wind is a large fraction of a small UAV's airspeed |
| ACC09, ACC10 | Earth curvature, Coriolis | cheap to run |
| (ACC04/05) | round Earth | optional |

**Tier T2: the compiler acceptance test.**
- Compile the NESC F-16 DAVE-ML with AeroLink's compiler. Do not hand-write it.
- Pass the DAVE-ML `checkData` static shots first. Then compare ACC11 (trim and air data) and ACC13.1–13.4 (multidimensional table look-up, manoeuvres) against the NESC envelopes [TM Vol I Table 6.3-1; Vol II App. A].
- The F-16 includes control-law DAVE-ML (`F16_control.dml`, `F16_gnc.dml`), so the compiler must cover the MathML subset those files use [TM Vol II; Inference: verify the file contents].
- ACC15 and ACC16 are needed only if AeroLink handles lat/lon wrapping itself. ACC12 and ACC17 have low value for MUAS, and ACC14 was never completed, so it has no reference data [TM Vol I Table 6.3-1; TM notes §7].

**Tolerance philosophy.**
- The TM defines no numeric pass/fail [AIAA 2015-1810].
- T1/T2 rule: stay inside the min–max envelope of the NESC tools, widened by a margin of max(≈2 % of the variable range, inter-tool spread). Calibrate the margin first with stock JSBSim, and record it as an AeroLink engineering choice [TM notes §7; Inference].
- Use the errata versions of the initial conditions, and treat the ACC11 trim-speed conflict (335.15 vs 400 KTAS) as resolved by the errata [TM notes §2]. The IC V_NED = (400, 400, 0) ft/s gives 565.7 ft/s ≈ 335.15 KTAS, so "400" probably comes from the ft/s components [Inference; confirm against the erratum].
- T4 golden files: max absolute difference 1e-5 with the same time base, following JSBSim's `RunCheckCases`. Golden files are per JSBSim version, with fixed dt and integrator [TM notes §6].

**Tier T3: aircraft-level checks, per package** [Inference; Prev JSBSim issue #90 failure mode]:
- Check data: JSBSim reproduces the DAVE-ML static shots at the *original* points; gridding error reported and bounded.
- Stability signs at nominal points: Cm_α < 0, Cn_β > 0, Cl_β < 0, Cm_q < 0, Cl_p < 0, Cn_r < 0; control-power signs match `ControlSurface.sign`.
- Trim converges at `<V_trim>`, with trim α, δe and throttle inside table ranges (no extrapolation).
- Mass: total = roll-up; positive-definite inertia satisfying the triangle inequalities; CG inside its envelope; `negated_crossproduct_inertia="false"` consistent with the products convention [Prev Creo notes].
- NaN/range scan over the table hypercube; a short open-loop run stays bounded; S-119 unit suffixes match the units tags.

**Run hygiene for all tiers:** log the JSBSim commit, integrator, dt, atmosphere, Earth constants and IC rate frame [TM Vol I F-3, §12; AIAA 2015-1810].

---

## 9. MGP readiness checklist

**Must be true now**, so that MGP can be implemented later without re-ingesting data:

- [ ] Aero data is stored as scattered points. Raw repeats are retained and hashed [MGP Q3].
- [ ] Every point carries every input coordinate, including held-fixed ones (β, V, deflections, rates) [MGP Q3 inference].
- [ ] Outputs declare axis system, sign and nondimensionalisation. Reference geometry and **MRP** are stored, so a transfer to a common CG is possible [MGP Q3].
- [ ] σ is stored per point or per dataset, together with `sigma.method` [MGP Q3]. MGP models output noise only, so known input uncertainty (e.g. deflection measurement error) is recorded but must be folded into σ or deferred [MGP Q2 inference].
- [ ] `role` ∈ {nominal, correction, truth, validation}, plus `effect` and `nominal_ref` [MGP Q3].
- [ ] A `fidelity` level is recorded per dataset, giving AR1 ordering within each hierarchy [MGP Q2; more than two levels per hierarchy is MGP Q2 inference].
- [ ] Discrete variants are recorded as configurations and effects. Continuous parameters are recorded as inputs [MGP Q2 inference].
- [ ] Flight sysID results return as `truth` datasets with covariance [MGP limitations; D19].
- [ ] At least one validation dataset per effect is held out and flagged [MGP Q1 held-out config; "per effect" is Inference].
- [ ] Export keeps corrections as separate weighted terms (D20) [MGP Q4 option c].
- [ ] Units are consistent across datasets, which allows global normalisation [MGP Q3].

**Defer:**
- GP fitting, kernel choice, and estimating ρᵢ and wᵢ.
- σ-dispersion and function-sampled JSBSim table sets [MGP Q4 a, b].
- Coherent function sampling inside time-stepping [MGP Q2, NTRS 20220016480].
- Multi-output correlation and noisy-input GPs [MGP Q2 inference].
- Serving models AeroFusion-style [MGP Q4].

---

## 10. Actionable roadmap

| Phase | Deliverables | Exit criteria |
|---|---|---|
| **P0 Foundations** | ADH vendored with patches; `muas` extension models (frames, units, provenance, mass, electric propulsion, control surface, aero dataset); JSON Schema v0.1; export spec v1; three repos with CI | The schema exports with no crash. A synthetic placeholder aircraft validates, assembles and exports. |
| **P1 AeroLink verification first** | NESC data pinned; T1 scripts; DAVE-ML→JSBSim compiler (tables, MathML subset, mass, metrics); T2 on the F-16; golden files | T1 and T2 inside their envelopes; checkData passes; margins documented |
| **P2 Currawong skeleton** | §7 steps 0–4: inventory, configurations, references, WBS map | Every artefact is classified and hashed. Frames are resolved or flagged. |
| **P3 Currawong ingest + first export** | §7 steps 5–11: L0/L1 package; T3 report | The package passes T3. It trims and flies a bounded short run. |
| **P4 Tool adapters + L2** | Flow5, OpenVSP and AeroSandbox adapters write point datasets ([Prev] formats); composition and source map | An L2 package is built with no hand-edited files, and its sign and trim differences from L1 are explained. |
| **P5 Return loop** | `aerolink identify` → dataset bundle → `aeroplan import-dataset`; truth-role datasets | Package v(n+1) improves replay residuals on held-out manoeuvres |
| **P6 (later) MGP** | GP nominal + correction fit; σ tables; weight dispersions | Posterior trim α is consistent with flight truth |

---

## 11. Open questions, risks, verify-before-citing

**Risks and open questions:**
- ADH upstream may revive and diverge: keep a patch series and a WBS-path compatibility map [ADH repo activity].
- Compiler scope creep from the F-16 control-law MathML: do ACC11 first, then ACC13 [Inference].
- JSBSim internals, checked at master `0f4a5d6` (2026-10-06): `FGTable` lookups are linear and clamped; LIFT/DRAG/SIDE are negated and rotated as described under 6.4; `<property>` declarations are accepted in `<aerodynamics>`. Re-check these in the pinned version before T2, because N-D tables arrived only in 2026 (#1443) [JSBSim source].
- Multirotor and quadplane JSBSim modelling remains the largest twin risk [Prev].
- Legacy σ will often be an engineering estimate; label it, never present it as measured [MGP Q3].
- Open: access control in one fleet repo; whether to split the export spec into its own repo once a second consumer exists.

**Verify before citing** (these came from WebFetch extraction or are unconfirmed in a primary source):

1. All ADH report quotes and section or page numbers (§5.1, 6, 10.3–10.6, 12.4, 15.1–15.3, 16). The PDF was not downloaded [ADH notes].
2. TM finding and recommendation numbering (F-1 to F-12, R-1 to R-6), page numbers, the ACC11 335.15 vs 400 KTAS conflict, and the case 12, 13.x and 16 initial conditions (not read) [TM notes].
3. MGP equations, especially Eq. 25 with w₀; σₙ = 0.1; the weights table; binning tolerances [MGP notes].
4. DAVE-ML 2.0 element syntax. Element names and content models were checked through WebFetch of the daveml.org 2.0 reference pages (`ungriddedTableDef`, `function`, uncertainty/`bounds`, `signal`, `documentRef`, `variableDef`/`provenance`), but the DTD file could not be fetched (proxy 403) and no snippet was machine-validated. Open points: element ordering inside `DAVEfunc`, and whether per-point `bounds` tables are allowed for ungridded tables.
5. The SAWE references: what RP A-8 (reporting groups) and STD A-6 (2023, coordinate conventions) actually say [Prev standards notes].
6. The JSBSim 1.3.1 release date. The git tag `v1.3.1` points to a commit dated 2026-05-17 (`v1.3.0` to 2026-04-09), which resolves the 2024 vs 2026 conflict in favour of 2026, but the GitHub release page was not checked. N-D (> 3) tables were merged 2026-05-10 (#1443) and are present at `v1.3.1` [JSBSim git].
7. The F-16 DAVE-ML file contents (breakpoints, interpolation, MathML) inside `Atmospheric_models.zip` (not downloaded) [TM notes §4].
