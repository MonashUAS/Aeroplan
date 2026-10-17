# 23. The design frame starts at the root leading edge of the main wing

Date: 2026-10-17

Status: accepted

## Context

ADR 0015 puts the Currawong wing root leading edge at x = 0.000. The old flow5 report used x = -0.080. The mass sheets, the spokes and the point masses all need one origin. The user wants the same origin for every aircraft.

## Decision

The origin of the design frame is the root leading edge (LE) of `wing_main`. The x axis points aft. This extends ADR 0015 to all aircraft.

Every mass position is measured from this point. This covers sheets, spokes and point masses. The specsheet mass sheet gives the CM of each object from the wing LE (column F, "CM-LE"). The SpecSheet setting `datum_x_m` must be 0.0.

`aeroplan check` fails when the `wing_main` root LE is not at x = 0 within 1 mm. The check skips an aircraft with no `wing_main`. The check also skips a published reference model (`units_system: as-source`, for example the F-16). The report says so.

An aircraft with no main wing (a multirotor) keeps ADR 0018.

## Consequences

A change of the wing position moves the whole aircraft in the tree, not the origin. Old reports with the wing at x = -0.080 (flow5, AeroSandbox methods report section 1.4) use the old frame.
