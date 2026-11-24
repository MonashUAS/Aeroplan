"""Aerolink spoke: the `.muas` package that Aerolink flies.

    aeroplan export Aerolink <aircraft> <out>   ->  <out>/<aircraft>-<version>-aerolink.muas

The package is `aeroplan pack <aircraft> --profile aerolink`: the ADH JSON, the aero and propulsion datasets
(HDF5) and the glTF view of the parts (`preview/aircraft.glb`) are embedded. Everything else is linked. Copy the
file into Aerolink `aircraft/`.

The glTF parts come from the CAD meshes of the CREO spoke when they are on this machine, else from the ADH shapes
(see aeroplan.parts). Each glTF node holds the ADH item and, for a movable part, its hinge axis (node extras).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from aeroplan.package import pack
from aeroplan.spokes import Context

NAME = "Aerolink"


def ingest(doc: Dict[str, Any], ctx: Context):
    """Nothing to read: flight records come in through the ArduPilot spoke."""
    return None


def export(doc: Dict[str, Any], ctx: Context, out: Path) -> List[Path]:
    return [pack(ctx.acft, "aerolink", ctx.root, out)]
