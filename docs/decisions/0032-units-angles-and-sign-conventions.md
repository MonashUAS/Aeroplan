---
id: "0032"
title: Units, angles and sign conventions
date: 2026-11-26
status: accepted
kind: data
amends: ["0018", "0027"]
applies_to: ["aeroplan/**", "aircraft/**"]
---
# 32. Units, angles and sign conventions

## Context

The unit rules were in `CLAUDE.md`, in ADR 0027 and in ADR 0018 (the `spin` sign). `CLAUDE.md` named three forms of a unit,
and one form (an ADH float with a patched description) was true only for `reference_data`. Six core modules converted
degrees, and two constants (g0, the inch) had more than one copy.

## Decision

- The source tree stores SI. Angles are radians. No field of the tree holds degrees.
- A quantity carries its unit in one of two forms: a `{value, units}` quantity, or a field name with a unit suffix (`_m`,
  `_s`, `_rad`, `_mps`). An ADH float carries the SI unit that a patch writes in its description, or a row of
  `standards/adh/EXTENSIONS.md` names its unit.
- The core works in SI and radians. Degrees exist only inside `aeroplan/<tool>/`, at the edge of the tool. The tool-neutral
  wing form (`aeroplan/wing.py`) still holds degrees. The allowlist names it, and the pydantic work of the roadmap removes it.
- A physical constant or a unit factor is written once, in `aeroplan/constants.py`.
- `muas.propeller.spin` is the sense seen along the thrust vector, from behind (from below for a lift rotor). ArduPilot CCW
  from above is `cw` in the tree.
- Exception: a published reference model (DAVE-ML) keeps its own units (`units_system: as-source`), because its check cases
  use them.

## Rules

- AP010: The core converts no angle to or from degrees.
- AP011: A physical constant is written once, in `aeroplan/constants.py`.
- check: `Quantity` converts each value to SI when it loads (`aeroplan/muas/units.py`).
- process: Every quantity carries its unit. Never type an unsourced number. A stand-in value has `placeholder: true` and
  names its source.
