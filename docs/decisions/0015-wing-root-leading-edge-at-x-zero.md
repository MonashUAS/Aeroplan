# 15. The wing root leading edge sits at x = 0.000

Date: 2026-10-15

Status: accepted

## Context

flow5 had it at x = -0.080. The Creo assembly holds the wing panel at x = 0.

## Decision

The wing root leading edge is at x = 0.000 in the design frame, as in the Creo assembly. The SpecSheet datum (`datum_x_m` = 0.0) is the same point. The spoke warns when the document wing differs.

## Consequences

A change of the wing position needs a new flow5 sweep.
