# 10. AeroSandbox runs in its own Python

Date: 2026-10-14

Status: accepted

## Context

AeroSandbox and Proptimiser need packages that AeroPlan does not need.

## Decision

AeroSandbox runs in `tools/aerosandbox/.venv`, made by `aeroplan setup AeroSandbox` with uv. The spoke sends jobs to `asb_worker.py`, which imports aerosandbox and proptimiser (CasADi path, no JAX). Only that file imports them. Tests that need it skip without it.

## Consequences

A venv can hold absolute paths. After a folder move, run `aeroplan setup AeroSandbox` if it fails.
