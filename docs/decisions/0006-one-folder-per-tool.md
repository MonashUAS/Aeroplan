# 6. One spoke folder for each tool

Date: 2026-10-10

Status: accepted

## Context

Each tool has its own files and its own rules. Mixed code is hard to change.

## Decision

Each tool has one spoke folder with `spoke.py`, `README.md` and `settings/`. The tools: Prototype, AeroSandbox, flow5, SpecSheet, Propalyser, CREO, OpenVSP, DAVEML, ArduPilot, Aerolink. A new tool gets a new folder. The folder place changed in ADR 0020.

## Consequences

A tool member works in the tool and runs `aeroplan build`. The spoke checks and writes the data.
