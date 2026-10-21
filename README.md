# AeroPlan

AeroPlan keeps each aircraft as a source tree in git: `aircraft/<aircraft>/`. This tree is the single source of truth
(SSOT): one [Aircraft Data Hierarchy](https://github.com/Boeing/aircraft-data-hierarchy) (ADH) document, one JSON file
for each ADH node and one for each dataset. `aeroplan pack` makes a `.muas` package from it: a ZIP archive that holds one
immutable, hashed snapshot of the aircraft. Each tool has a **spoke** in `tools/` that moves data between the tool and
the source tree.

```
   tools/  aerosandbox  flow5  specsheet  propalyser  creo  openvsp  daveml  ardupilot
              |           |        |          |         |      |       |        |
              +-----------+--------+----+-----+---------+------+-------+--------+
                                        |  aeroplan build
                                        v
                         aircraft/currawong/   (ADH source tree, committed)
                                        |  aeroplan pack --profile aerolink
                                        v
                  dist/currawong-<version>-aerolink.muas  ->  Aerolink  ->  fly
```

| Folder | What it holds |
|---|---|
| `aircraft/` | Source tree of each aircraft (the SSOT) |
| `tools/` | One spoke for each tool |
| `standards/` | `adh/` (ADH fork), `schema/` (JSON Schema), `spec/` (DAVE-ML DTDs) |
| `src/aeroplan/` | The core code |
| `docs/` | Tutorials, how-to guides, reference, explanation, decisions |
| `tests/` | Tests (synthetic numbers only) |
| `work/` | Raw tool files, `work/<tool>/<aircraft>/` (git ignores it) |
| `dist/` | Packages (git ignores it) |

Start here: [First day](docs/tutorials/first-day.md). All documents: [docs/](docs/README.md). Reports and notebooks of each aircraft: [By aircraft](docs/README.md#by-aircraft). Rosella sizing study: [rosella_sizing.ipynb](tools/aerosandbox/notebooks/rosella_sizing.ipynb). Rules and code map for
contributors: [CLAUDE.md](CLAUDE.md). Decisions: [docs/decisions](docs/decisions/README.md).
