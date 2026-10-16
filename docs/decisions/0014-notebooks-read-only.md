# 14. Notebooks run in the AeroSandbox Python and never write the source tree

Date: 2026-10-15

Status: accepted

## Context

Analysis needs aerosandbox and aeroplan in one Python.

## Decision

Notebooks in `tools/aerosandbox/notebooks/` run in `tools/aerosandbox/.venv` (kernel `aeroplan-asb`). They may import aerosandbox and aeroplan (`lab.py`). They read the source tree and never write it. They are committed with empty outputs. Proptimiser is optional in that Python.

## Consequences

Plots go to `work/aerosandbox/<aircraft>/lab/`.
