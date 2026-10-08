"""Electric propulsion extension (brief D12; user answers 3, 4).

Propeller performance is a Ct/Cp table, a point dataset against advance ratio J
(and rpm when known). The data reaches AeroPlan through Propalyser. Proptimiser
output is an input to Propalyser, not to AeroPlan.

Definitions (standard propeller coefficients, see the references page, A8)::

    J  = V / (n D)
    Ct = T / (rho n^2 D^4)
    Cp = P / (rho n^3 D^5)

with n in rev/s and D the propeller diameter.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import Field, model_validator

from .base import MuasModel
from .dataset import DatasetKind, Fidelity, Processing, Role
from .provenance import Provenance
from .reference import Position
from .uncertainty import ScalarResult, Uncertainty, UncertaintyStatus
from .units import Quantity


class PropRole(str, Enum):
    CRUISE = "cruise"
    LIFT = "lift"


class Spin(str, Enum):
    CW = "cw"
    CCW = "ccw"


class PropellerInstallation(MuasModel):
    """Mount of a propeller or rotor in the design frame (WBS 1.2.3.9)."""

    role: PropRole
    hub: Position
    thrust_axis: List[float] = Field(min_length=3, max_length=3, description="Unit vector, design frame")
    spin: Spin
    diameter: Quantity

    @model_validator(mode="after")
    def _check(self):
        self.diameter.require("length", "diameter")
        norm = sum(v * v for v in self.thrust_axis) ** 0.5
        if abs(norm - 1.0) > 1e-6:
            raise ValueError("thrust_axis must be a unit vector")
        return self


class Motor(MuasModel):
    kv_rpm_per_volt: Optional[float] = Field(None, gt=0)
    resistance: Optional[Quantity] = None
    no_load_current: Optional[Quantity] = None


class Battery(MuasModel):
    cells_series: Optional[int] = Field(None, ge=1)
    capacity: Optional[Quantity] = Field(None, description="Charge capacity, A*s")
    nominal_voltage: Optional[Quantity] = None


class PropCtCpManifest(MuasModel):
    dataset_id: str
    kind: Literal[DatasetKind.PROP_CT_CP] = DatasetKind.PROP_CT_CP
    role: Role = Role.NOMINAL
    config_id: str
    propeller_id: str
    fidelity: Fidelity
    source_tool: str
    diameter: Quantity
    valid_domain: Literal["static_only", "forward_flight"]
    valid_j: Optional[tuple[float, float]] = Field(None, description="Advance-ratio range the table covers")
    limits: List[str] = Field(default_factory=list, description="Known limits, e.g. the static (J=0) power overstatement")
    derived: Dict[str, ScalarResult] = Field(default_factory=dict, description="Scalar results with coverage intervals")
    placeholder: bool = Field(False, description="True when the source says its values are a model, not a measurement")
    notes: List[str] = Field(default_factory=list)
    uncertainty: Uncertainty
    processing: Processing
    provenance: Provenance
    data: str = "points.parquet"
    columns: List[str] = Field(default_factory=lambda: ["J", "rpm", "Ct", "Cp", "Ct_sigma", "Cp_sigma"])

    @model_validator(mode="after")
    def _check(self):
        self.diameter.require("length", "diameter")
        for need in ("J", "Ct", "Cp"):
            if need not in self.columns:
                raise ValueError(f"columns must include {need}")
        if self.valid_domain == "static_only" and not self.limits:
            raise ValueError("a static_only dataset must say what it cannot support in limits")
        if self.uncertainty.status is UncertaintyStatus.QUANTITATIVE and self.uncertainty.per_point_column is None:
            raise ValueError("Ct/Cp datasets need per-point sigma columns")
        return self
