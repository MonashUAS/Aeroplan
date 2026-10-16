# 7. How a new aircraft starts

Date: 2026-10-10

Status: accepted

## Context

Sizing, geometry and reference models start from different tools.

## Decision

A new aircraft starts from the AeroSandbox sizing output, then moves forward to flow5. A published reference model (the NASA F-16, `aircraft/f16/`) starts from the DAVEML spoke.

## Consequences

The multirotor path is a variant (ADR 0016).
