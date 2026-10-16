# 18. Multirotor path

Date: 2026-10-16

Status: accepted

## Context

The Redback (X quadcopter) has no sizing printout.

## Decision

The Redback starts from `tools/aerosandbox/settings/redback.yaml` (`kind: multirotor`, `aeroplan.multirotor.seed`). `muas.reference.kind = multirotor` selects the Aerolink needs (`consumers.FLIGHT_ITEMS_BY_KIND`): four lift rotors, motor outputs `motor1` to `motor4` (ArduPilot 33 to 36), no control surfaces. `spin` is the sense seen along the thrust vector (ArduPilot CCW from above is `cw`). The SpecSheet spoke has a CSV mode. The AeroSandbox worker has EMST jobs (Bershadsky 2016). The body drag is a forces-only DAVE-ML (`multirotor_aero.py`). The contract for Aerolink is `docs/reference/multirotor_contract.md`. The Mk4 propulsion CSV is an estimate (sanity check only).

## Consequences

Aerolink keeps a hand copy of the contract.
