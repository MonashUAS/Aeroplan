# AeroSandbox spoke

Two jobs: the initial sizing (`ingest`) and the AeroSandbox model of the aircraft with its propulsion chain (`generate`).

| Item | Place |
|---|---|
| Sizing input | `AeroSandbox/work/<aircraft>/athena_outputs.txt` (the printout of the Athena sizing scripts) |
| Model input | the ADH document, and the Proptimiser design and state file in `AeroSandbox/work/<aircraft>/proptimiser/{designs,propellers}/` (copy by hand) |
| Settings | `AeroSandbox/settings/<aircraft>.yaml` |
| Writes (ingest) | node 1.2 `performance` (Discipline "sizing"), `muas.sources` |
| Writes (generate) | `AeroSandbox/work/<aircraft>/asb/`: `report.md`, `results.json`, `three_view.png`, `airplane_3d.html`, `polar.csv`, `polar.png`. No ADH data changes |

## Set up (once for each computer)

```
python -m aeroplan setup AeroSandbox --proptimiser <Proptimiser checkout>
python -m aeroplan setup AeroSandbox            # installs Proptimiser from proptimiser_git in the settings
```

This makes `AeroSandbox/.venv` (Python 3.12, uv). It holds aerosandbox, casadi and Proptimiser. It holds no JAX: the
CasADi path of Proptimiser does not need it. The spoke sends each job to `asb_worker.py` in that Python. Only the
worker imports aerosandbox and proptimiser. Run the model with `python -m aeroplan generate AeroSandbox currawong`.

## The model

The three propulsion models of the team now use one set of equations.

| Part | Model in the AeroSandbox worker | Source |
|---|---|---|
| Airframe | `asb.AeroBuildup` on the wing, tail, fuselage and tail boom of the ADH (settings `bodies`). Control surfaces split the sections at their ends | `spec.py` |
| Propeller | Proptimiser BEMT (Nahon 2015, NeuralFoil sections) as constraints of the `asb.Opti` problem. Axial flow, `n_psi = 1` | `proptimiser.casadi_prop` |
| Motor and ESC | Drela first-order motor behind an ESC chopper: `d*V_bus = omega/(kappa*Kv) + R_tot*I`, `I = I0 + (Q + Q0)*Kv`, `I_bat = d*I` | Propalyser `estimate/chain.py`, constants in contract B `/motor` |
| Battery | Nominal voltage. No internal resistance (no sourced value) | contract B `/battery` |
| Mass | The mass model of node 1.2 (placeholder today) | ADH `muas.mass_properties` |

AeroSandbox 4.2.9 has `motor_electric_performance` (no kappa, no ESC) and an actuator-disc propeller with a fixed
efficiency. The worker does not use the actuator disc. At kappa = 1 and Q0 = 0 the chain gives the library motor
(`tests/test_aerosandbox.py`).

## Jobs

| Job | What it does |
|---|---|
| `geometry` | Area, span and MAC of AeroSandbox against the ADH reference. Three-view and 3D view |
| `polar` | CL, CD and Cm of AeroBuildup against the flow5 aero model (DAVE-ML in the ADH) |
| `cruise_trim` | One Opti problem: level flight at the sizing cruise speed. Unknowns: alpha, elevator, shaft speed, duty. Gives power, chain efficiency, endurance |
| `static_check` | Full command at V = 0 against the Propalyser Ct/Cp table and shaft power. The alignment check |

`report.md` lists every placeholder that the results use. The SHA-256 of the Proptimiser files go in it.

## Notebooks

`AeroSandbox/notebooks/` holds the notebooks. They use `AeroSandbox/lab.py`. They read the source tree and write nothing
to it (plots go to `work/<aircraft>/lab/`). They are committed with empty outputs (a test enforces it).

```
python -m aeroplan setup AeroSandbox                         # once: Python, JupyterLab, kernel "AeroPlan AeroSandbox"
AeroSandbox/.venv/bin/jupyter lab AeroSandbox/notebooks      # or pick the kernel in VS Code
```

| Notebook | What it shows |
|---|---|
| `01_geometry_and_mass.ipynb` | Three-view, 3D view with the point masses, top view with the CG and MRP, mass by subassembly and source, inertia against flow5 T7, static margin of each configuration |
| `02_flow5_vs_aerosandbox.ipynb` | The gap ladder: inputs, slopes at the T7 point (VLM, AeroBuildup, flow5), what flow5 implies for wing and tail, sections (NeuralFoil), trim, drag build-up, power budget |
| `03_gap_study.ipynb` | The causes of the gap: method matrix (VLM mesh and wake, LiftingLine, NonlinearLiftingLine, AeroBuildup, with and without the boom), downwash at the tail against DATCOM, the tail alone against lifting-line theory, neutral point build-up, drag at the same CL. The numbers of `docs/methods_report.md` |

`lab.load()` gives the airplane, the spec, the point masses, the flow5 DAVE-ML model and the mass configurations. The notebooks do
not need Proptimiser. Proptimiser is optional in the venv: without it `cruise_trim` and `static_check` say what is missing.

## Known limits

- The propeller sees axial inflow V cos(alpha). The in-plane inflow is not in the model.
- A control surface section that the spoke inserts takes the foil of the inner section.
- AeroSandbox ignores the trailing edge point of a section. The spec carries the pitch incidence of a surface (`ry_deg`, the
  tail has -2.6 deg) in the section twist (before 2026-10-15 it was lost).
- AeroBuildup has no interference between components (no wing downwash on the tail) and the VLM has no fuselage.
- AeroBuildup and LiftingLine take the section lift from NeuralFoil. At Re 2e5 it gives the NACA 0012 tail a 2D slope
  of about 8 per rad near zero alpha, so these two methods give too much tail and too much static margin. Use the VLM
  for the neutral point (`docs/methods_report.md`).
- The tail boom (`tail_boom`) is a placeholder tube of the CREO spoke. It adds CD 0.0005 and almost no lift or moment.
- The sizing printout gives no units: see `UNITS` in `spoke.py` and `units_basis`.

## Multirotor mode

Settings `kind: multirotor` seed the aircraft (aeroplan.multirotor) and enable the jobs multirotor_drag, emst_segments, emst_endurance and emst_sensitivity (Bershadsky, Haviland, Johnson, AIAA 2016-0581, section III.A). Order: build, `generate AeroSandbox <aircraft>`, build. Output: `work/<aircraft>/asb/multirotor_results.json` and `report.md`. The EMST jobs need the Propalyser propulsion system.
