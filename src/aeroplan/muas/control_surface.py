"""Control-surface extension (brief D13). Rudder and elevator are instances under 1.2.2.4, not new WBS numbers."""
from __future__ import annotations

from typing import Optional

from pydantic import Field, model_validator

from .base import MuasModel


class ControlSurface(MuasModel):
    parent: str = Field(description="muas.instance of the parent surface")
    eta_span: tuple[float, float] = Field(description="Span fraction, inboard to outboard")
    hinge_x_over_c: float = Field(ge=0, le=1)
    limit_min_rad: float
    limit_max_rad: float
    positive_sign: str
    s119_name: str
    jsbsim_property: Optional[str] = None

    @model_validator(mode="after")
    def _check(self):
        if not (0 <= self.eta_span[0] < self.eta_span[1] <= 1):
            raise ValueError("eta_span must satisfy 0 <= inboard < outboard <= 1")
        if self.limit_min_rad >= self.limit_max_rad:
            raise ValueError("limit_min_rad must be below limit_max_rad")
        return self
