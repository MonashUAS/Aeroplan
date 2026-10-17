# Commands

```
pip install -e .[test]
python -m pytest
```

| Command | What it does |
|---|---|
| `aeroplan build <aircraft> --author NAME` | Runs the spokes with input, checks, writes `aircraft/<aircraft>/` (`--new`, `--consumers`, `--only`, `--dry-run`) |
| `aeroplan check <aircraft>` | Every check: ADH tree, dataset hashes, DAVE-ML (DTD, round trip, checkData), datums, consumers |
| `aeroplan show <aircraft>` | Prints the ADH tree and the asset register (`--placeholders`: the stand-in values) |
| `aeroplan show <aircraft> --md <file>` | Writes the one-page summary. Use `docs/reference/aircraft/<aircraft>.md` |
| `aeroplan pack <aircraft> --profile P ...` | Writes `dist/<aircraft>-<version>-<P>.muas` |
| `aeroplan unpack <file> <folder>` | Checks a package and writes its source tree |
| `aeroplan verify <file>` | Checks a package: mimetype, every hash, the package hash |
| `aeroplan generate <spoke> <aircraft>` | Writes the tool input files from the source tree (flow5, OpenVSP, AeroSandbox) |
| `aeroplan sweep flow5 <aircraft>` | flow5 headless: T7, alpha, beta, controls (about 11 minutes) |
| `aeroplan sweep OpenVSP <aircraft>` | CompGeom, parasite drag, VSPAERO (about 15 minutes after generate) |
| `aeroplan export <spoke> <aircraft> <out>` | Writes the tool files of a spoke (Aerolink: the `aerolink` package. ArduPilot: `.parm`, `.waypoints`, `.poly`) |
| `aeroplan spokes <aircraft>` | Lists the spokes and the files in their work folders |
| `aeroplan setup OpenVSP` | Makes the OpenVSP Python on this machine (`--vsp <folder>` when it does not find OpenVSP) |
| `aeroplan setup AeroSandbox` | Makes the AeroSandbox Python (`--proptimiser <checkout>`, or the git source in the settings) |
| `rosella.py optimise\|ladder\|evaluate\|order-sheet\|rotor-check` | Quadplane sizing in `tools/aerosandbox` (AeroSandbox Python). See [Size a quadplane](../howto/size-a-quadplane.md) |
| `aeroplan schema --out standards/schema` | Exports the JSON Schema of the MUAS types. Run it after a model change |

Examples:

```
python -m aeroplan build currawong --author "Liam M." --consumers review archive   # after a sheet change
python -m aeroplan build redback --new --author "Liam M." --consumers review archive
python -m aeroplan build f16 --author "Liam M."     # the NASA F-16 (DAVEML spoke, downloads when needed)
python -m aeroplan pack currawong --profile aerolink review archive
tools/aerosandbox/.venv/bin/python tools/aerosandbox/rosella.py optimise --config H4 --cells 12   # Rosella sizing (Scripts/python.exe on Windows)
tools/aerosandbox/.venv/bin/jupyter lab tools/aerosandbox/notebooks   # the notebooks (Scripts/jupyter.exe on Windows). Setup installs the kernel in the user folder.
```

Profiles: `aerolink`, `review`, `flight-record`, `archive`.
