"""Flow5 geometry and stability files: the plane XML, the foil .dat files and a T7 operating point.

Hand copy (2026-10-08) of the readers of Aerolink 6f7edb7 (`flow5/plane.py`, `flow5/opoint.py`), cut to what
AeroPlan uses: the wings of the plane, the foils, and the header scalars of a T7 (stability) operating point.

Flow5 conventions found by the old Aerolink, by a fit of the T7 panels (its tests kept the proof, NOT re-verified here):

- A section twists about its quarter chord. Positive twist is nose up.
- Each section's dihedral applies to the panel outboard of it.
- Ry is a rotation about +y with nose up positive. Rx is a rotation about -x (Rx = -90 stands the fin up).

The T7 stability derivatives use aeronautical signs (Cnb > 0 and Clb < 0 for this aircraft). The polar Cl and Cn
columns do not (see flow5.py).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..frame import flip_point

_GREEK = {"α": "alpha", "β": "beta", "φ": "phi", "γ": "gamma"}
_UNIT = re.compile(r"\(([^)]*)\)$")


class Flow5GeometryError(ValueError):
    """A plane XML, foil or operating-point file is missing or not readable."""


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


@dataclass
class Plane:
    name: str
    wings: List[Wing] = field(default_factory=list)

    def by_kind(self, kind: str) -> Wing:
        found = [w for w in self.wings if w.kind == kind]
        if len(found) != 1:
            raise Flow5GeometryError(f"plane {self.name}: expected one {kind} wing, found {len(found)}")
        return found[0]


def _tag(e: ET.Element) -> str:
    return e.tag.lower()


def _child(e: ET.Element, name: str) -> Optional[ET.Element]:
    return next((c for c in e if _tag(c) == name), None)


def _text(e: ET.Element, name: str, default: str = "") -> str:
    c = _child(e, name)
    return c.text.strip() if c is not None and c.text else default


def _vec(text: str) -> Tuple[float, float, float]:
    v = tuple(float(t) for t in text.replace(",", " ").split())
    if len(v) != 3:
        raise Flow5GeometryError(f"expected three numbers, got {text!r}")
    return v


def read_plane(path: Path) -> Plane:
    """Read the wings of a flow5 plane XML. Only SI units (all factors 1) are accepted. flow5 works in x aft, z up: the
    wing `position` is returned in the design frame (FRD, aeroplan.frame). The section numbers (x_offset, dihedral, twist)
    stay in the local frame of flow5."""
    path = Path(path)
    root = ET.fromstring(path.read_bytes())
    if _tag(root) != "xflplane":
        raise Flow5GeometryError(f"{path.name} is not a flow5 plane XML")
    units = _child(root, "units")
    if units is not None and any(abs(float(u.text) - 1.0) > 1e-9 for u in units if u.text and u.text.strip()):
        raise Flow5GeometryError(f"{path.name} uses non-SI units")
    node = _child(root, "plane")
    if node is None:
        raise Flow5GeometryError(f"{path.name} has no <Plane> element")
    plane = Plane(_text(node, "name", path.stem))
    for w in (c for c in node if _tag(c) == "wing"):
        secs = _child(w, "sections")
        sections = tuple(
            Section(float(_text(s, "y_position")), float(_text(s, "chord")), float(_text(s, "xoffset", "0")),
                    float(_text(s, "dihedral", "0")), float(_text(s, "twist", "0")),
                    _text(s, "left_side_foilname") or _text(s, "right_side_foilname"))
            for s in (secs if secs is not None else []) if _tag(s) == "section")
        plane.wings.append(Wing(
            _text(w, "name"), _text(w, "type").upper(), tuple(flip_point(_vec(_text(w, "position", "0 0 0")))),
            float(_text(w, "rx_angle", "0")), float(_text(w, "ry_angle", "0")),
            _text(w, "symmetric", "true").lower() == "true", _text(w, "two_sided", "false").lower() == "true", sections))
    return plane


def read_foil(folder: Path, name: str) -> np.ndarray:
    """The foil `name` from `folder/<name>.dat`: an (n, 2) array of x/c, y/c in Selig order."""
    folder = Path(folder)
    path = next((p for p in folder.glob("*.dat") if p.stem.lower() == name.lower()), folder / f"{name}.dat")
    if not path.is_file():
        raise Flow5GeometryError(f"foil file {name}.dat not found in {folder}")
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        t = line.split()
        if len(t) == 2:
            try:
                rows.append((float(t[0]), float(t[1])))
            except ValueError:
                continue
    if len(rows) < 10:
        raise Flow5GeometryError(f"foil file {path.name} holds only {len(rows)} points")
    return np.array(rows)


def _key(token: str) -> str:
    m = _UNIT.search(token)
    if m:
        token = token[: m.start()]
    return _GREEK.get(token, token).replace(".", "_")


def _floats(line: str) -> Optional[List[float]]:
    parts = line.split()
    if not parts:
        return None
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


def read_t7_scalars(path: Path) -> Dict[str, float]:
    """The header scalars of a flow5 7.57 operating-point text file (label row, then value row).

    The mass block is welded on one line (N labels, then N values). The reader stops at the first section title.
    """
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    out: Dict[str, float] = {}
    i = 2
    while i < len(lines):
        tokens = lines[i].split()
        if not tokens:
            i += 1
            continue
        if _floats(lines[i]) is not None:
            raise Flow5GeometryError(f"{Path(path).name} line {i + 1}: values without labels")
        k = len(tokens)
        while k > 0 and _floats(tokens[k - 1]) is not None:
            k -= 1
        if k >= 2 and len(tokens) == 2 * k:                     # welded: labels then values on one line
            out.update({_key(t): float(v) for t, v in zip(tokens[:k], tokens[k:])})
            i += 1
            continue
        nxt = _floats(lines[i + 1]) if i + 1 < len(lines) else None
        if nxt is None or len(nxt) != len(tokens):
            break                                                # a section title: the header ends here
        out.update({_key(t): v for t, v in zip(tokens, nxt)})
        i += 2
    if "Cma" not in out or "Cnb" not in out:
        raise Flow5GeometryError(f"{Path(path).name} has no stability derivatives (it needs a T7 analysis)")
    return out
