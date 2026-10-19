# Size a quadplane (the Rosella)

The sizing script `tools/aerosandbox/rosella.py` gives every number that you need to order the lift booms and the lift propulsion. It reads `tools/aerosandbox/settings/rosella.yaml`. Run it in the AeroSandbox Python. The decision is [ADR 22](../decisions/0022-quadplane-path.md).

## Before you start

1. Run `python -m aeroplan setup AeroSandbox --proptimiser <checkout>`. The checkout must have the geometric scale (Proptimiser 711ef86).
2. Copy the Proptimiser design `MAD_FLUXER_22x6_6` into `work/aerosandbox/redback/proptimiser/`. Copy `Currawong_V1` into `work/aerosandbox/currawong/proptimiser/`. Use the `designs` and `propellers` folders.
3. Open a shell in `tools/aerosandbox`. Use `.venv/Scripts/python` on Windows. Use `.venv/bin/python` elsewhere.

All results go to `work/aerosandbox/rosella/`. The script never writes the source tree.

## Commands

| Command | What it does |
|---|---|
| `rosella.py optimise` | Runs the ladder for each case. Writes `sizing/<config>_<S>S.json`, the order sheet and `sizing/best.json` |
| `rosella.py optimise --config H4 --cells 12` | Runs one case |
| `rosella.py ladder --config H4 --cells 12` | Runs the ladder for one case. Writes `ladder/<case>/L<k>.json` |
| `rosella.py ladder --from L3 --upto L4` | Starts at a later level. It reads the file of the level below |
| `rosella.py evaluate NAME` | Checks one manual configuration against every constraint |
| `rosella.py order-sheet --case H4_12S` | Prints the order sheet of one result. Without `--case` it uses `best.json` |
| `rosella.py rotor-check` | Compares the table, BEMT and momentum shaft power at 22.4 N hover thrust |

The `optimise` command takes `--upto L2` to stop at a lower level. It takes `--multistart N` for the random starts of L0 and L1. It takes `--time-limit` in seconds for each case. A full run of 10 cases takes several hours. Do not stop the run while it writes `sizing/`.

## Change a setting for one run

Use `--set` with the `optimise` and `ladder` commands. The YAML file does not change.

```
python rosella.py ladder --config H4 --cells 12 --set cruise_aero.map_speed_m_s=19
python rosella.py optimise --set control.hover_control_power.yaw_rad_s2=2.0
```

A number with a `value` key takes the new value. The result lists the change in `settings_changed`. The result also lists every placeholder in `placeholders`.

## Read the ladder report

The ladder prints one row for each level.

| Column | Meaning |
|---|---|
| status | `ok`, `acceptable` (IPOPT accepted a looser tolerance), `infeasible` or `failed` |
| M kg, E Wh | Take-off mass and mission energy |
| D in, kv | Rotor diameter and motor KV |
| worst 5 | The five constraints with the smallest margin. A margin is the fraction by which the constraint holds |

Follow these steps for each level.

1. Check the status. Each level starts from the result of the level below. The ladder stops at the first level that does not converge.
2. Read the gap between two levels in `gap_to_lower_level`. A large gap in energy means that the cheaper model was wrong.
3. Read `active` in the level file. It lists the constraints with a margin below 1e-3. These constraints set the design.
4. Read `cost_Wh_per_unit` of a constraint in the `constraints` block. It gives the energy that one unit of relaxation saves.

Every level first runs an elastic feasibility phase. The solver adds a slack to each inequality and minimises the sum. When the largest slack is above the tolerance, the status is `infeasible`. The report then lists `slack > 0` with the names. These are the constraints that you must relax. The result of `optimise` is the result of the highest level that converged. The field `level_reached` names it.

## Check your own parts

1. Open `notebooks/04_rosella_sizing.ipynb` in the kernel `aeroplan-asb`. Run the cells down to the manual window.
2. Type the motor, propeller, ESC, battery and boom data. Press **Evaluate**. The window shows pass or fail and a margin for each constraint.
3. Press **Re-optimise booms** to size the booms for your parts.
4. Press **Save** and type a name. The notebook writes a block to `settings/rosella.manual.json`.
5. Run `rosella.py evaluate NAME` to repeat the check on the command line. Add `--level L2` for a faster check.

The notebook also shows the three views, the mass breakdown, the CG and static margin, the inertia, the energy of each segment, the H4 and H8 table, the boom margins with the 1P band, and the control authority. It writes plots to `work/aerosandbox/rosella/lab/`.

## Build the aircraft

The AeroSandbox spoke reads the result named by `build_from` in the settings. The value is `optimised` or a name in `rosella.manual.json`.

```
python -m aeroplan build rosella --new --author "Your Name" --consumers review archive
python -m aeroplan check rosella
python -m aeroplan pack rosella --profile review archive
```

The spoke writes the booms as subcomponents of 1.2.2, the lift propellers at 1.2.3.9, the point masses and the sizing outputs. Every estimate carries `placeholder: true` and names its source. Aerolink waits for a quadplane contract, so do not pack the `aerolink` profile.
