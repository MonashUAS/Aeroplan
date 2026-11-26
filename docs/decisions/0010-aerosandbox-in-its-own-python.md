---
id: "0010"
title: AeroSandbox runs in its own Python
date: 2026-10-14
status: superseded
kind: architecture
superseded_by: ["0030"]
---
# 10. AeroSandbox runs in its own Python

Superseded by ADR 0030. The text below is history.

## Context

AeroSandbox and Proptimiser need packages that AeroPlan does not need.

## Decision

AeroSandbox runs in `tools/aerosandbox/.venv`, made by `aeroplan setup AeroSandbox` with uv. The spoke sends jobs to `model.py`, which runs in that Python with the files `component.py`, `mission.py`, `optimise.py` and `result.py`. These files import aerosandbox and proptimiser (CasADi path, no JAX). The spoke (`spoke.py`) runs in the AeroPlan Python and imports neither. Tests that need the AeroSandbox Python skip without it.

Changed by [ADR 24](0024-aircraft-models-in-code.md): the worker file is `model.py`.

## Consequences

A venv can hold absolute paths. After a folder move, run `aeroplan setup AeroSandbox` if it fails.
