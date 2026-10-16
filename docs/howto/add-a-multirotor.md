# Add a multirotor (the Redback)

A multirotor starts from the AeroSandbox settings (`tools/aerosandbox/settings/<aircraft>.yaml` with `kind: multirotor`),
not from a sizing printout. The settings hold the CAD arm (distance and direction angles), the Quad X motor pattern and
the demo sizes.

1. `python -m aeroplan build redback --new --author "Your Name" --consumers review archive` seeds the rotors, the motor
   outputs, the reference data, the ground contacts and the demo shapes, and rolls up the mass from the weight CSV
   (`tools/specsheet/sheets/redback/`). The Propalyser and ArduPilot spokes skip with a note until their files exist.
2. `python -m aeroplan generate AeroSandbox redback` runs the body drag and (with a propulsion system) the EMST jobs.
3. `python -m aeroplan build redback --author "Your Name"` writes the body-drag aero dataset and the `sizing` record.
4. Copy `redback_mk4.v2.h5` into `work/propalyser/redback/` by hand, then repeat steps 2 and 3, then add `aerolink` with
   `--consumers aerolink review archive`.
5. Put the flight log (`.BIN`) and the parameter file in `work/ardupilot/redback/`. Fill the `FILL_IN` values of
   `tools/ardupilot/settings/redback.yaml`. Build again.

The contract for Aerolink is [the multirotor contract](../reference/multirotor_contract.md).
