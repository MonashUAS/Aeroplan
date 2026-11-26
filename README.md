# AeroPlan

AeroPlan keeps each aircraft as a source tree in git: `aircraft/<aircraft>/`. This tree is the single source of truth
(SSOT). It is one [Aircraft Data Hierarchy](https://github.com/Boeing/aircraft-data-hierarchy) (ADH) document, with one JSON
file for each ADH node and one for each dataset. `aeroplan pack` makes a `.muas` package from it: a ZIP archive that holds one
immutable, hashed snapshot of the aircraft. Each tool has a **spoke** in `aeroplan/<tool>/` that moves data between the tool
and the source tree.

```
 aeroplan/<tool>/  aerosandbox  flow5  specsheet  propalyser  creo  openvsp  daveml  ardupilot
                        |         |        |           |        |      |        |        |
                        +---------+--------+-----------+--------+------+--------+--------+
                                                       |  aeroplan build
                                                       v
                                         aircraft/currawong/   (ADH source tree, committed)
                                                       |  aeroplan pack --profile aerolink
                                                       v
                                dist/currawong-<version>-aerolink.muas  ->  Aerolink  ->  fly
```

| Folder | What it holds |
|---|---|
| `aircraft/` | The source tree of each aircraft (the SSOT): one `<wbs>.<key>.json` for each node, and `datasets/` |
| `aeroplan/` | The package: the core code, and one subpackage for each tool (`aeroplan/<tool>/`) |
| `standards/` | `adh/` (the ADH copy, its patches and the extension register), `schema/` (JSON Schema), `spec/` (DAVE-ML DTDs) |
| `docs/` | Tutorials, how-to guides, reference, explanation, decisions |
| `tests/` | Tests (synthetic numbers only) |
| `work/` | Raw tool files, `work/<tool>/<aircraft>/` (git ignores it) |
| `dist/` | Packages (git ignores it) |

## ADH first

AeroPlan uses the Boeing ADH as it is. It adds a MUAS extension under the key `muas` only where ADH has no field. Each fact
is stored once: when ADH has the field, the value goes there. [standards/adh/EXTENSIONS.md](standards/adh/EXTENSIONS.md)
gives the reason for each `muas` key, and [standards/README.md](standards/README.md) lists the ADH patches and the known
faults of upstream.

## Start

One Python, the repository `.venv`, runs everything but OpenVSP ([ADR 30](docs/decisions/0030-one-python-for-aeroplan-and-aerosandbox.md)):

```
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[all]"
python -m aeroplan doctor
```

You need Python 3.12 or newer. `.[all]` installs Proptimiser from a private repository, so git needs a sign-in with read
access. With no access, use `pip install -e ".[sizing,dev]"` ([First day](docs/tutorials/first-day.md)).

Start here: [First day](docs/tutorials/first-day.md). All documents: [docs/](docs/README.md). Reports and notebooks of each
aircraft: [By aircraft](docs/README.md#by-aircraft). Rosella sizing study:
[rosella_sizing.ipynb](aeroplan/aerosandbox/notebooks/rosella_sizing.ipynb). Rules and code map for contributors:
[CLAUDE.md](CLAUDE.md). Decisions: [docs/decisions](docs/decisions/README.md).
