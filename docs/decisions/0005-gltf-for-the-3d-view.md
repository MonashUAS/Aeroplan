---
id: "0005"
title: glTF for the 3D view, no STL output
date: 2026-10-10
status: accepted
kind: architecture
applies_to: ["aeroplan/gltf.py", "aeroplan/visual.py", "aeroplan/parts.py"]
---
# 5. glTF for the 3D view, no STL output

## Context

Aerolink needs a compact view of the parts with names and poses.

## Decision

Aerolink packaging uses glTF (`preview/aircraft.glb`) for the 3D parts. AeroPlan writes no STL output.

## Consequences

Without CAD files, the parts come from the ADH shapes. They look simpler but move the same.

## Rules

- process: The 3D view is glTF (`preview/aircraft.glb`). AeroPlan writes no STL output.
