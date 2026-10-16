# 16. The fuselage body is a fit of the Creo skin

Date: 2026-10-15

Status: accepted

## Context

The exact skin is heavy. Some analyses need a simple body.

## Decision

`geometry.body` is a fit of the Creo shrinkwrap skin, cut by the CREO spoke (`aeroplan.skin_body`). The skin (`muas.skin`, faceted STEP) stays the exact shape and goes to OpenVSP (CompGeom, parasite drag, VSPAERO panel). `muas.skin.body_fit` records the method and the fit.

## Consequences

OpenVSP and flow5 can use different fuselage shapes. The datum table shows the gap.
