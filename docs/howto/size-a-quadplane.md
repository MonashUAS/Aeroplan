# Size a quadplane (the Rosella)

The notebook [rosella_sizing.ipynb](../../tools/aerosandbox/notebooks/rosella_sizing.ipynb) gives every number that you need to order the lift booms and the lift propulsion. It builds the model from components, runs the fidelity ladder and saves the model to `tools/aerosandbox/settings/rosella.json`. The decisions are [ADR 22](../decisions/0022-quadplane-path.md) and [ADR 24](../decisions/0024-aircraft-models-in-code.md).

## Before you start

1. Run `python -m aeroplan setup AeroSandbox --proptimiser <checkout>`. The checkout must have the geometric scale (Proptimiser 711ef86).
2. Copy the Proptimiser design `MAD_FLUXER_22x6_6` into `work/aerosandbox/redback/proptimiser/`. Copy `Currawong_V1` into `work/aerosandbox/currawong/proptimiser/`. Use the `designs` and `propellers` folders.
3. Open `tools/aerosandbox/notebooks/rosella_sizing.ipynb` in the kernel "AeroPlan AeroSandbox".

The notebook writes to `work/aerosandbox/rosella/` and to `settings/rosella.json`. It never writes the source tree.

## Run the study

1. Run the cells of section 2. They make the components. Each number has units and a source. A `placeholder=True` number is a stand-in.
2. Run section 3. `model.fix(...)` fixes the bought tube. Free params are the design variables.
3. Run section 4 (about 2 minutes). The ladder prints one row for each level.
4. Read sections 5 to 9: the design, the limits that set it, the mass and energy, the blade check and the boom vibration.
5. Run section 10 (checks) and section 11 (save).

## Change the question

| You want | Do this |
|---|---|
| Another tube | Change `bought_tube` and the `model.fix(boom__r_o=..., boom__t=...)` line |
| Another motor, ESC, battery or propeller | Give the bought value to the param: `motor["mass_kg"]`, `rm_ohm` and `i0_A`; `esc["mass_kg"]` and `current_A`; `battery["mass_kg"]`; `rotor["mass_kg"]` and `pitch_m`. A value replaces the fit |
| H8 or another cell count | `QuadplaneModel(..., layout="H8")`, `battery["cells_s"]` |
| Fix a design variable | `model.fix(motor__kv=150.0)` |
| Free a design variable again | `model.free("motor.kv", lo=60, hi=450)` |
| Another limit | Change the param, for example `model.c["boom"]["resonance_margin"] = 0.3` |
| Another study (fix the propulsion, optimise the wing) | Make a new notebook. Free the params that the model class can free (`model.DESIGN_VARS`). A new design variable needs a change in the model class |

## Read the ladder report

The ladder prints one row for each level.

| Column | Meaning |
|---|---|
| status | `ok`, `acceptable` (IPOPT accepted a looser tolerance), `infeasible` or `failed` |
| M kg, E Wh | Take-off mass and mission energy |
| D mm, kv | Rotor diameter and motor KV |
| worst 5 | The five constraints with the smallest margin. A margin is the fraction by which the constraint holds |

1. Check the status. Each level starts from the result of the level below. The ladder stops at the first level that does not converge.
2. Read `gap_to_lower_level` in the level file. A large gap in energy means that the cheaper model was wrong.
3. Read `result.active()`. It lists the constraints with a margin below 1e-3. These constraints set the design.
4. Read `cost_Wh_per_unit` of a constraint (`result.constraints`). It gives the energy that one unit of relaxation saves.

Every level first runs an elastic feasibility phase. The solver adds a slack to each inequality and minimises the sum. When the largest slack is above the tolerance, the status is `infeasible`. The row then lists `slack > 0` with the names. These are the constraints that you must relax.

## Check your own parts

1. Run the last cell of the notebook: `Window(model, "L1").show()`.
2. Type the motor, propeller, ESC, battery and boom values in the rows. The 3D view moves.
3. Press **Evaluate**. The window shows the margin of each limit and the limits that break.
4. Mark the params that must change as **free**. Press **Optimise**. The window redraws the booms and rotors at each solver iteration.
5. Press **Adopt result** to take the solved values into the rows. Press **Save** to write `settings/rosella.json`.

## Build the aircraft

```
python -m aeroplan build rosella --author "Your Name"
python -m aeroplan check rosella
python -m aeroplan pack rosella --profile review archive
```

The spoke reads `settings/rosella.json`. It writes the booms as subcomponents of 1.2.2 (with `muas.tube.material_data`), the lift propellers at 1.2.3.9, the point masses, the sizing outputs and the limits as `muas.target` requirements of node 1.2. Every estimate carries `placeholder: true` and names its source. Aerolink waits for a quadplane contract, so do not pack the `aerolink` profile.
