---
id: "0013"
title: The MRP stays the CoG of the flow5 T7 analysis
date: 2026-10-15
status: superseded
kind: data
superseded_by: ["0033"]
---
# 13. The MRP stays the CoG of the flow5 T7 analysis

Superseded by ADR 0033. The text below is history.

## Context

The aero model is about the T7 point. The mass CG moved after the sheet.

## Decision

The MRP stays the CoG of the flow5 T7 analysis until a new flow5 sweep of the sheet mass model. `reference.nominal_cg` and `mrp` do not move with the mass model. The datum check warns when the mass CG differs from the MRP. `pack --profile aerolink` refuses (MRP = CG within 1 mm). Currawong lists no `aerolink` consumer until the re-sweep.

## Consequences

A new flow5 sweep closes this decision.
