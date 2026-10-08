"""MUAS extensions of an ADH `Requirement` (user answer 5, 2026-10-08: handling targets and analysis speeds are
ADH requirements). A requirement carries exactly one of these under its `muas` key:

- `mission`: a mission profile (category "mission", see mission.py).
- `target`: one design or handling target (category "handling" or "sizing"). `key` is the flat name that the
  analysis tools use (for example `short_period_zeta_min`), `bound` says how the value applies.
- `analysis_points`: the airspeeds of the linear model family (category "analysis").
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import Field, model_validator

from .base import MuasModel
from .mission import Mission


class Bound(str, Enum):
    MIN = "min"
    MAX = "max"
    TARGET = "target"


class Target(MuasModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: float
    bound: Bound
    units: str = Field(description="pint spelling, nd for a dimensionless value")
    source: str = Field(min_length=1)
    placeholder: bool = False


class AnalysisPoints(MuasModel):
    speeds_mps: List[float] = Field(min_length=1)
    source: str = Field(min_length=1)
    placeholder: bool = False

    @model_validator(mode="after")
    def _check(self):
        if any(v <= 0 for v in self.speeds_mps) or self.speeds_mps != sorted(set(self.speeds_mps)):
            raise ValueError("speeds_mps must be positive, rising and without repeats")
        return self


class RequirementExt(MuasModel):
    mission: Optional[Mission] = None
    target: Optional[Target] = None
    analysis_points: Optional[AnalysisPoints] = None

    @model_validator(mode="after")
    def _one(self):
        if sum(x is not None for x in (self.mission, self.target, self.analysis_points)) != 1:
            raise ValueError("a requirement's muas key holds exactly one of mission, target, analysis_points")
        return self


def _requirement(name: str, description: str, category: str, verification: str, acceptance: str, muas: dict,
                 source: Optional[str] = None) -> dict:
    from aircraft_data_hierarchy.requirements import Requirement

    req = {"name": name, "description": description, "category": category, "priority": "medium",
           "verification_method": verification, "status": "draft", "acceptance_criteria": acceptance, "muas": muas}
    if source:
        req["source"] = source
    RequirementExt.model_validate(muas)
    Requirement.model_validate(req)
    return req


def target_requirement(t: Target, category: str, description: str) -> dict:
    """The ADH `Requirement` that carries one target."""
    word = {"min": "at least", "max": "at most", "target": "equal to"}[t.bound.value]
    return _requirement(f"{category}:{t.key}", description, category, "analysis",
                        f"{t.key} is {word} {t.value:g} {t.units}.", {"target": t.model_dump(mode="json")}, t.source)


def analysis_requirement(a: AnalysisPoints) -> dict:
    """The ADH `Requirement` that carries the analysis airspeeds."""
    return _requirement("analysis:speeds", "Airspeeds of the linear model family (gain-scheduling study)", "analysis",
                        "analysis", "A linear model exists at each airspeed.", {"analysis_points": a.model_dump(mode="json")},
                        a.source)
