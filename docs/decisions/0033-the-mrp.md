---
id: "0033"
title: The MRP
date: 2026-11-26
status: accepted
kind: data
supersedes: ["0013"]
applies_to: ["aeroplan/datum.py", "aeroplan/consumers.py", "aeroplan/muas/reference.py", "aeroplan/specsheet/**", "aeroplan/flow5/**"]
---
# 33. The MRP

## Context

Three texts defined the moment reference point (MRP) in three ways. ADR 0013 kept the MRP at the CoG of the flow5 T7
analysis until a new flow5 sweep. `CLAUDE.md` said "MRP = the nominal-configuration CG". ADR 0022 made the Rosella CG a
design output. The flow5 re-sweep of the Currawong is done.

## Decision

- The MRP of an aircraft is its nominal CG: one fixed point in the design frame (FRD), stored once in `muas.reference` of
  node 1.2.
- The aero model is about the MRP. A change of the MRP needs a new aero model (for a fixed wing: a new flow5 sweep).
- The datum check compares the MRP with the CG of the mass model. `pack --profile aerolink` refuses a package when they
  differ by more than 1 mm.
- The Rosella CG is a design output of the sizing (ADR 0022) until a SpecSheet exists.

## Consequences

ADR 0013 is closed. Currawong lists the `aerolink` consumer.

## Rules

- check: `aeroplan check` reports the MRP against the mass CG. `pack --profile aerolink` refuses more than 1 mm.
- process: Store the MRP once. A dataset may hold the MRP of its own model in its metadata.
