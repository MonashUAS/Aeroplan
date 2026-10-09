# Propalyser spoke

The propulsion system that flies: Ct/Cp table, throttle map, propeller diameter, blades and inertia.

| Item | Place |
|---|---|
| Input | `Propalyser/work/<aircraft>/<system>.v2.h5` (contract B, `propulsion-system` version 2), copied by hand from Propalyser |
| Settings | `Propalyser/settings/<aircraft>.yaml`: `system` (the system that flies), `instance` (the propeller node) |
| Writes | node 1.2.3.9 `muas.propulsion_system`, and the installation diameter |

The spoke reads the file with h5py only. It refuses another schema or version, and a `units` attribute that is not
a pint spelling.
