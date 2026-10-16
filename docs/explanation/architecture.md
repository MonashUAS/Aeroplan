# Architecture

AeroPlan keeps each aircraft as a source tree in git: `aircraft/<aircraft>/`. This tree is the single source of truth (SSOT). It holds one [Aircraft Data Hierarchy](https://github.com/Boeing/aircraft-data-hierarchy) (ADH) document, one JSON file for each ADH node, and one JSON file for each dataset.

```
 tools/  aerosandbox  flow5  specsheet  propalyser  creo  openvsp  daveml  ardupilot
            |           |        |           |        |      |        |        |
            +-----------+--------+-----+-----+--------+------+--------+--------+
                                       |  aeroplan build
                                       v
                        aircraft/currawong/   (ADH source tree, committed)
                                       |  aeroplan pack --profile aerolink
                                       v
                 dist/currawong-<version>-aerolink.muas  ->  Aerolink  ->  fly
```

Why this shape:

- ADH decides the design. A MUAS extension is added only where ADH is silent or broken, under the `muas` key. The patched upstream is built in `standards/adh/build/` from the pristine copy and the patch series.
- Each tool has a spoke. A tool member works in the tool, then runs `aeroplan build`. AeroPlan reads the tool output, checks it and writes the source tree. A failed check writes nothing.
- Raw tool files do not go into git. They stay in `work/<tool>/<aircraft>/`. The asset register names them with a hash, so a package can say which file a value came from, and a fetch can check it.
- A package is a snapshot. It is built from the source tree, never edited, and the same tree gives the same bytes.
- Units are SI. Angles are radians in the ADH data. A published reference model (DAVE-ML) keeps its own units.
- The mass reference point (MRP) is the nominal-configuration CG, a fixed point in the design frame.
- A stand-in value carries `placeholder: true` and names its source. No unsourced number is typed.
- Tests use synthetic numbers only. `tests/test_aircraft_files.py` runs every check, the pack and the unpack on each committed source tree.
- Copy data by hand between repositories. No symlinks. No hard-coded cross-repository paths. AeroPlan imports no sibling repository.

The decisions and their dates are in [the decision records](../decisions/README.md).

Open items (state of 2026-10-17):

- The flow5 sweep runner is not in AeroPlan yet. A member runs the sweep in flow5 by hand.
- Currawong: the mass CG moved 22 mm forward of the MRP. A new flow5 sweep is needed. Until then the datum check warns and `aerolink` is not a consumer (ADR 0012).
- flow5 and AeroSandbox disagree on the lift slope and the neutral point. See `tools/aerosandbox/docs/methods_report.md`.
- Redback: the propulsion system file does not exist yet, so the aircraft has no propulsion dataset and no `aerolink` consumer. The flight log and parameter file are in `work/ardupilot/redback/`. Fill the `FILL_IN` values in `tools/ardupilot/settings/redback.yaml`.
- The ArduPilot spoke does not decode the log yet.
- No dataset has a sigma yet.
