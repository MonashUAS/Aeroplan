# 20. Repository layout A

Date: 2026-10-17

Status: accepted

## Context

Tool folders, standards and work files sat in the repository root with mixed case and many `work/` folders.

## Decision

Spokes go to `tools/<lower-case>/`. The ADH fork, the JSON Schema and the DAVE-ML DTDs go to `standards/` (`adh/`, `schema/`, `spec/`). Raw files go to one `work/<tool>/<aircraft>/` (git ignores `work/`). Documents go to `docs/` in the Diataxis split. The Master Specification Sheet moved to `tools/specsheet/sheets/currawong/`.

## Consequences

Register paths changed by code (a one-time migration through `source_tree`). No dataset hash changed. The two tool Pythons moved with their folders.
