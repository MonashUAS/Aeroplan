# 1. SSOT lives inside AeroPlan

Date: 2026-10-08

Status: accepted

## Context

Aircraft data was in a separate repository (muas-fleet-data). Two places for the same data cause drift.

## Decision

The SSOT lives in AeroPlan, in `aircraft/<aircraft>/`. The muas-fleet-data repository is deleted. Do not use it.

## Consequences

One repository holds code and data. Tools and people change data only through AeroPlan.
