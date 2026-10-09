# flow5 spoke

Geometry, mass model, reference dimensions, aero model and trim speed from a flow5 sweep. Also writes a flow5 plane
from the SSOT.

| Item | Place |
|---|---|
| Input | `flow5/work/<aircraft>/sweeps/<sweep>/` (plane_with_body.xml, t7_reference.xml, t7_reference_opoint.txt, alpha_viscous.csv, results.json) and `flow5/work/<aircraft>/plane/*.dat` (foils) |
| Settings | `flow5/settings/<aircraft>.yaml`: the sweep to use, its date, the surface-to-node map, the mesh |
| Writes | lifting surfaces and planforms, the fuselage body, point masses, mass properties, reference, aero model (ADH DAVEfunc), initial conditions |
| Generate | `aeroplan generate flow5 <aircraft>` writes `work/<aircraft>/generated/<aircraft>.xml` and the foil files |

Procedure for a change:

1. `python -m aeroplan generate flow5 <aircraft>`.
2. Load the plane in flow5, change it, run the sweep (T7 stability point, alpha, viscous alpha, beta, control runs).
3. Copy the sweep folder into `work/<aircraft>/sweeps/`. Set `sweep` and `sweep_date` in the settings file.
4. `python -m aeroplan build <aircraft> --author "Your Name"`.

The changed file wins: the build writes the geometry of an item only when its flow5 files (plane XML, foils)
differ from the flow5 pointers on the item. A geometry change from OpenVSP stays until a new sweep.

Open: the sweep runner (it writes the flow5 script and the results.json validation) is not in AeroPlan yet.
