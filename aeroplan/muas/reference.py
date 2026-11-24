"""Reference data: frames, MRP and signs (brief D05; user answer 7). The reference values (S, b, c) are ADH data: the
`parameters.reference_data` of node 1.2 (Sref, BLref, Cbar in SI by patch 0004, ADR 0027). Read them with
`aeroplan.adh_doc.reference`.

MRP definition: the nominal-configuration CG, stored as a FIXED point in the
design frame. It is not the instantaneous CG. See docs/decisions.md section "MRP".
"""
from __future__ import annotations

import math
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import Field, model_validator

from .base import MuasModel
from .units import ureg


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
    design_frame: Literal["x_fwd_y_right_z_down_m_wingLE", "x_fwd_y_right_z_down_m_bodyOrigin"] = \
        "x_fwd_y_right_z_down_m_wingLE"
    kind: Optional[Literal["multirotor", "quadplane"]] = Field(
        None, description="Absent: a fixed-wing aircraft (the reference values Sref, BLref, Cbar are the wing). multirotor: "
        "Sref is the frontal area of the body, BLref the hub-to-hub span in y, Cbar the hub-to-hub length in x. quadplane: "
        "a fixed wing (the reference values are the wing) with lift rotors on booms (propeller role lift, motor 5 and up) "
        "and one cruise propeller. The vehicle kind selects what Aerolink needs (aeroplan.consumers.FLIGHT_ITEMS_BY_KIND)")
    body_frame: Literal["FRD"] = "FRD"
    euler: Literal["3-2-1/NED"] = "3-2-1/NED"
    nominal_cg: Position
    mrp: Mrp
    surface_signs: Dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_SIGNS))
    placeholder_fields: List[str] = Field(default_factory=list, description="Fields whose values are stand-ins. "
                                          "s_ref, b_ref and c_ref name the ADH reference values Sref, BLref and Cbar")
    notes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self):
        if not all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(self.mrp.point.xyz, self.nominal_cg.xyz)):
            raise ValueError("mrp.point must equal nominal_cg when definition is nominal_cg")
        return self
