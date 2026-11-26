---
id: "0011"
title: OpenVSP runs in its own Python
date: 2026-10-10
status: accepted
kind: architecture
applies_to: ["aeroplan/openvsp/**"]
---
# 11. OpenVSP runs in its own Python

## Context

The OpenVSP Python package needs its own interpreter.

## Decision

OpenVSP runs in `aeroplan/openvsp/.venv` (the path since ADR 0025), made by `aeroplan setup OpenVSP` with uv. The spoke sends jobs to `vsp_worker.py`, which imports only openvsp and numpy. Tests that need it skip without it.

## Consequences

A venv can hold absolute paths. After a folder move, run `aeroplan setup OpenVSP` again.

## Rules

- AP020: `aeroplan/openvsp/vsp_worker.py` imports only openvsp, numpy and the standard library.
- process: OpenVSP runs in `aeroplan/openvsp/.venv`, made by `python -m aeroplan setup OpenVSP`.
