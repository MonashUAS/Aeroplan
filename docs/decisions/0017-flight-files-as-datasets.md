---
id: "0017"
title: Flight files are datasets of the autopilot node
date: 2026-10-16
status: accepted
kind: data
applies_to: ["aeroplan/ardupilot/**", "aeroplan/flightfiles.py"]
---
# 17. Flight files are datasets of the autopilot node

## Context

One file must hold the aircraft and everything it needs to fly.

## Decision

The ArduPilot flight files (`.parm`, `.waypoints`, geofence) go into the `.muas` as datasets of node 1.2.5.10 (roles `parameters`, `waypoints`, `geofence`). The `aerolink` profile embeds them (`consumers.tier`). `flightfiles.py` parses and writes the formats. Aerolink extracts them and can write them into the autopilot.

## Consequences

The spoke that reads them is the ArduPilot spoke (ADR 0021).

## Rules

- process: The flight files are datasets of node 1.2.5.10 with the roles `parameters`, `waypoints` and `geofence`.
