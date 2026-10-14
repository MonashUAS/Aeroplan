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
| Airframe | `asb.AeroBuildup` on the wing, tail and fuselage of the ADH. Control surfaces split the sections at their ends | `spec.py` |
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

## Known limits

- The propeller sees axial inflow V cos(alpha). The in-plane inflow is not in the model.
- A control surface section that the spoke inserts takes the foil of the inner section.
- The ADH fuselage ends before the tail (no boom), so the body drag is the drag of that shape.
- The sizing printout gives no units: see `UNITS` in `spoke.py` and `units_basis`.
