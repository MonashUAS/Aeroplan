---
id: "0012"
title: The Master Specification Sheet owns the mass model
date: 2026-10-15
status: accepted
kind: data
applies_to: ["aeroplan/specsheet/**", "aeroplan/mass_model.py"]
---
# 12. The Master Specification Sheet owns the mass model

## Context

Weights come from weighing, and the sheet is the record.

## Decision

The Master Specification Sheet owns the mass model. The SpecSheet spoke writes the subassembly masses and the 1.2 roll-up (mass, CG, inertia, point masses). It runs after flow5, so flow5 ingest cannot keep its own mass model. The nominal configuration is the measured aircraft with no payload. Payload layouts are named configurations in the notebooks only.

## Consequences

The sheet file is in `aeroplan/specsheet/sheets/<aircraft>/`. Two exceptions exist: the Rosella sizing owns the Rosella mass model until a SpecSheet exists (ADR 0022), and the Redback uses the CSV mode of the spoke (ADR 0018).

## Rules

- process: Only the SpecSheet spoke writes the mass roll-up of node 1.2. The exceptions are ADR 0022 (the Rosella sizing) and the CSV mode of ADR 0018.
