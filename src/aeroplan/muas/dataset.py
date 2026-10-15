"""Dataset metadata: what every dataset in the asset register carries (source tool, version, fidelity, role, sigma,
moment reference point). ADH has no slot for these, so they sit in the register entry under 1.10.2 DataRepository.

The tool and its version use the ADH `ModelDescription` (generation_tool, version, generation_date_and_time). The
sigma uses the ADH DAVE-ML `Uncertainty` form (normal or uniform PDF). The rest is MUAS. These fields keep a later
multi-fidelity model (MGP) possible: each dataset says where it comes from and how good it is.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, field_validator

from .base import MuasModel
from .mass import MassProperties
from .reference import Position


class Fidelity(str, Enum):
    """L0 handbook, L1 AeroSandbox, L2 flow5/VSPAERO, L3 CFD/stand/CAD, L4 flight, REF a published reference model."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    REF = "REF"


class DatasetRole(str, Enum):
    AERO = "aero"
    PROPULSION = "propulsion"
    MASS = "mass"
    CONTROL = "control"
    FLIGHT_RECORD = "flight-record"
    PARAMETERS = "parameters"
    SEGMENTS = "segments"
    OTHER = "other"


class DatasetMeta(MuasModel):
    """The metadata of one dataset (a JSON value: an ADH DAVEfunc, or tables)."""

    form: Literal["daveml-adh", "tables", "parameters"] = Field(
        description="daveml-adh: an ADH DAVEfunc. tables: {name: {columns, units}}. parameters: {name: number}")
    model_description: Dict[str, Any] = Field(description="ADH ModelDescription: generation_tool, version, "
                                              "generation_date_and_time, author, description")
    fidelity: Fidelity
    sigma: Optional[Dict[str, Any]] = Field(None, description="ADH Uncertainty form. None: no uncertainty estimate "
                                            "exists in the source")
    mrp: Optional[Position] = Field(None, description="Moment reference point of the moments, design frame")
    analysis_mass_model: Optional[MassProperties] = Field(
        None, description="The mass model (mass, CG, inertia) that the source analysis flew. The aero model belongs to "
        "this mass model. The mass model of the air vehicle can differ from it after a later change")
    units_system: Literal["SI", "as-source"] = Field(
        "SI", description="as-source: a published reference model kept in its own units. Each variable names its units")
    placeholder: bool = False
    notes: List[str] = Field(default_factory=list)

    @field_validator("model_description")
    @classmethod
    def _adh_model_description(cls, v):
        from aircraft_data_hierarchy.performance import ModelDescription

        ModelDescription.model_validate(v)
        if not v.get("generation_tool"):
            raise ValueError("model_description.generation_tool names the source tool")
        return v

    @field_validator("sigma")
    @classmethod
    def _adh_uncertainty(cls, v):
        if v is not None:
            from aircraft_data_hierarchy.behavior import Uncertainty

            Uncertainty.model_validate(v)
        return v


class DatasetRef(MuasModel):
    """A pointer from an ADH item to a dataset: `asset:sha256:<hash>` plus an optional `#/<path>` in the dataset."""

    role: DatasetRole
    ref: str = Field(pattern=r"^asset:sha256:[0-9a-f]{64}(#/.*)?$")
