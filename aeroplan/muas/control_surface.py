"""Control-surface extension (brief D13). A control surface is a subcomponent of the surface that carries it
(ADH has no Elevator or Rudder class). It holds no WBS number of its own. Its span fractions and hinge are ADH data:
`parameters.asymmetric_control` or `parameters.symmetric_flap` (ADR 0027, read them with adh_doc.control_surface)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, model_validator

from .base import MuasModel


class ControlSurface(MuasModel):
    parent: str = Field(description="muas.instance of the parent surface")
    limit_min_rad: float
    limit_max_rad: float
    positive_sign: str
    s119_name: str
    jsbsim_property: Optional[str] = None
    side: Literal["left", "right", "both"] = Field(
        "both", description="Which half of the parent carries the surface. both: every half the parent has")

    @model_validator(mode="after")
    def _check(self):
        if self.limit_min_rad >= self.limit_max_rad:
            raise ValueError("limit_min_rad must be below limit_max_rad")
        return self
