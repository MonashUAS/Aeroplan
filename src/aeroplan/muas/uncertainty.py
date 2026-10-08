"""Uncertainty schema.

Design basis:

- NASA-STD-7009B (approved 2024-03-05). [M&S 29]: record uncertainty in the
  input, the results and the derived quantities, and record margins or factors
  of safety with the uncertainty they cover. [M&S 28] and [M&S 34]: record the
  process and rationale. [M&S 33]: report a quantitative estimate, a
  qualitative description, or a clear statement that none is available.
- ADH / DAVE-ML (ANSI/AIAA S-119): the quantitative part maps to the ADH
  `Uncertainty` class (effect, normal_pdf, uniform_pdf, correlation). See
  `Uncertainty.to_adh`.
- MGP (AIAA 2023-1185): a per-dataset or per-point sigma and its method are the
  inputs a later Gaussian-process fit needs.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import Field, model_validator

from .base import MuasModel


class UncertaintyStatus(str, Enum):
    """[M&S 33] a, b, c."""

    QUANTITATIVE = "quantitative"
    QUALITATIVE = "qualitative"
    UNAVAILABLE = "unavailable"


class UncertaintyScope(str, Enum):
    """[M&S 29] a, b, c."""

    INPUT = "input"
    RESULT = "result"
    DERIVED = "derived"


class UncertaintyEffect(str, Enum):
    """Same values as ADH behavior.UncertaintyEffect (DAVE-ML)."""

    ADDITIVE = "additive"
    MULTIPLICATIVE = "multiplicative"
    PERCENTAGE = "percentage"
    ABSOLUTE = "absolute"


class Distribution(str, Enum):
    NORMAL = "normal"
    UNIFORM = "uniform"
    INTERVAL = "interval"  # a coverage interval from a simulation. No ADH home (ADH has normal and uniform only)


class UncertaintyMethod(str, Enum):
    REPEAT_SCATTER = "repeat_scatter"
    BINNING = "binning"
    GRID_STUDY = "grid_study"
    TOOL_SPREAD = "tool_spread"
    SYSID_COV = "sysid_cov"
    MEASUREMENT_CHAIN = "measurement_chain"
    VENDOR_SPEC = "vendor_spec"
    MONTE_CARLO = "monte_carlo"  # JCGM 101:2008, used by Propalyser
    ENGINEERING = "engineering"


class QualitativeLevel(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class SafetyFactor(MuasModel):
    """[M&S 29] b: a margin or factor of safety, with what it covers."""

    name: str
    value: float
    covers: str


class Correlation(MuasModel):
    var_id: str
    coefficient: float = Field(ge=-1.0, le=1.0)


class ScalarResult(MuasModel):
    """One result with a coverage interval, for example a Propalyser Monte Carlo output (JCGM 101:2008)."""

    median: float
    lower: float
    upper: float
    coverage: float = Field(gt=0, le=1)
    units: str = "nd"
    method: UncertaintyMethod = UncertaintyMethod.MONTE_CARLO

    @model_validator(mode="after")
    def _order(self):
        if not self.lower <= self.median <= self.upper:
            raise ValueError("need lower <= median <= upper")
        return self


class Uncertainty(MuasModel):
    status: UncertaintyStatus
    scope: UncertaintyScope
    basis: str = Field(min_length=1, description="[M&S 28]/[M&S 34]: process and rationale")
    effect: Optional[UncertaintyEffect] = None
    distribution: Optional[Distribution] = None
    num_sigmas: float = Field(1.0, gt=0, description="Sigmas that `sigma` represents (DAVE-ML numSigmas)")
    sigma: Optional[float] = Field(None, ge=0, description="Dataset-level value, in the units of the quantity")
    lower: Optional[float] = None
    upper: Optional[float] = None
    coverage: Optional[float] = Field(None, gt=0, le=1, description="Probability inside lower..upper (interval only)")
    per_point_column: Optional[str] = Field(None, description="Column in the points file that holds sigma")
    method: Optional[UncertaintyMethod] = None
    qualitative_level: Optional[QualitativeLevel] = None
    factors: List[SafetyFactor] = Field(default_factory=list)
    correlations: List[Correlation] = Field(default_factory=list)
    covariance_ref: Optional[str] = Field(None, description="File that holds a sysID covariance matrix")

    @model_validator(mode="after")
    def _check(self):
        s = self.status
        if s is UncertaintyStatus.QUANTITATIVE:
            if self.method is None or self.distribution is None or self.effect is None:
                raise ValueError("quantitative uncertainty needs method, distribution and effect")
            if self.distribution is Distribution.NORMAL:
                if self.sigma is None and self.per_point_column is None:
                    raise ValueError("normal uncertainty needs sigma or per_point_column")
            elif self.lower is None or self.upper is None or self.lower > self.upper:
                raise ValueError(f"{self.distribution.value} uncertainty needs lower <= upper")
            elif self.distribution is Distribution.INTERVAL and self.coverage is None:
                raise ValueError("an interval needs its coverage probability")
        elif s is UncertaintyStatus.QUALITATIVE:
            if self.qualitative_level is None:
                raise ValueError("qualitative uncertainty needs qualitative_level")
        elif any(v is not None for v in (self.sigma, self.lower, self.upper, self.per_point_column)):
            raise ValueError("an 'unavailable' uncertainty must not carry numbers")
        return self

    def to_adh(self):
        """Map the quantitative part to the ADH (DAVE-ML) Uncertainty class.

        Per-point sigma has no ADH home (brief D21). It exports as a companion table.
        """
        from aircraft_data_hierarchy import behavior as b

        if self.status is not UncertaintyStatus.QUANTITATIVE:
            raise ValueError("only quantitative uncertainty maps to ADH")
        if self.distribution is Distribution.INTERVAL:
            raise ValueError("an interval has no ADH (DAVE-ML) form. Keep it in the MUAS record")
        eff = b.UncertaintyEffect(self.effect.value)
        corr = [b.Correlation(var_id=c.var_id, corr_coef=c.coefficient) for c in self.correlations] or None
        if self.distribution is Distribution.NORMAL:
            bounds = [b.Bounds(value=repr(self.sigma))] if self.sigma is not None else None
            return b.Uncertainty(
                effect=eff,
                normal_pdf=b.NormalPDF(num_sigmas=self.num_sigmas, bounds=bounds, correlation=corr),
            )
        return b.Uncertainty(
            effect=eff,
            uniform_pdf=b.UniformPDF(bounds=[b.Bounds(value=repr(self.lower)), b.Bounds(value=repr(self.upper))]),
        )
