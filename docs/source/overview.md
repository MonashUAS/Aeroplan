# Overview

## What AeroPlan does

AeroPlan holds the aircraft data. Tools write data into it. Aerolink reads data out of it.

```
Proptimiser --> Propalyser --(system .h5)--> AeroPlan --(export package)--> Aerolink
flow5, CAD, hand config ---(adapters)------>    |                              |
                                                +<---(identified datasets)-----+
```

- **Proptimiser** designs propellers. It feeds Propalyser. It has no direct link to AeroPlan.
- **Propalyser** analyses stand runs and vendor data. It writes one `.h5` file for each propulsion system.
- **Adapters** in AeroPlan read raw tool files (flow5, CAD, hand config, Propalyser).
- **Export package**: an immutable folder with ADH JSON, DAVE-ML, a manifest and the initial conditions.
  `aeroplan package pack` wraps one folder into one `.h5` file for a hand copy.
- **Aerolink** builds JSBSim, linear models and SITL from the package. Its `aircraft/*.h5` is a derived cache.

## Principles (from ADH)

1. **ADH decides the design.** A MUAS extension exists only where ADH is silent or broken.
2. **Data stays apart from tools.** AeroPlan imports no code from Aerolink, Propalyser or Proptimiser.
3. **Same treatment for every item.** A propeller, a wing and a battery use the same node, dataset and uncertainty types.
4. **One place for an extension.** Each node keeps its upstream fields. MUAS additions sit under the key `muas`.
5. **No invented WBS number.** `adh_wbs_numbers()` reads the numbers from the ADH source.
6. **Pydantic validates.** Every model rejects an unknown key. The JSON Schema is exported for each version.

## Rules that save time

- Store SI. Angles are radians in the SSOT. Every quantity carries its units.
- Never write a value that no source gives. Use `unknown`, `placeholder` or `unverified`. Add the gap to [](currawong/missing_data.md).
- Every uncertainty has a status, a scope and a basis. See [](design/uncertainty.md).
- Copy data between repos by hand. No symbolic link. No path to another repo in any file.

## Layout of the repos

| Repo | Holds |
|---|---|
| `Aeroplan` | Software, schemas, docs, tests |
| `muas-fleet-data` | Raw files, hand config, generated datasets and nodes for each aircraft |
| `Aerolink` | Simulation. Reads the export package |

## Run the checks

```
python scripts/build_adh.py
set PYTHONPATH=src;packages/muas_adh/build/src
python -m pytest
```
