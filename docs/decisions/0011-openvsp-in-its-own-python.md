# 11. OpenVSP runs in its own Python

Date: 2026-10-10

Status: accepted

## Context

The OpenVSP Python package needs its own interpreter.

## Decision

OpenVSP runs in `tools/openvsp/.venv`, made by `aeroplan setup OpenVSP` with uv. The spoke sends jobs to `vsp_worker.py`, which imports only openvsp and numpy. Tests that need it skip without it.

## Consequences

Same venv path note as ADR 0009.
