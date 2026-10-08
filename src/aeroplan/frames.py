"""Frame transforms and moment transfer (brief D05).

Design frame: x aft, y right, z up, metres, nose datum.
Body frame: FRD (x forward, y right, z down).
"""
from __future__ import annotations

import numpy as np

_DESIGN_TO_FRD = np.diag([-1.0, 1.0, -1.0])


def design_to_frd(v) -> np.ndarray:
    """Rotate a vector from the design frame to body FRD. The map is its own inverse."""
    return _DESIGN_TO_FRD @ np.asarray(v, dtype=float)


def frd_to_design(v) -> np.ndarray:
    return _DESIGN_TO_FRD @ np.asarray(v, dtype=float)


def transfer_moment_coefficients(cf_frd, cm_frd, r_from_design, r_to_design, b_ref: float, c_ref: float):
    """Move body-axis moment coefficients from one reference point to another.

    cf_frd: (CX, CY, CZ) force coefficients in body FRD.
    cm_frd: (Cl, Cm, Cn) moment coefficients about `r_from`, nondimensionalised by (b, c, b).
    Returns (Cl, Cm, Cn) about `r_to`. Positions are in metres, design frame.
    Rule: M_to = M_from + d x F, with d = r_from - r_to (the force acts at r_from).
    """
    scale = np.array([b_ref, c_ref, b_ref])
    m_from = np.asarray(cm_frd, dtype=float) * scale
    d = design_to_frd(r_from_design) - design_to_frd(r_to_design)
    m_to = m_from + np.cross(d, np.asarray(cf_frd, dtype=float))
    return tuple(m_to / scale)
