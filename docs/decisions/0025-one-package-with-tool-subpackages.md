---
id: "0025"
title: One package, with a subpackage for each tool
date: 2026-10-30
status: accepted
kind: architecture
supersedes: ["0006", "0020"]
amended_by: ["0030"]
applies_to: ["aeroplan/**"]
---
# 25. One package, with a subpackage for each tool

## Context

The code was in three places: the core in `src/aeroplan/`, the spokes in `tools/<tool>/`, and the flow5 file readers in
`src/aeroplan/adapters/`. The spoke loader imported each `tools/<tool>/spoke.py` by file path into a made-up package
(`aeroplan_spokes`). The AeroSandbox model files imported each other as top-level modules, so they ran only as scripts with
their folder on `sys.path`. The core imported the flow5 readers, so core and tool code depended on each other.

## Decision

- The package is `./aeroplan` (flat layout). `src/` is removed.
- Each tool is a subpackage `aeroplan/<tool>/` with `spoke.py`, `README.md`, `settings/` and its other modules. `tools/` and
  `adapters/` are removed. The spoke loader imports `aeroplan.<tool>.spoke`.
- The flow5 file readers are in `aeroplan/flow5/` (`files.py`, `polar.py`, `buildup.py`). The tool-neutral wing form
  (`Section`, `Wing`) is in the core module `aeroplan/wing.py`.
- The core (`aeroplan/*.py`, `aeroplan/muas/`) imports no tool package. A test checks it.
- `work/<tool>/<aircraft>/` stays at the repository root. Git ignores it.
- A tool Python stays in its tool folder: `aeroplan/<tool>/.venv`. The AeroSandbox worker runs as the module
  `aeroplan.aerosandbox.model` in that Python. (ADR 0030 changes this for AeroSandbox: it runs in the repository `.venv`.)
- Setuptools finds only folders with an `__init__.py` (`namespaces = false`), so the wheel holds no settings, data, notebooks
  or tool Python.

## Consequences

The repository-relative paths in the asset register and in the settings changed from `tools/<tool>/` to `aeroplan/<tool>/`
by a one-time migration through `source_tree`. No dataset hash changed. Each tool Python was made again with
`aeroplan setup <tool>` (ADR 10). `aeroplan_dirty` of the build record now checks `aeroplan/` only.

With a flat layout, setuptools writes `aeroplan.egg-info` next to `pyproject.toml` when it builds. Git ignores it.

## Rules

- AP001: The core (`aeroplan/*.py`, `aeroplan/muas/`) imports no tool package.
- AP002: A tool package imports no other tool package.
- AP005: Each spoke has `__init__.py`, `spoke.py`, `README.md` and `settings/`, and keeps the spoke contract (`spokes.check_spoke`). Start a new spoke with `python -m aeroplan new-spoke <Name>`.
- AP006: The repository root is `aeroplan.REPO_ROOT`. Never compute it from `parents[n]` or `.parent.parent`.
