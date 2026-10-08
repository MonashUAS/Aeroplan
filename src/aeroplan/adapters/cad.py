"""CAD adapter: contract only. Not implemented in P0.

Contract for the later implementation:
- Input: CAD mass-property exports and STL or topology files (Creo `.ibl` and parameters).
- Output: `muas.mass_properties` per ADH node (muas/mass.py) and a geometry hash.
- Inertia about the node CG, axes parallel to the design frame, product convention +integral(xy dm).
- The roll-up must equal an independent total within sigma (brief section 7, step 6).
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from .base import Adapter


class CadAdapter(Adapter):
    name = "cad"
    produces = ("mass_properties", "geometry_hash")

    def ingest(self, source: Path, out_dir: Path) -> List[Path]:
        raise NotImplementedError("CAD adapter starts in phase P3")
