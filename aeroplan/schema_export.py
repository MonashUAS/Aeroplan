"""Export one JSON Schema file per MUAS type, committed per version (brief D15)."""
from __future__ import annotations

import json
from pathlib import Path

from . import MUAS_SCHEMA_VERSION
from .muas.aircraft import PropulsionSystemData, PropulsionTables, VisualPart
from .muas.assets import Asset
from .muas.dataset import DatasetMeta
from .muas.flight import FlightEvent, SoftwareRelease
from .muas.ic import InitialConditions
from .muas.mass import MassProperties
from .muas.mission import Mission
from .muas.node import MuasNodeExt
from .muas.reference import ReferenceData
from .muas.requirement import RequirementExt
from .muas.uncertainty import Uncertainty

TYPES = {
    "node_ext": MuasNodeExt,
    "asset": Asset,
    "dataset_meta": DatasetMeta,
    "flight_event": FlightEvent,
    "software_release": SoftwareRelease,
    "reference": ReferenceData,
    "mass_properties": MassProperties,
    "uncertainty": Uncertainty,
    "initial_conditions": InitialConditions,
    "mission": Mission,
    "requirement_ext": RequirementExt,
    "propulsion_system": PropulsionSystemData,
    "propulsion_tables": PropulsionTables,
    "visual_part": VisualPart,
}


def export_schemas(out_root: Path) -> list[Path]:
    out = Path(out_root) / f"v{MUAS_SCHEMA_VERSION}"
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in TYPES.items():
        path = out / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8",
                        newline="\n")
        written.append(path)
    return written
