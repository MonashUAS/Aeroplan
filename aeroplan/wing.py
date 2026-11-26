"""A lifting surface in the section form of the tools (flow5, OpenVSP, AeroSandbox): the right half, root first.

The tool conventions (flow5, also used by the other spokes):

- A section twists about its quarter chord. Positive twist is nose up.
- Each section's dihedral applies to the panel outboard of it.
- Ry is a rotation about +y with nose up positive. Rx is a rotation about -x (Rx = -90 stands the fin up).

This is a tool shape in memory. The source tree stores the ADH `geometry.lifting_surface` (see geometry.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Section:
    y: float
    chord: float
    x_offset: float
    dihedral_deg: float
    twist_deg: float
    foil: str


@dataclass(frozen=True)
class Wing:
    """A wing, elevator or fin. `position` is the root leading edge. Only the right half is listed."""

    name: str
    kind: str
    position: Tuple[float, float, float]
    rx_deg: float
    ry_deg: float
    symmetric: bool
    two_sided: bool
    sections: Tuple[Section, ...]

    @property
    def mirrored(self) -> bool:
        """True when a left half exists. A single fin has none."""
        return self.symmetric and (self.kind != "FIN" or self.two_sided)

    def section_z(self) -> Tuple[float, ...]:
        """The height of each section from the dihedral of the panels inboard of it (root at 0), wing frame. The only
        copy of this sum: geometry, parts and visual use it."""
        z = [0.0]
        for a, b in zip(self.sections, self.sections[1:]):
            z.append(z[-1] + (b.y - a.y) * math.tan(math.radians(a.dihedral_deg)))
        return tuple(z)
