# Prototype spoke

The published specs of the team Prototype project (meetprototype.com) to ADH sizing targets, and a first propulsion sizing from the MTOW.

| Item | Place |
|---|---|
| Input | `work/prototype/<aircraft>/specs.json`: the answer of `GET /api/v1/projects/<project>/specs` |
| Download | `python -m aeroplan generate Prototype <aircraft>` (needs `PROTOTYPE_TOKEN`, scope `specs:read`) |
| Settings | `tools/prototype/settings/<aircraft>.yaml`: project, spec slug -> target, `mtow_spec`, `propulsion_sizing` |
| Writes | Node 1.2: one sizing `Requirement` for each mapped spec. Node 1.2.3: the propulsion targets. `muas.sources` of 1.2 |
| Code | `tools/prototype/spoke.py` (the spoke), `src/aeroplan/propulsion_sizing.py` (the method, no I/O) |

The Prototype API is read only for specs. A person publishes a spec in the app. The spoke never writes to Prototype.

## Workflow: from an MTOW target to a propulsion specification

1. A lead publishes the spec `mtow` (kg) in Prototype.
2. Copy `settings/quadplane.yaml` to `settings/<aircraft>.yaml` and set the project slug, the spec slugs and the assumptions.
3. `export PROTOTYPE_TOKEN=ptk_live_...` (PowerShell: `$env:PROTOTYPE_TOKEN = "ptk_live_..."`), then
   `python -m aeroplan generate Prototype <aircraft>`. Or save the API answer by hand as `work/<aircraft>/specs.json`.
4. `python -m aeroplan build <aircraft> --author "Your Name" --only Prototype --dry-run` shows the numbers. Drop
   `--dry-run` to write them. For a new aircraft add `--new`.
5. Read the targets: `python -m aeroplan show <aircraft>`. They are the specification for the motor, ESC, propeller and battery.
6. Choose the parts. Run the Propalyser and AeroSandbox spokes on the chosen system, and compare with the targets.
7. A new MTOW: publish it in Prototype, repeat from step 3. The old targets are replaced.

## What the sizing does

Momentum theory, one pass (`propulsion_sizing.py` has the formulas). From the MTOW and the assumptions it gives:

| Target (node 1.2.3) | Bound | Use |
|---|---|---|
| `lift_motor_thrust_peak` (N) | min | Thrust each lift motor and propeller must give |
| `lift_rotor_diameter` (m) | target | From the disc loading |
| `lift_motor_power_peak` (W) | min | Electrical power of each lift motor and ESC |
| `hover_power_total` (W) | target | All lift motors in hover at MTOW |
| `cruise_thrust` (N), `cruise_power` (W) | target | Cruise propeller and motor |
| `battery_energy` (W*h), `battery_mass` (kg) | min, target | Pack size and its share of the MTOW |

Every assumption is a stand-in until `propulsion_sizing.confirmed: true`. Until then the targets carry
`placeholder: true`. The pack mass is not yet added to the MTOW: if it makes the MTOW too high, lower the energy or raise the
MTOW in Prototype.

## What it does not do

- It does not choose a motor or a propeller. The targets are the input of that choice.
- It does not write a spec back to Prototype. A derived value that differs from a published spec is a proposal for a
  person to publish. Not built yet.
- The source of every owned requirement starts with "Prototype". A later ingest replaces those and keeps all others.
