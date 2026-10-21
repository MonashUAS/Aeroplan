"""The design frame: FRD (x forward, y right, z down, metres) with its origin at the wing root leading edge (ADR 0025).

The tools flow5, OpenVSP and AeroSandbox work in x aft, y right, z up. The map between the two frames is
P = diag(-1, 1, -1), a turn of 180 degrees about y. P is its own inverse, so each function here converts in both
directions. A spoke converts at the edge of its tool and never inside the source tree.

A point or a vector is flipped as (-x, y, -z). The products of inertia Ixy and Iyz change sign. Ixz does not. The
planform numbers (x_offset, dihedral, twist, rx, ry) describe a shape in a local frame (aft, right, up). They stay as
they are. `planform_le_x` gives the design x of a section leading edge.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np

from . import MUAS_SCHEMA_VERSION

P = np.diag([-1.0, 1.0, -1.0])

#: old design_frame -> new design_frame
FRAME_NAMES = {
    "x_aft_y_right_z_up_m_flow5Origin": "x_fwd_y_right_z_down_m_wingLE",
    "x_aft_y_right_z_up_m_bodyOrigin": "x_fwd_y_right_z_down_m_bodyOrigin",
}
NEW_FRAMES = tuple(FRAME_NAMES.values())

#: keys that hold one point or one vector (3 numbers)
_VECTOR_KEYS = ("xyz", "centre", "p0", "p1", "thrust_axis", "axis", "origin_m")
#: sub trees in a frame of their own (unit-chord foil sections): never flipped
_SKIP_KEYS = ("airfoil_sections",)


def _neg(v):
    return 0 - v


def _is_vec(v: Any, n: int = 3) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == n and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)


def flip_point(xyz: Sequence[float]) -> List[float]:
    """A point or a vector between x aft, z up and FRD."""
    return [_neg(xyz[0]), xyz[1], _neg(xyz[2])]


flip_vector = flip_point


def flip_inertia(ixy: float, ixz: float, iyz: float):
    """The products of inertia (+integral of xy dm and so on) after the flip: (Ixy, Ixz, Iyz)."""
    return _neg(ixy), ixz, _neg(iyz)


def flip_axes(axes: Sequence[str]) -> List[str]:
    """The signed CAD axes of a Transform (one for each design axis): the x and z entries change sign."""
    out = list(axes)
    for i in (0, 2):
        out[i] = out[i][1:] if out[i].startswith("-") else "-" + out[i]
    return out


def flip_array(a: np.ndarray) -> np.ndarray:
    """Rows of points (n x 3)."""
    return np.asarray(a, dtype=float) * np.array([-1.0, 1.0, -1.0])


def planform_le_x(position_x: float, x_offset: float) -> float:
    """Design x of the leading edge of a planform section. x_offset is aft positive, as in flow5."""
    return position_x - x_offset


def _flip(o: Any, key: str = "") -> Any:
    if isinstance(o, dict):
        if {"x", "y", "z"} <= set(o) and all(isinstance(o[k], (int, float)) for k in "xyz"):
            o = dict(o)
            o["x"], o["z"] = _neg(o["x"]), _neg(o["z"])
            return o
        out = {}
        for k, v in o.items():
            if k in _SKIP_KEYS:
                out[k] = v
            elif k in _VECTOR_KEYS and _is_vec(v):
                out[k] = flip_point(v)
            elif k == "hinge" and isinstance(v, list) and all(_is_vec(p) for p in v):
                out[k] = [flip_point(p) for p in v]
            elif k == "axes" and isinstance(v, list) and v and all(isinstance(s, str) and s.lstrip("-") in ("x", "y", "z") for s in v):
                out[k] = flip_axes(v)
            elif k == "x_m" and _is_vec(v, 2):
                out[k] = [_neg(v[1]), _neg(v[0])]
            elif k in ("ixy", "iyz") and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = _neg(v)
            else:
                out[k] = _flip(v, k)
        return out
    if isinstance(o, list):
        return [_flip(x, key) for x in o]
    return o


def flip_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """A copy of an ADH document (or one node, or one fragment) with every frame value flipped. The data has no
    other change. Apply it twice and the result is the input."""
    return _flip(copy.deepcopy(doc))


def _set_frame(o: Any, to_new: bool) -> int:
    n = 0
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "design_frame" and isinstance(v, str):
                names = FRAME_NAMES if to_new else {b: a for a, b in FRAME_NAMES.items()}
                if v not in names:
                    raise ValueError(f"design_frame {v!r} is not one of {sorted(names)}")
                o[k] = names[v]
                n += 1
            elif k == "ext_version" and isinstance(v, str):
                o[k] = MUAS_SCHEMA_VERSION
            else:
                n += _set_frame(v, to_new)
    elif isinstance(o, list):
        for x in o:
            n += _set_frame(x, to_new)
    return n


def migrate_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """x aft, z up -> FRD, for a whole document. A document that is FRD already is refused."""
    text = repr(doc)
    if any(f in text for f in NEW_FRAMES):
        raise ValueError("the document is in FRD already")
    out = flip_doc(doc)
    if _set_frame(out, True) != 1:
        raise ValueError("the document has no design_frame (a published reference model keeps its own frame)")
    return out


def migrate_tree(folder: Path) -> Path:
    """Rewrite the source tree of one aircraft in FRD. The datasets stay as they are (they hold no design frame value)."""
    from . import source_tree

    acft = source_tree.read(folder)
    acft.doc = migrate_doc(acft.doc)
    source_tree.write(acft, folder)
    return Path(folder)


def main(argv: Iterable[str] = None) -> int:
    import argparse

    from .build import aircraft_dir

    ap = argparse.ArgumentParser(description="Migrate source trees from x aft, z up to the FRD design frame (ADR 0025).")
    ap.add_argument("aircraft", nargs="+")
    args = ap.parse_args(argv)
    for name in args.aircraft:
        print(f"{name}: {migrate_tree(aircraft_dir(name))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
