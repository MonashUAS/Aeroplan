# AeroSandbox spoke

Two jobs in the AeroPlan Python (`spoke.py`): the initial sizing and the sized quadplane go into the source tree (`ingest`). The AeroSandbox model of an aircraft with its propulsion chain runs from the tree (`generate`). The models, the solver and the plots run in the AeroSandbox Python ([ADR 10](../../docs/decisions/0010-aerosandbox-in-its-own-python.md), [ADR 24](../../docs/decisions/0024-aircraft-models-in-code.md)).

## Where to start

| You want to | Open |
|---|---|
| See the Rosella sizing result (H4 12S, bought boom tube) | [notebooks/rosella_sizing.ipynb](notebooks/rosella_sizing.ipynb) |
| Change a few params and watch the design | the last cell of that notebook (`window.Window`) |
| Size a quadplane with other parts | [Size a quadplane](../../docs/howto/size-a-quadplane.md) |
| Read the saved model of the Rosella | [settings/rosella.json](settings/rosella.json) |
| Read the Currawong gap study (old) | [notebooks/deprecated/](notebooks/deprecated/README.md) |

## The files

| File | Job | Runs in |
|---|---|---|
| `spoke.py` | `ingest`, `generate`, `setup`. Builds the spec of a job from the ADH document. Reads `settings/<aircraft>.json` into the tree. Makes the AeroSandbox Python | AeroPlan Python |
| `component.py` | `Param` and the components (`Material`, `Tube`, `Rotor`, `Motor`, `ESC`, `Battery`, `Cables`, `Fuselage`, `PointMass`, `Airframe`, `Control`, `Spec`). The level functions `rotor_model`, `airframe_model`, `motor_model`. The Jung 2021 blade check | AeroSandbox Python (and AeroPlan Python for the JSON) |
| `model.py` | One class for each class of aircraft: `QuadplaneModel`, `FixedWingModel`, `MultirotorModel`. The jobs of the spoke. `python model.py job.json result.json` | AeroSandbox Python |
| `mission.py` | `FlightCondition`, `Segment`, `Mission` (the conditions and the energy of the segments) | AeroSandbox Python |
| `optimise.py` | `Problem` (one `asb.Opti` problem), `solve_level`, `ladder`, `evaluate`, `optimise` | AeroSandbox Python |
| `result.py` | `Result`, `Snapshot` (one iterate), the margin of a limit | AeroSandbox Python |
| `plot.py` | Static plots (PNG, shown on GitHub) and the plotly `LiveView`. It reads results and snapshots. It never solves | AeroSandbox Python |
| `window.py` | The window: one row for each param, Evaluate, Optimise, a live 3D view | AeroSandbox Python (notebook) |

## How a model works

A model is made from components in code (a notebook). A component is a set of `Param`. A param has a value, units, a source and a `placeholder` flag. A param that is `free` is a design variable. A fixed param is a parameter of the problem.

```python
boom.fix(r_o=0.0175, t=0.001)                  # the bought tube
model = QuadplaneModel("rosella", components, layout="H4")
run = ladder(model, "L0..L4")                  # L0 momentum ... L4 blade element theory in every state
result = run["reports"]["L4"]
model.result_summary = result.compact()
model.save()                                   # settings/rosella.json
```

A model evaluates one flight condition at a time (`add_to(problem, condition)`), like the Proptimiser `PropellerModel`. It calls the level functions of `component.py`. The level says which rotor model is used and which limits are on.

| Level | Rotor model | Limits on |
|---|---|---|
| L0 | momentum theory | mass, CG, energy, thrust (tip Mach) |
| L1 | fitted CT and CP table | and motor, ESC, duty, current, C-rate |
| L2 | table | and boom structure, boom frequency, clearance, control |
| L3 | BEMT in the take-off hover states, table elsewhere | all |
| L4 | BEMT in every state (Proptimiser, NeuralFoil sections) | all |

Each level has an elastic feasibility phase. It adds a slack to each limit and minimises the sum. A limit with a slack above the tolerance is named in the report. The optimality phase then starts from that point.

The model file `settings/<aircraft>.json` holds the components and the last result (`Result.compact`). `python -m aeroplan build rosella` reads it into the tree: the booms (with `muas.tube.material_data`), the rotors, the masses, the `sizing` record and the limits as `muas.target` requirements of node 1.2.

## Set up (once for each computer)

```
python -m aeroplan setup AeroSandbox --proptimiser <Proptimiser checkout>
python -m aeroplan setup AeroSandbox            # installs Proptimiser from proptimiser_git in the settings
```

This makes `tools/aerosandbox/.venv` (Python 3.12, uv). It holds aerosandbox, casadi, Proptimiser (no JAX), JupyterLab, ipywidgets and anywidget. The kernel is "AeroPlan AeroSandbox". Reload the VS Code window after the setup. If the kernel is still missing, use **Python: Select Interpreter** and choose `.venv\Scripts\python.exe`.

Copy the Proptimiser design and state file of each blade by hand into `work/aerosandbox/<aircraft>/proptimiser/{designs,propellers}/`. The Rosella notebook copies them from the work folders of Redback (lift blade) and Currawong (cruise blade).

## Load a custom propeller

A blade is a Proptimiser design: `designs/<name>.yaml` and `propellers/<name>.state.json`. The BEMT reads chord and twist from the state file at 25 stations from the hub radius to the tip.

1. Make the design in the Proptimiser checkout. Use one of these three ways:
   - Measured chord and twist (a scan or a maker drawing): write a shape CSV with the columns `blade,r_over_R,c_over_R,beta_rad`. Then run `.venv/Scripts/python -m proptimiser.fit_prop --shape <csv> --no-fit --name <name> --save`.
   - A maker bench table only: run `.venv/Scripts/python -m proptimiser.fit_prop --table <csv> --name <name> --save`. Add `--shape <csv>` to fit a scale of a known shape. The Rosella lift blade `MAD_FLUXER_22x6_6_jung` uses the Jung 2021 T-motor shape.
   - A new blade: use the Proptimiser optimiser.
2. Copy the two files by hand into `work/aerosandbox/<aircraft>/proptimiser/{designs,propellers}/`.
3. Set the rotor params in the notebook model cell: `design`, `design_aircraft`, `reference_radius_m` (the tip radius of the design file), `blade_diameter_m` and `blade_pitch_m`. For a bought prop, also set `mass_kg` and `pitch_m`.
4. Run the notebook again.

A copy in the aircraft folder that differs from its source is replaced (sha256). The CT/CP table cache key holds the sha256 of the design, so a changed blade with the same name makes new samples.

Limit: the `fit_prop` command line targets the FLUXER (22 in, 6.6 in, 2 blades, hub 0.025 m, hover 22.4 N). A prop of another size needs a new `Target` and a new setup function in `fit_prop.py`.

## Fixed-wing and multirotor models (`generate`)

| Item | Place |
|---|---|
| Sizing input | `work/aerosandbox/<aircraft>/athena_outputs.txt` (the printout of the Athena sizing scripts) |
| Model input | the ADH document, and the Proptimiser design and state file in `work/aerosandbox/<aircraft>/proptimiser/` |
| Settings | `settings/<aircraft>.yaml` (`currawong.yaml`, `redback.yaml`) |
| Writes (ingest) | node 1.2 `performance` (Discipline "sizing"), `muas.sources` |
| Writes (generate) | `work/aerosandbox/<aircraft>/asb/`: `report.md`, `results.json`, `three_view.png`, `airplane_3d.html`, `polar.csv`, `polar.png`, and `work/aerosandbox/<aircraft>/neutral_point.json` (the SpecSheet spoke reads it). No ADH data changes |

Run the model with `python -m aeroplan generate AeroSandbox currawong`.

| Part | Model | Source |
|---|---|---|
| Airframe | `asb.AeroBuildup` on the wing, tail, fuselage and tail boom of the ADH (settings `bodies`). Control surfaces split the sections at their ends | `FixedWingModel`, `component.surface_spec` |
| Propeller | Proptimiser BEMT (Nahon 2015, NeuralFoil sections) as constraints of the `asb.Opti` problem. Axial flow, `n_psi = 1` | `proptimiser.casadi_prop` |
| Motor and ESC | Drela first-order motor behind an ESC chopper: `d*V_bus = omega/(kappa*Kv) + R_tot*I`, `I = I0 + (Q + Q0)*Kv`, `I_bat = d*I` | Propalyser `estimate/chain.py`, constants in contract B `/motor` |
| Battery | Nominal voltage. No internal resistance (no sourced value) | contract B `/battery` |
| Mass | The mass model of node 1.2 (placeholder today) | ADH `muas.mass_properties` |

AeroSandbox 4.2.9 has `motor_electric_performance` (no kappa, no ESC) and an actuator-disc propeller with a fixed efficiency. The jobs do not use the actuator disc. At kappa = 1 and Q0 = 0 the chain gives the library motor (`tests/test_aerosandbox.py`).

| Job | What it does |
|---|---|
| `geometry` | Area, span and MAC of AeroSandbox against the ADH reference. Three-view and 3D view |
| `polar` | CL, CD and Cm of AeroBuildup against the flow5 aero model (DAVE-ML in the ADH) |
| `cruise_trim` | One Opti problem: level flight at the sizing cruise speed. Unknowns: alpha, elevator, shaft speed, duty. Gives power, chain efficiency, endurance |
| `static_check` | Full command at V = 0 against the Propalyser Ct/Cp table and shaft power. The alignment check |
| `neutral_point` | Vortex lattice neutral point plus the body term. Written to `neutral_point.json` |

`report.md` lists every placeholder that the results use. The SHA-256 of the Proptimiser files go in it.

Multirotor (settings `kind: multirotor`): the settings seed the aircraft (`aeroplan.multirotor`) and enable the jobs `multirotor_drag`, `emst_segments`, `emst_endurance` and `emst_sensitivity` (`MultirotorModel`, Bershadsky, Haviland, Johnson, AIAA 2016-0581, section III.A). Order: build, `generate AeroSandbox <aircraft>`, build. The output is `work/<aircraft>/asb/multirotor_results.json` and `report.md`. The EMST jobs need the Propalyser propulsion system.

Live propeller: the settings keys `proptimiser_design` and `proptimiser_compare` (a list) switch on the job `emst_live`. It solves hover and vertical climb with the Proptimiser BEMT (`static_and_axial`) in place of the CT/CP table. Each rotor has its own `Propeller`. The table result stays in the same file as the maker check. The design yaml and the state json of each design must be in `work/<aircraft>/proptimiser/designs/` and `.../propellers/`. Copy them by hand. Each BEMT call takes about 0.8 s, so the job runs for about 40 s.

## Known limits

- The propeller sees axial inflow V cos(alpha). The in-plane inflow is not in the model.
- A control surface section that the spoke inserts takes the foil of the inner section.
- AeroSandbox ignores the trailing edge point of a section. The spec carries the pitch incidence of a surface (`ry_deg`, the tail has -2.6 deg) in the section twist.
- AeroBuildup has no interference between components (no wing downwash on the tail) and the VLM has no fuselage.
- AeroBuildup and LiftingLine take the section lift from NeuralFoil. At Re 2e5 it gives the NACA 0012 tail a 2D slope of about 8 per rad near zero alpha, so these two methods give too much tail and too much static margin. Use the VLM for the neutral point (`docs/methods_report.md`).
- The tail boom (`tail_boom`) is a placeholder tube of the CREO spoke. It adds CD 0.0005 and almost no lift or moment.
- The sizing printout gives no units: see `UNITS` in `spoke.py` and `units_basis`.
- The Rosella model assumes a rigid clamp and a rigid wing for the boom frequency. The clamp and the wing are softer, so the real first mode is lower.
