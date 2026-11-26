---
id: "0021"
title: One ArduPilot spoke for flight events and flight files
date: 2026-10-17
status: accepted
kind: architecture
applies_to: ["aeroplan/ardupilot/**"]
---
# 21. One ArduPilot spoke for flight events and flight files

## Context

The ArduPilot and MissionPlanner spokes shared the work folder, the parameter parser and the autopilot topic, with two settings files for one aircraft.

## Decision

`aeroplan/ardupilot/` holds both. One settings file `settings/<aircraft>.yaml`: `releases` and `flights` (flight events, nodes 1.8.1.4 and 1.2.9) and `flight_files` (parameters, waypoints, geofence, node 1.2.5.10). One work folder `work/ardupilot/<aircraft>/`. Flight events use `flightfiles.parse_parm`. The export command is `aeroplan export ArduPilot`.

## Consequences

All behaviour and dataset roles stay. The MissionPlanner spoke name does not exist any more.

## Rules

- process: One spoke (ArduPilot) holds the flight events and the flight files. The settings file is `settings/<aircraft>.yaml`.
