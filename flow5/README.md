# flow5 spoke

Geometry, mass model, reference dimensions, aero model and trim speed from a flow5 sweep. Also writes a flow5 plane
from the SSOT.

| Item | Place |
|---|---|
| Input | `flow5/work/<aircraft>/sweeps/<sweep>/` (plane_with_body.xml, t7_reference.xml, t7_reference_opoint.txt, alpha_viscous.csv, results.json) and `flow5/work/<aircraft>/plane/*.dat` (foils) |
| Settings | `flow5/settings/<aircraft>.yaml`: the sweep to use, its date, the surface-to-node map, the mesh |
| Writes | lifting surfaces and planforms, the fuselage body, point masses, mass properties, reference, aero model (ADH DAVEfunc), initial conditions |
| Sweep | `aeroplan sweep flow5 <aircraft>` runs flow5 and writes the sweep folder (`sweep.py`) |
| Generate | `aeroplan generate flow5 <aircraft>` writes `work/<aircraft>/generated/<aircraft>.xml` and the foil files |

Procedure for a change:

1. `python -m aeroplan sweep flow5 <aircraft>`. It writes the plane from the source tree, runs flow5 headless in two
   passes (T7 trim, then alpha, viscous alpha, beta and control runs at the trim) and writes
   `work/<aircraft>/sweeps/<aircraft>_<date>/` with `results.json`. About 11 minutes. The exit code is 1 when the
   validation fails.
2. Set `sweep` (and `sweep_date`) in the settings file to the new folder.
3. `python -m aeroplan build <aircraft> --author "Your Name"`.

The mass, CG, inertia and reference of the polars come from node 1.2 of the source tree (the SpecSheet mass model).
`--dry-run` writes the XML files into `work/<aircraft>/runs/<name>/` and starts no flow5. `--only <run> ...` runs a
part of the sweep. flow5 is found by `--flow5`, `FLOW5_EXE`, the settings `flow5_exe`, the PATH, then Program Files.
The runs, ranges and the `.fl5` project are in the `sweep_runner` block of the settings.

A manual run in the flow5 GUI stays possible: `aeroplan generate flow5 <aircraft>`, run the cases, copy the folder.

The changed file wins: the build writes the geometry of an item only when its flow5 files (plane XML, foils)
differ from the flow5 pointers on the item. A geometry change from OpenVSP stays until a new sweep.
