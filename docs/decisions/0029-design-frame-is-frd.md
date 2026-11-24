# 29. The design frame is FRD

Date: 2026-10-21 (written on 2026-10-30 from commit `f8b60fb` and `aeroplan/frame.py`)

Status: accepted. Amends ADR 0023 (the x axis).

## Context

ADR 0023 put the design frame origin at the root leading edge of the main wing, with x aft, y right and z up: the frame
of flow5, OpenVSP and AeroSandbox. ArduPilot, the aero datasets and the simulator use FRD body axes (x forward, y right,
z down). Each consumer had to flip the data. Commit `f8b60fb` changed the frame, but no ADR recorded it. The code cited
"ADR 0025" for it, and that number now holds the package layout.

## Decision

- The design frame is FRD: x forward, y right, z down, metres. The origin does not change: the root leading edge of
  `wing_main` (`x_fwd_y_right_z_down_m_wingLE`), or the middle of the four hubs for a multirotor
  (`x_fwd_y_right_z_down_m_bodyOrigin`).
- The map between x aft, z up and FRD is P = diag(-1, 1, -1), a turn of 180 degrees about y. A point or a vector becomes
  (-x, y, -z). The products of inertia Ixy and Iyz change sign. Ixz does not. P is its own inverse.
- A spoke flips at the edge of its tool (`aeroplan/frame.py`). The source tree holds FRD only. The planform numbers of a
  tool (x offset, dihedral, twist) describe a shape in a local frame and do not flip.
- The glTF view is FRD too. Its asset `extras.to_gltf` gives the turn to the glTF frame.
- The MUAS extension version became 0.5.0.

## Consequences

A consumer with an x-aft frame inside flips at its reader. Aerolink does this in its package reader, because JSBSim uses
an x-aft structural frame. The multirotor contract (version 2) gives the FRD values. Old reports in the x-aft frame keep
their numbers.
