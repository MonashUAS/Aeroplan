# 27. Store each fact once: ADH fields first

Date: 2026-10-30

Status: accepted.

## Context

A review compared the `muas` extension with the vendored ADH (Boeing commit `96179ca`, the head of `main`) and with the
report that ADH comes from (NASA/CR-20250007045). ADH is a prototype: it has no mass-properties class, no inertia, and no
unit conversion. Most `muas` keys fill a real gap. Four did not:

1. The wing and tail shape was stored twice: `muas.planform` (the source) and the ADH `geometry.lifting_surface` (made from
   it).
2. `muas.reference` held S, b and c, which ADH `parameters.reference_data` (Sref, BLref, Cbar) holds. Upstream documents that
   field in ft.
3. `muas.uncertainty` declared its own copy of the ADH `UncertaintyEffect`, and a `Correlation` with other field names.
4. `muas.control_surface` held the span and hinge, which ADH `AsymmetricControl` and `SymmetricFlap` hold.

## Decision

- A fact that ADH has a field for goes in that field, and only there. A `muas` key holds only what ADH has no field for.
- `standards/adh/EXTENSIONS.md` gives, for each `muas` key, what ADH has and why MUAS adds the key. A test stops the build
  when a key has no row.
- The ADH `geometry.lifting_surface` is the only stored shape of a lifting surface. `muas.lifting_surface` holds the section
  frame of the tools (position, rx, ry in rad), the tool name and role, the foil names, the symmetry and the structural mass.
  `geometry.planform_of` gives the tool sections back. The tip section has no outboard panel: it gets the dihedral of the
  last panel.
- S, b and c go in node 1.2 `parameters.reference_data`, in SI. Patch 0004 changes the upstream field descriptions from ft to
  m. ADH reads only the aliases (`Sref`, `BLref`, `Cbar`): a field name passes the validation as an unknown key and the value
  is lost. `adh_doc.set_reference` writes the aliases, and `validate_document` refuses every other key.
- The control-surface span and hinge go in `parameters.asymmetric_control` (a left or right surface) or
  `parameters.symmetric_flap` (a surface on both halves). The chord ratio is 1 - hinge x/c. The ADH `hingeline_chord_ratio`
  has no clear meaning, so AeroPlan does not use it.
- The ADH `UncertaintyEffect` checks the MUAS `effect` value (MUAS keeps no copy of the enum). The check imports ADH when a
  value comes, so the MUAS models load without the ADH package. `Correlation` uses the ADH field names (`var_id`,
  `corr_coef`) and adds the bound.
- No `muas` field holds degrees. The take-off pitch of a mission is `pitch_rad`.
- A stored quantity uses the SI name of its unit when the base units match exactly (W, V, ohm, Pa, N, `rad / V / s`).
- The MUAS extension version is 0.6.0. The build writes the version into each `muas` block.

## Consequences

One-time migrations moved the data. Each one checked its result: the planforms come back within 4e-15, the ADH splines did
not change, and the reference and control values are equal. Spoke code reads and writes these facts through
`adh_doc.reference`, `adh_doc.set_reference`, `adh_doc.control_surface`, `adh_doc.set_control_geometry`,
`geometry.planform_of` and `geometry.set_planform`.

The Aerolink contract changed to version 2 (`docs/reference/multirotor_contract.md`, section 11). The Aerolink hand copy of
the package reader must read the new places before it reads a package of extension version 0.6.0.
