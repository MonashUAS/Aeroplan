"""Mass properties (brief D11) with roll-up through the parallel-axis theorem.

Inertia is about the node's own CG, axes parallel to the design frame.
Product convention: Ixy = +integral(x y dm). The inertia tensor then has
off-diagonal entries -Ixy, -Ixz, -Iyz.
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable, List, Optional

import numpy as np
from pydantic import Field, model_validator

from .base import MuasModel
from .provenance import Provenance
from .reference import Position
from .uncertainty import Uncertainty
from .units import Quantity


class MassSource(str, Enum):
    ESTIMATE = "estimate"
    CAD = "cad"
    WEIGHED = "weighed"


class Inertia(MuasModel):
    axes: str = "parallel_to_design"
    products_convention: str = "+integral(xy dm)"
    ixx: float
    iyy: float
    izz: float
    ixy: float = 0.0
    ixz: float = 0.0
    iyz: float = 0.0
    units: str = "kg*m^2"
    unverified_products: List[str] = Field(
        default_factory=list, description="Product terms (for example ixz) stored as written by the source, sign convention unverified")

    def tensor(self) -> np.ndarray:
        return np.array(
            [[self.ixx, -self.ixy, -self.ixz], [-self.ixy, self.iyy, -self.iyz], [-self.ixz, -self.iyz, self.izz]]
        )

    @model_validator(mode="after")
    def _physical(self):
        if self.units != "kg*m^2" or self.axes != "parallel_to_design":
            raise ValueError("inertia is stored in kg*m^2 about axes parallel to the design frame")
        if self.products_convention != "+integral(xy dm)":
            raise ValueError("unsupported products convention")
        if np.linalg.eigvalsh(self.tensor()).min() <= 0:
            raise ValueError("inertia tensor is not positive definite")
        tol = 1e-9 * max(self.ixx, self.iyy, self.izz)
        if self.ixx + self.iyy < self.izz - tol or self.iyy + self.izz < self.ixx - tol or self.ixx + self.izz < self.iyy - tol:
            raise ValueError("inertia violates the triangle inequalities")
        return self


class MassProperties(MuasModel):
    mass: Quantity
    cg: Position
    inertia: Optional[Inertia] = None
    source: MassSource
    uncertainty: Optional[Uncertainty] = None
    placeholder: bool = Field(False, description="True when the values are a stand-in, not data")
    provenance: Optional[Provenance] = None
    notes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self):
        self.mass.require("mass", "mass")
        if self.mass.value <= 0:
            raise ValueError("mass must be positive")
        return self


def roll_up(items: Iterable[MassProperties]) -> MassProperties:
    """Combine items into one MassProperties about the combined CG (parallel-axis theorem)."""
    items = list(items)
    if not items:
        raise ValueError("nothing to roll up")
    if any(i.inertia is None for i in items):
        raise ValueError("every item needs inertia for a roll-up")
    m = np.array([i.mass.value for i in items])
    r = np.array([i.cg.xyz for i in items])
    total = m.sum()
    cg = (m[:, None] * r).sum(axis=0) / total
    tensor = np.zeros((3, 3))
    for mi, ri, it in zip(m, r, items):
        d = ri - cg
        tensor += it.inertia.tensor() + mi * (d @ d * np.eye(3) - np.outer(d, d))
    inertia = Inertia(
        ixx=tensor[0, 0], iyy=tensor[1, 1], izz=tensor[2, 2], ixy=-tensor[0, 1], ixz=-tensor[0, 2], iyz=-tensor[1, 2]
    )
    return MassProperties(
        mass=Quantity(value=float(total), units="kg"),
        cg=Position(xyz=[float(v) for v in cg]),
        inertia=inertia,
        source=MassSource.ESTIMATE,
        placeholder=any(i.placeholder for i in items),
    )
