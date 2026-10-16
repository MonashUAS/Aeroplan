# 17. Flight files are datasets of the autopilot node

Date: 2026-10-16

Status: accepted

## Context

One file must hold the aircraft and everything it needs to fly.

## Decision

The ArduPilot flight files (`.parm`, `.waypoints`, geofence) go into the `.muas` as datasets of node 1.2.5.10 (roles `parameters`, `waypoints`, `geofence`). The `aerolink` profile embeds them (`consumers.tier`). `flightfiles.py` parses and writes the formats. Aerolink extracts them and can write them into the autopilot.

## Consequences

The spoke that reads them is the ArduPilot spoke (ADR 0021).
