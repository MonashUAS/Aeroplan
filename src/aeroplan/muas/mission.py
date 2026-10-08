"""Missions as ADH requirements (user decision 2026-10-08: "standardise missions inside the ADH").

ADH has no mission class. A mission is an ADH `Requirement` with category "mission". The typed profile sits under the
requirement's `muas.mission` key. The item set is the one the Aerolink mission compiler used (site-relative offsets).

Positions: `ahead_m` along the take-off heading of the site, `right_m` to its right, `alt_agl_m` above ground.
The site itself (GPS point, heading) is operational data and stays in the Aerolink config.
"""
from __future__ import annotations

from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import Field, model_validator

from .base import MuasModel


class _Item(MuasModel):
    label: Optional[str] = None


class Takeoff(_Item):
    type: Literal["takeoff"]
    pitch_deg: float
    alt_agl_m: float = Field(gt=0)


class Speed(_Item):
    type: Literal["speed"]
    airspeed_ms: float = Field(gt=0)


class Waypoint(_Item):
    type: Literal["waypoint"]
    ahead_m: float
    right_m: float
    alt_agl_m: float


class Jump(_Item):
    type: Literal["jump"]
    to: str
    repeat: int = Field(ge=1)


class LoiterTurns(_Item):
    type: Literal["loiter_turns"]
    turns: float = Field(gt=0)
    radius_m: float = Field(gt=0)
    ahead_m: float
    right_m: float
    alt_agl_m: float


class LoiterToAlt(_Item):
    type: Literal["loiter_to_alt"]
    radius_m: float = Field(gt=0)
    ahead_m: float
    right_m: float
    alt_agl_m: float


class Land(_Item):
    type: Literal["land"]
    ahead_m: float
    right_m: float


MissionItem = Annotated[Union[Takeoff, Speed, Waypoint, Jump, LoiterTurns, LoiterToAlt, Land], Field(discriminator="type")]


class Mission(MuasModel):
    name: str = Field(pattern=r"^[a-z0-9_]+$")
    site: Optional[str] = Field(None, description="Site name in the Aerolink config. None: chosen at run time")
    params: Dict[str, float] = Field(default_factory=dict, description="ArduPilot parameters the mission needs")
    items: List[MissionItem] = Field(min_length=2)
    notes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self):
        if self.items[0].type != "takeoff":
            raise ValueError("a mission starts with takeoff")
        if self.items[-1].type != "land":
            raise ValueError("a mission ends with land (an RTL ending circles for ever)")
        labels = [i.label for i in self.items if i.label]
        if len(labels) != len(set(labels)):
            raise ValueError("item labels must be unique")
        for i, item in enumerate(self.items):
            if item.type == "jump":
                if item.to not in labels:
                    raise ValueError(f"jump target {item.to!r} is not a label")
                target = next(k for k, x in enumerate(self.items) if x.label == item.to)
                if target >= i:
                    raise ValueError("a jump must go back to an earlier item")
        return self


def mission_requirement(m: Mission, priority: str = "medium", status: str = "draft") -> dict:
    """The ADH `Requirement` that carries one mission. Validated against the upstream class."""
    from aircraft_data_hierarchy.requirements import Requirement

    req = {
        "name": f"mission:{m.name}",
        "description": f"Mission profile {m.name}",
        "category": "mission",
        "priority": priority,
        "verification_method": "SITL run, then flight test",
        "status": status,
        "acceptance_criteria": "The aircraft flies every item and lands. The flight ends disarmed.",
        "muas": {"mission": m.model_dump(mode="json", exclude_none=True)},
    }
    Requirement.model_validate(req)
    return req
