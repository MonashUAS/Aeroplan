"""Export one JSON Schema file per MUAS type, committed per version (brief D15)."""
from __future__ import annotations

import json
from pathlib import Path

from . import MUAS_SCHEMA_VERSION
from .muas.dataset import AeroPointManifest
from .muas.ic import InitialConditions
from .muas.mass import MassProperties
from .muas.mission import Mission
from .package import PackageManifest
from .muas.node import MuasNodeExt
from .muas.propulsion import PropCtCpManifest
from .muas.reference import ReferenceData
from .muas.requirement import RequirementExt
from .muas.uncertainty import Uncertainty

TYPES = {
    "reference": ReferenceData,
    "node_ext": MuasNodeExt,
    "mass_properties": MassProperties,
    "uncertainty": Uncertainty,
    "aero_point_manifest": AeroPointManifest,
    "prop_ct_cp_manifest": PropCtCpManifest,
    "initial_conditions": InitialConditions,
    "package_manifest": PackageManifest,
    "mission": Mission,
    "requirement_ext": RequirementExt,
}


def export_schemas(out_root: Path) -> list[Path]:
    out = Path(out_root) / f"v{MUAS_SCHEMA_VERSION}"
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in TYPES.items():
        path = out / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written
