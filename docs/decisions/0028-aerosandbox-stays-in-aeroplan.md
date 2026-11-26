---
id: "0028"
title: The AeroSandbox model stays in AeroPlan, with one seam
date: 2026-10-30
status: accepted
kind: architecture
amends: ["0024"]
applies_to: ["aeroplan/aerosandbox/**"]
---
# 28. The AeroSandbox model stays in AeroPlan, with one seam

## Context

The AeroSandbox model files (`component.py`, `model.py`, `optimise.py`, `mission.py`, `result.py`, `plot.py`, `window.py`)
and the Rosella notebook could become a separate repository, for example a tool to show a design. Today they are tightly
joined to AeroPlan:

- The model read the source tree of the base aircraft itself, and found the repository root by folder arithmetic.
- The model uses the AeroPlan geometry and frame helpers.
- The spoke (1400 lines) imports AeroPlan, so it must stay in AeroPlan in any case.

## Decision

- The model files stay in AeroPlan, in `aeroplan/aerosandbox/` (ADR 25).
- The model files read the source tree in one function only: `component.base_document`. They never import the spoke
  machinery (`aeroplan.spokes`). A test checks both rules.
- The model files may import the pure AeroPlan helpers (`adh_doc`, `frame`, `geometry`, `wing`).

Make the split when one of these is true:

1. A second program (not AeroPlan) needs the model or the plots.
2. The model reads its aircraft from a `.muas` package, as Aerolink does. Then `base_document` is the only function to change.
3. The release cycle of the model differs from that of AeroPlan.

## Consequences

The split stays cheap: change `base_document`, move the seven files and the notebooks, and give the spoke a dependency on the
new package. Until then one test run covers the model and the source tree together.

## Rules

- AP004: The AeroSandbox model files read the source tree only in `component.base_document` and never import `aeroplan.spokes`.
