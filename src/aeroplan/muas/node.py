"""MUAS extension of an ADH node (rule D03).

An ADH node keeps its upstream fields. All MUAS additions sit under the single key `muas`. The WBS number must
exist in upstream ADH. We never invent one.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from .aircraft import (AeroSettings, BuildRecord, Planform, PointMass, PropulsionSystemData, Skin, SourceRef, Tube,
                       VisualPart)
from .assets import Asset
from .base import MuasModel
from .control_surface import ControlSurface
from .control_system import Actuator, Autopilot
from .dataset import DatasetRef, Fidelity
from .flight import FlightEvent, SoftwareRelease
from .ground import GroundContact
from .ic import InitialConditions
from .mass import MassProperties
from .propulsion import PropellerInstallation
from .provenance import Provenance
from .reference import ReferenceData


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
    reference: Optional[ReferenceData] = None
    initial_conditions: Optional[InitialConditions] = None
    datasets: Optional[List[DatasetRef]] = Field(None, description="The datasets of this item (aero model, "
                                                 "propulsion tables): pointers into the asset register")
    aero_settings: Optional[AeroSettings] = None
    planform: Optional[Planform] = None
    point_masses: Optional[List[PointMass]] = None
    visual: Optional[List[VisualPart]] = None
    skin: Optional[Skin] = None
    tube: Optional[Tube] = Field(None, description="The inputs, source and placeholder flag of a tube body "
                                 "(geometry.body of the same item)")
    propulsion_system: Optional[PropulsionSystemData] = None
    sources: Optional[List[SourceRef]] = None
    geometry_tool: Optional[str] = Field(None, description="The spoke that wrote the geometry of this item last "
                                         "(flow5, OpenVSP). The changed tool file wins")
    assets: Optional[List[Asset]] = Field(None, description="The asset register (1.10.2 DataRepository only)")
    software_releases: Optional[List[SoftwareRelease]] = Field(None, description="1.2.9 AirVehicleSoftwareRelease only")
    flight_tests: Optional[List[FlightEvent]] = Field(None, description="1.8.1.4 FlightTests only")
    build: Optional[BuildRecord] = None


#: muas keys that belong to one WBS node only
NODE_ONLY = {"assets": "1.10.2", "software_releases": "1.2.9", "flight_tests": "1.8.1.4"}


def validate_ext(ext: Dict[str, Any], where: str, wbs: Optional[str] = None) -> MuasNodeExt:
    """Validate the `muas` key of a node or a subcomponent, with the checks that span several fields."""
    e = MuasNodeExt.model_validate(ext)
    for key, node in NODE_ONLY.items():
        if getattr(e, key) is not None and wbs != node:
            raise ValueError(f"{where}: muas.{key} belongs on the WBS node {node} only")
    if e.actuator is not None and e.control_surface is None:
        raise ValueError(f"{where}: muas.actuator needs muas.control_surface on the same node")
    if e.ground_contacts is not None:
        names = [c.name for c in e.ground_contacts]
        if len(set(names)) != len(names):
            raise ValueError(f"{where}: a ground contact name is used twice")
    if e.assets is not None:
        for key in ("id", "name"):
            vals = [getattr(a, key) for a in e.assets]
            if len(set(vals)) != len(vals):
                raise ValueError(f"{where}: an asset {key} is used twice in the register")
    if e.flight_tests is not None:
        ids = [f.event_id for f in e.flight_tests]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{where}: a flight event_id is used twice")
    return e
