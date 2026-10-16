# 13. The MRP stays the CoG of the flow5 T7 analysis

Date: 2026-10-15

Status: accepted

## Context

The aero model is about the T7 point. The mass CG moved after the sheet.

## Decision

The MRP stays the CoG of the flow5 T7 analysis until a new flow5 sweep of the sheet mass model. `reference.nominal_cg` and `mrp` do not move with the mass model. The datum check warns when the mass CG differs from the MRP. `pack --profile aerolink` refuses (MRP = CG within 1 mm). Currawong lists no `aerolink` consumer until the re-sweep.

## Consequences

A new flow5 sweep closes this decision.
