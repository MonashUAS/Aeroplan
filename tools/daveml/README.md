# DAVEML spoke

Published DAVE-ML 2.0 models (ANSI/AIAA S-119), for example the NASA F-16 model of the NESC check cases. Each file
becomes a dataset of an ADH item.

| Item | Place |
|---|---|
| Input | `work/daveml/<aircraft>/<file>.dml`. When a file is not there, the spoke downloads it from the settings URL and checks its sha256 |
| Settings | `settings/<aircraft>.yaml`: `source` (URL and the publication), `models` (file, member of the ZIP at the URL, sha256, role, name, WBS node, instance) |
| Writes | for each model: a dataset `<role>.<name>` (form `daveml-adh`, fidelity `REF`, units as in the file) on its node, the file as a linked asset (repo path and URL) |

The ingest stops when a file does not convert to the ADH form and back with no loss. `aeroplan check <aircraft>`
repeats that test when the file is on the machine. It also checks each model against the DAVE-ML 2.0 DTD and runs
every checkData static shot with the evaluator `aeroplan.daveml_eval`.

A published model keeps its own units (for example ft and lbf). Each variable names its units. The check cases of
the file use those units, so a conversion to SI would break them.

## The F-16 (`aircraft/f16/`)

| File | Role | ADH node |
|---|---|---|
| `F16_aero.dml` | aero | 1.2 AirVehicle |
| `F16_inertia.dml` | mass | 1.2 AirVehicle |
| `F16_prop.dml` | propulsion | 1.2.3.1 Engine |
| `F16_control.dml` | control | 1.2.4.2 FlightControlSubsystem |
| `F16_gnc.dml` | control | 1.2.5.10 AutomaticFlightControl |

Source: NASA/TM-2015-218675 (NESC-RP-12-00770), <https://nescacademy.nasa.gov/flightsim/2015>, archive
`Atmospheric_models.zip`, folder `F16_package/F16_S119_source`. The F-16 serves the `review` and `archive` profiles.
It has no propeller, servo map or ground contacts, so the `aerolink` profile refuses it.
