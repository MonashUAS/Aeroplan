---
id: "0037"
title: How an aircraft starts, by kind
date: 2026-11-26
status: accepted
kind: process
supersedes: ["0007"]
applies_to: ["aircraft/**"]
---
# 37. How an aircraft starts, by kind

## Context

ADR 0007 covered the fixed wing only, and it cited the wrong ADR for the multirotor path.

## Decision

| Kind | Starts from | Then | ADR |
|---|---|---|---|
| Fixed wing (Currawong) | the AeroSandbox sizing output | flow5, SpecSheet, CREO | 0012, 0016 |
| Multirotor (Redback) | `aeroplan/aerosandbox/settings/redback.yaml` (`aeroplan.multirotor.seed`) | SpecSheet CSV mode, Propalyser | 0018 |
| Quadplane (Rosella) | the model file `aeroplan/aerosandbox/settings/rosella.json` | a SpecSheet when one exists | 0022 |
| Published reference model (F-16) | the DAVEML spoke | none | - |
