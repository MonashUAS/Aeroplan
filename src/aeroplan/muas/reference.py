"""Reference data: frames, reference geometry, MRP (brief D05; user answer 7).

MRP definition: the nominal-configuration CG, stored as a FIXED point in the
design frame. It is not the instantaneous CG. See docs/decisions.md section "MRP".
"""
from __future__ import annotations

import math
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import Field, model_validator

from .base import MuasModel
from .units import Quantity, ureg


class Position(MuasModel):
    frame: Literal["design"] = "design"
    xyz: List[float] = Field(min_length=3, max_length=3)
    units: str = "m"

    @model_validator(mode="after")
    def _to_metres(self):
        factor = ureg.Quantity(1.0, self.units).to("m").magnitude
        if self.units != "m":
            object.__setattr__(self, "xyz", [v * factor for v in self.xyz])
            object.__setattr__(self, "units", "m")
        return self


class MrpDefinition(str, Enum):
    NOMINAL_CG = "nominal_cg"


class Mrp(MuasModel):
    definition: MrpDefinition = MrpDefinition.NOMINAL_CG
    config_id: str
    point: Position
    mass_properties_sha256: Optional[str] = Field(None, pattern=r"^[0-9a-f]{64}$")


DEFAULT_SIGNS: Dict[str, str] = {
    "elevator": "trailing edge down positive",
    "aileron": "positive rolls right",
    "rudder": "trailing edge left positive",
}


class ReferenceData(MuasModel):
    design_frame: Literal["x_aft_y_right_z_up_m_noseDatum", "x_aft_y_right_z_up_m_flow5Origin"] = (
        "x_aft_y_right_z_up_m_noseDatum"
    )
    body_frame: Literal["FRD"] = "FRD"
    euler: Literal["3-2-1/NED"] = "3-2-1/NED"
    s_ref: Quantity
    b_ref: Quantity
    c_ref: Quantity
    nominal_cg: Position
    mrp: Mrp
    surface_signs: Dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_SIGNS))
    placeholder_fields: List[str] = Field(default_factory=list, description="Fields whose values are stand-ins")
    notes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self):
        self.s_ref.require("area", "s_ref")
        self.b_ref.require("length", "b_ref")
        self.c_ref.require("length", "c_ref")
        for q in (self.s_ref, self.b_ref, self.c_ref):
            if q.value <= 0:
                raise ValueError("reference geometry must be positive")
        if not all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(self.mrp.point.xyz, self.nominal_cg.xyz)):
            raise ValueError("mrp.point must equal nominal_cg when definition is nominal_cg")
        return self
