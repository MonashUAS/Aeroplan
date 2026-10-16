# 5. glTF for the 3D view, no STL output

Date: 2026-10-10

Status: accepted

## Context

Aerolink needs a compact view of the parts with names and poses.

## Decision

Aerolink packaging uses glTF (`preview/aircraft.glb`) for the 3D parts. AeroPlan writes no STL output.

## Consequences

Without CAD files, the parts come from the ADH shapes. They look simpler but move the same.
