"""Point-dataset manifest (brief D06, D07, D08, D10, D21, section 9 MGP readiness).

One manifest plus one columnar points file. Master aero data is never a gridded table.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from pydantic import Field, model_validator

from .base import MuasModel
from .provenance import Provenance
from .reference import Mrp
from .uncertainty import Uncertainty, UncertaintyStatus


class DatasetKind(str, Enum):
    AERO_POINT = "aero_point"
    PROP_CT_CP = "prop_ct_cp"


class Role(str, Enum):
    NOMINAL = "nominal"
    CORRECTION = "correction"
    TRUTH = "truth"
    VALIDATION = "validation"


class Fidelity(str, Enum):
    """L0 handbook, L1 AeroSandbox, L2 Flow5/VSPAERO, L3 CFD/stand/CAD, L4 flight."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class Term(str, Enum):
    """Build-up term (brief D07)."""

    STATIC = "static"
    CONTROL = "control"
    RATE = "rate"
    POWER = "power"


class AxisSystem(str, Enum):
    DESIGN = "design"  # x aft, y right, z up: the flow5 and JSBSim structural axes
    BODY = "body"
    STABILITY = "stability"
    WIND = "wind"


class DatasetInput(MuasModel):
    name: str
    id: str
    units: str
    range: Optional[Tuple[float, float]] = None
    fixed: Optional[float] = None

    @model_validator(mode="after")
    def _explicit(self):
        # MGP readiness: every coordinate is stored, including held-fixed ones.
        if (self.range is None) == (self.fixed is None):
            raise ValueError(f"input {self.id!r} needs exactly one of range or fixed")
        if self.range is not None and self.range[0] > self.range[1]:
            raise ValueError(f"input {self.id!r} has an inverted range")
        return self


class DatasetOutput(MuasModel):
    name: str
    id: str
    units: str
    axis_system: Optional[AxisSystem] = None
    sign: Optional[str] = None
    is_moment: bool = False

    @model_validator(mode="after")
    def _axes(self):
        if self.axis_system is None or not self.sign:
            raise ValueError(f"output {self.id!r} must declare axis_system and sign")
        return self


class DatasetReference(MuasModel):
    s_ref_m2: float = Field(gt=0)
    b_ref_m: float = Field(gt=0)
    c_ref_m: float = Field(gt=0)
    mrp: Mrp


class Processing(MuasModel):
    binning: str
    n_raw: int = Field(ge=0)
    n_points: int = Field(ge=1)


class AeroPointManifest(MuasModel):
    dataset_id: str
    kind: Literal[DatasetKind.AERO_POINT] = DatasetKind.AERO_POINT
    role: Role
    effect: Optional[str] = None
    nominal_ref: Optional[str] = None
    config_id: str
    geometry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    term: Term = Term.STATIC
    fidelity: Fidelity
    source_tool: str
    inputs: List[DatasetInput] = Field(min_length=1)
    outputs: List[DatasetOutput] = Field(min_length=1)
    reference: DatasetReference
    uncertainty: Uncertainty
    raw_ref: Optional[str] = None
    processing: Processing
    provenance: Provenance
    data: str = "points.parquet"
    notes: List[str] = Field(default_factory=list, description="Source facts a reader needs: sign traps, mappings, doubts")

    @model_validator(mode="after")
    def _check(self):
        if self.role is Role.CORRECTION and not (self.effect and self.nominal_ref):
            raise ValueError("a correction dataset needs effect and nominal_ref")
        if self.role is not Role.CORRECTION and (self.effect or self.nominal_ref):
            raise ValueError("effect and nominal_ref belong to correction datasets only")
        ids = [i.id for i in self.inputs] + [o.id for o in self.outputs]
        if len(set(ids)) != len(ids):
            raise ValueError("input and output ids must be unique")
        u = self.uncertainty
        if u.status is UncertaintyStatus.QUANTITATIVE and u.per_point_column is None and u.sigma is None:
            raise ValueError("aero datasets need a dataset sigma or a per-point column")
        return self

    def expected_columns(self) -> List[str]:
        cols = [i.id for i in self.inputs] + [o.id for o in self.outputs]
        if self.uncertainty.per_point_column:
            cols.append(self.uncertainty.per_point_column)
        return cols


def check_points_file(manifest, base: Path) -> None:
    """Make sure the points file has the columns the manifest lists. Needs pandas and pyarrow."""
    import pandas as pd

    df = pd.read_parquet(Path(base) / manifest.data)
    missing = [c for c in manifest.expected_columns() if c not in df.columns]
    if missing:
        raise ValueError(f"points file lacks columns {missing}")
    if len(df) != manifest.processing.n_points:
        raise ValueError(f"points file has {len(df)} rows, manifest says {manifest.processing.n_points}")
