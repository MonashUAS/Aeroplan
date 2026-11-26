---
id: "0030"
title: One Python for AeroPlan and AeroSandbox
date: 2026-11-26
status: accepted
kind: architecture
supersedes: ["0010"]
amends: ["0024", "0025"]
applies_to: ["pyproject.toml", "aeroplan/aerosandbox/**", "docs/tutorials/**", "README.md"]
---
# 30. One Python for AeroPlan and AeroSandbox

## Context

ADR 0010 put AeroSandbox and Proptimiser in a second Python, `aeroplan/aerosandbox/.venv`, because they need packages that
AeroPlan does not need. A new user had to run `aeroplan setup AeroSandbox`, register a Jupyter kernel, and pick that kernel.
On a Linux laptop, a fresh clone that followed `first-day.md` could not run the sizing notebook: Jupyter was not in the main
Python, the notebook text named another kernel, and `pip install uv` failed on a system Python (PEP 668).

The AeroSandbox Python already held `aeroplan` (editable) and every core dependency next to aerosandbox 4.2.9, casadi and
Jupyter. The two sets of packages do not conflict.

## Decision

- One Python, the repository `.venv`, runs AeroPlan, the AeroSandbox model files and the notebooks.
- `pyproject.toml` has the extras `sizing` (AeroSandbox, Jupyter, plots), `prop` (Proptimiser), `dev` (the checks) and
  `all`. `prop` is separate because the Proptimiser repository is private and needs Python 3.12.
- The install is: make `.venv`, activate it, `pip install -e ".[all]"`, then `python -m aeroplan doctor`.
- The AeroSandbox spoke runs its jobs in the same Python when aerosandbox imports. Else it uses the old tool Python if it
  exists. Else it stops with the install line.
- OpenVSP keeps its own Python (ADR 0011): its compiled module fixes the Python version.

## Consequences

`aeroplan setup AeroSandbox` prints the install line and does nothing else. The notebook kernel is `python3` of the `.venv`.
The sizing tests run in CI, not skip. Proptimiser must come from a pushed commit,
because pip installs it from git. A user with no access installs `.[sizing,dev]`. CI installs `prop` only when the
secret `PROPTIMISER_TOKEN` exists.

## Rules

- process: A notebook uses the python3 kernel of the `.venv`. Check AP017 of ADR 0024 tests it.
- ci: The `fresh-clone` CI job runs the install of `docs/tutorials/first-day.md` on Linux, then `aeroplan doctor`.
- process: A new runtime dependency goes in an extra of `pyproject.toml`, never in a setup command.
