---
id: "0022"
title: Quadplane path
date: 2026-10-17
status: accepted
kind: data
applies_to: ["aeroplan/aerosandbox/**", "aircraft/rosella/**"]
---
# 22. Quadplane path

## Context

The Rosella is a VTOL quadplane. It uses the Currawong V1 wing, tail and tail boom. It has a new fuselage and lift booms. It has no sizing printout and no SpecSheet. ADR 18 covers multirotors only. ADR 12 gives the mass model to the SpecSheet.

## Decision

The Rosella starts from `aeroplan/aerosandbox/settings/rosella.json` (the `airframe` component has `base: currawong`). The
notebook `aeroplan/aerosandbox/notebooks/rosella_sizing.ipynb` and the `QuadplaneModel` of `model.py` size the propulsion and
the booms with the EMST equations (Bershadsky 2016) in AeroSandbox. It has two configurations. H4 has four lift rotors. H8 has
a coaxial pair on each of the four H4 stations.

The Rosella CG is a design output: the VLM neutral point minus 10 % MAC. The sizing owns the mass model until a SpecSheet
exists. This is an exception to ADR 12. The SpecSheet takes the mass model back when it exists.

The model file `aeroplan/aerosandbox/settings/rosella.json` holds the components and the last result. The notebook writes it.
It never writes the source tree. The AeroSandbox spoke writes `aircraft/rosella/` from the model file (ADR 8). A bought part
is a component with fixed params. There is no second file for manual configurations.

The study choices (the lift blade, the bounds, the fidelity ladder and the rotor cant) were in this ADR until 2026-11-26.
They change with each solve, so they are now in the
[quadplane modelling report](../reports/quadplane_model/README.md#14-study-choices-from-adr-22).

The Currawong NP and CG question is closed: ADR 0033 records the MRP after the flow5 re-sweep.

## Consequences

The sizing numbers in `aircraft/rosella/` are placeholders until a SpecSheet and maker data replace them. Aerolink gets no Rosella package until a quadplane contract exists. The packing profiles are `review` and `archive`.

Changed by [ADR 24](0024-aircraft-models-in-code.md): the script, the YAML settings file and the manual file are replaced by the model classes and one JSON file.

## Rules

- process: A sizing notebook never writes the source tree. The AeroSandbox spoke writes it from the model file.
- process: The Rosella sizing owns the Rosella mass model until a SpecSheet exists (exception to ADR 0012).
