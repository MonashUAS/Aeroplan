# Aerolink interface

What Aerolink reads, what it keeps, and what moved. Source: the Aerolink README and CLAUDE.md.

## Decisions

| Topic | Decision |
|---|---|
| `aircraft/*.h5` | A derived cache. Aerolink rebuilds it from the export package. It is never an input to AeroPlan. |
| flow5, CAD and config import | Move to AeroPlan adapters. Aerolink keeps its importers until each adapter works for all its inputs. |
| Hand config | YAML in AeroPlan and fleet-data. Aerolink still reads its own JSON until it reads the package. |
| Propulsion | Reaches Aerolink only through the package. No direct `.h5` copy. |
| MRP | The nominal-configuration CG, a fixed point. |
| Verification | The NESC F-16 case verifies the DAVE-ML to JSBSim compiler. It never judges MUAS data. |

## What Aerolink must read from the package

- `adh/aircraft.adh.json`: nodes with mass properties and installations.
- `dml/*.dml`: aero and propulsion tables (DAVE-ML 2.0, DTD-checked).
- `ic/initial_conditions.json`: rate frame, latitude type and attitude sequence are required fields.
- `reference.json`: frames, reference geometry, MRP, placeholder flags.
- `manifest.json`: hashes of every file, the package hash, `placeholder`, `known_limits`.

## What Aerolink must keep honest

- A `placeholder` flag in the package means the value is an estimate. Aerolink prints its warning for it, as today.
- Cl and Cn in the flow5 datasets have the flow5 sign. The compiler must apply the sign rule stated in the dataset.
- Aerolink's `daveml.py` evaluator and its check-cases are a candidate for the compiler tests. Not yet reviewed.

## Conflicts to remove later

| Conflict | State |
|---|---|
| Aerolink CLAUDE.md: "One source of truth: the aircraft file". | Out of date once AeroPlan is the SSOT. Aerolink owner must update it. |
| Aerolink CLAUDE.md: "No CI service". | Applies to Aerolink only. AeroPlan has CI. |
| Hand config is JSON in Aerolink. | Replace by the YAML from AeroPlan. |
| `h5map.py` and the propulsion spec are shared with Propalyser. | Do not change the layout without a change in both repos. |
