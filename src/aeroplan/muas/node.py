"""MUAS extension of an ADH node and node validation (brief D02, D03).

An ADH node keeps its upstream fields. All MUAS additions sit under the single key `muas`.
The WBS number must exist in upstream ADH. We never invent one.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pydantic import Field

from .base import MuasModel
from .control_surface import ControlSurface
from .control_system import Actuator, Autopilot
from .dataset import Fidelity
from .ground import GroundContact
from .mass import MassProperties
from .propulsion import PropellerInstallation
from .provenance import Provenance
from .requirement import RequirementExt

_WBS_DEF = re.compile(r'wbs_no:\s*Optional\[str\]\s*=\s*Field\("([0-9.]+)"\)')


class MuasNodeExt(MuasModel):
    ext_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    instance: str = Field(min_length=1)
    fidelity: Optional[Fidelity] = None
    mass_properties: Optional[MassProperties] = None
    provenance: Optional[Provenance] = None
    control_surface: Optional[ControlSurface] = None
    propeller: Optional[PropellerInstallation] = None
    actuator: Optional[Actuator] = None
    autopilot: Optional[Autopilot] = None
    ground_contacts: Optional[List[GroundContact]] = None


@lru_cache(maxsize=1)
def adh_wbs_numbers() -> Set[str]:
    """Every WBS number defined by the upstream ADH source."""
    import aircraft_data_hierarchy as adh

    root = Path(adh.__file__).parent / "work_breakdown_structure" / "work_breakdown_structure.py"
    return set(_WBS_DEF.findall(root.read_text(encoding="utf-8")))


def validate_node(node: Dict[str, Any]) -> None:
    """Validate one node: upstream ADH Component rules, a real WBS number, and the `muas` extension."""
    from aircraft_data_hierarchy.work_breakdown_structure.airframe import Component

    wbs = node.get("wbs_no")
    if wbs not in adh_wbs_numbers():
        raise ValueError(f"wbs_no {wbs!r} is not an ADH WBS number")
    Component.model_validate(node)
    ext = node.get("muas")
    if ext is None:
        raise ValueError("node has no 'muas' key")
    ext = MuasNodeExt.model_validate(ext)
    if ext.actuator is not None and ext.control_surface is None:
        raise ValueError(f"node {ext.instance}: muas.actuator needs muas.control_surface on the same node")
    if ext.ground_contacts is not None:
        names = [c.name for c in ext.ground_contacts]
        if len(set(names)) != len(names):
            raise ValueError(f"node {ext.instance}: a ground contact name is used twice")
    for req in node.get("requirements") or []:
        if "muas" in req:
            RequirementExt.model_validate(req["muas"])
    for sub in node.get("subcomponents") or []:
        validate_node(sub)
