---
id: "0018"
title: Multirotor path
date: 2026-10-16
status: accepted
kind: data
amended_by: ["0032", "0036"]
applies_to: ["aeroplan/multirotor.py", "aeroplan/multirotor_aero.py", "aeroplan/aerosandbox/settings/redback.yaml"]
---
# 18. Multirotor path

## Context

The Redback (X quadcopter) has no sizing printout.

## Decision

The Redback starts from `aeroplan/aerosandbox/settings/redback.yaml` (`kind: multirotor`, `aeroplan.multirotor.seed`). `muas.reference.kind = multirotor` selects the Aerolink needs (`consumers.FLIGHT_ITEMS_BY_KIND`): four lift rotors, motor outputs `motor1` to `motor4` (ArduPilot 33 to 36), no control surfaces. `spin` is the sense seen along the thrust vector (ArduPilot CCW from above is `cw`). ADR 0032 now holds this sign rule. The SpecSheet spoke has a CSV mode. The AeroSandbox worker has EMST jobs (Bershadsky 2016). The body drag is a forces-only DAVE-ML (`multirotor_aero.py`). The contract for Aerolink is the Aerolink `docs/multirotor_contract.md` (ADR 0036). The Mk4 propulsion CSV is an estimate (sanity check only).

## Consequences

Aerolink owns the contract. AeroPlan keeps no copy (ADR 0036).

## Rules

- process: `muas.reference.kind = multirotor` selects the Aerolink needs (`consumers.FLIGHT_ITEMS_BY_KIND`).
