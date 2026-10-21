# 24. Aircraft models are made in code, saved in one JSON file, and shown in evaluated notebooks

Date: 2026-10-21

Status: accepted

## Context

The Rosella sizing was one script of 1700 lines (`rosella.py`). Its settings were in a YAML file and a second machine file. The notebooks had no outputs (the old ADR 14), so a reader on GitHub saw no result. A change of the question, for example "fix the propulsion and optimise the wing", needed a change in the script.

## Decision

- A model is made from components in `tools/aerosandbox/component.py`. A component is a set of params. A param has a value, units, a source, a `placeholder` flag, and the settings of the optimiser: free or fixed, bounds and scale. A free param is a design variable. A fixed param is a parameter of the problem. Components are made in code, in a notebook.
- `model.py` has one class for each class of aircraft: `QuadplaneModel`, `FixedWingModel` and `MultirotorModel`. A model evaluates one flight condition, as the Proptimiser `PropellerModel` does. It calls the level functions of `component.py` (`rotor_model`, `airframe_model`, `motor_model`). A level function gives a model of lower or higher fidelity.
- `optimise.py` makes one `asb.Opti` problem from a model and runs the fidelity ladder (L0 to L4). `result.py` holds the result and a snapshot of one iterate. `plot.py` and `window.py` read results and snapshots. The solver does not draw and the plot does not solve.
- One JSON file for each aircraft, `tools/aerosandbox/settings/<aircraft>.json`, holds the components and the last result. The spoke reads it into the source tree (ADR 8). `currawong.yaml` and `redback.yaml` stay as the settings of the spoke.
- The limits of the model go into the tree as `muas.target` requirements of node 1.2 (category sizing). The material of a tube goes into `muas.tube.material_data`. ADH has no material model.
- Notebooks run in `tools/aerosandbox/.venv` and never write the source tree. They are committed with their outputs, so GitHub shows the study. A widget state does not stay in the file. A notebook is smaller than 5 MB (a test checks it).
- This decision replaces ADR 14, which is removed.

## Consequences

`rosella.py`, `asb_worker.py`, `spec.py`, `lab.py`, `runner.py`, `fast_bemt.py`, `neutral_point.py` and `jung2021.py` are removed. The notebooks `01` to `04` are in `tools/aerosandbox/notebooks/deprecated/`. They run only on commit 3851d80. The Rosella sizing is `tools/aerosandbox/notebooks/rosella_sizing.ipynb`.

A later study makes a new notebook. It builds the model, fixes some params, frees others, and runs the ladder. It needs no change in the solver. A new design variable needs a change in the model class, because the model decides which params it can free (`model.DESIGN_VARS`).
