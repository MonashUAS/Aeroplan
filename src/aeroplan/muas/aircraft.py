"""MUAS extension types of the aircraft ADH document.

ADH has no slot for these items, so they sit under the `muas` key of a node (rule D03). Each type says where it
comes from: the spoke that writes it, and the source file it points to (`SourceRef`, an asset of the register).
A spoke writes them. Nobody types them in.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, model_validator

from .base import MuasModel
from .reference import Position
from .units import Quantity

ASSET_ID = r"^asset:sha256:[0-9a-f]{64}$"


class SourceRef(MuasModel):
    """A pointer to a raw file that a spoke read: an asset of the register (1.10.2). The file stays linked."""

    tool: str = Field(min_length=1, description="The spoke that read the file, for example flow5")
    asset: str = Field(pattern=ASSET_ID)
    role: str = Field(min_length=1, description="What the file gave, for example 'T7 stability point'")
    note: Optional[str] = None


class PlanformSection(MuasModel):
    """One section of a lifting surface, in the flow5 convention (right half, root first)."""

    y: float = Field(description="Span station, m, from the root")
    chord: float = Field(gt=0, description="m")
    x_offset: float = Field(description="Leading-edge offset from the root leading edge, m")
    dihedral_deg: float = Field(description="Dihedral of the panel outboard of this section, deg")
    twist_deg: float = Field(description="Twist about the quarter chord, nose up positive, deg")
    foil: str = Field(min_length=1, description="Name of the foil of this section (lifting_surface.airfoil_sections)")


class Planform(MuasModel):
    """The parametric shape of a lifting surface. The ADH `geometry.lifting_surface` holds the same shape as splines."""

    surface_name: str = Field(min_length=1, description="Name of the surface in its tool, for example 'Main Wing'")
    kind: Literal["MAINWING", "SECONDWING", "ELEVATOR", "FIN", "OTHERWING"]
    position: Position = Field(description="Root leading edge, design frame")
    rx_deg: float = 0.0
    ry_deg: float = 0.0
    symmetric: bool = True
    two_sided: bool = True
    sections: List[PlanformSection] = Field(min_length=2)
    structural_mass: Optional[Quantity] = Field(None, description="Mass of the surface structure, when the tool gives it")
    source: str = Field(min_length=1)
    placeholder: bool = False

    @model_validator(mode="after")
    def _rising(self):
        ys = [s.y for s in self.sections]
        if any(b <= a for a, b in zip(ys, ys[1:])):
            raise ValueError(f"{self.surface_name}: section y must rise from root to tip")
        return self


class PointMass(MuasModel):
    """A concentrated mass of the mass model (for example a battery or a motor)."""

    tag: str = Field(min_length=1)
    mass: Quantity
    position: Position
    source: str = Field(min_length=1)
    placeholder: bool = False


class Transform(MuasModel):
    """Puts a CAD part into the design frame: each design axis is a signed CAD axis, then a shift in metres."""

    axes: List[Literal["x", "-x", "y", "-y", "z", "-z"]] = Field(min_length=3, max_length=3)
    origin_m: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)


class VisualPart(MuasModel):
    """The 3D shape of a part for a simulator view. The mesh is a raw file. The `.muas` holds its pointer and pose."""

    part: str = Field(min_length=1, description="Part name, for example 'aileron_l'")
    mesh: Optional[SourceRef] = Field(None, description="The CAD mesh, when the part comes from CAD")
    generator: Optional[Literal["planform", "tube"]] = Field(
        None, description="How a tool makes the mesh when no CAD mesh exists")
    units: str = Field("m", description="Units of the CAD mesh")
    transform: Optional[Transform] = None
    hinge: Optional[List[List[float]]] = Field(None, description="Two points of the hinge axis, design frame, m")
    tube: Optional[Dict[str, Any]] = Field(
        None, description="For generator tube: radius_m and to_instance (the item whose root quarter chord ends it)")
    material: Optional[str] = None
    source: str = Field(min_length=1)
    placeholder: bool = False

    @model_validator(mode="after")
    def _one_shape(self):
        if (self.mesh is None) == (self.generator is None):
            raise ValueError(f"visual part {self.part}: give a CAD mesh or a generator, not both and not neither")
        if self.hinge is not None and (len(self.hinge) != 2 or any(len(p) != 3 for p in self.hinge)):
            raise ValueError(f"visual part {self.part}: hinge must be two points of three numbers")
        return self


class Skin(MuasModel):
    """The outer skin of a part from CAD (for example a Creo shrinkwrap). It is a reference shape for the datum checks
    and the tool views, not the geometry of the part. The file stays on the user's machine."""

    mesh: SourceRef
    format: Literal["step_faceted", "stl"] = Field(description="step_faceted: a STEP file of flat faces, with its own "
                                                   "length unit. stl: an STL file in `units`")
    units: str = Field("m", description="Units of an STL file. A STEP file gives its own unit")
    transform: Transform
    source: str = Field(min_length=1)


class Table(MuasModel):
    """Columns of a lookup table. Every column has the same length. `units` maps each column to its units."""

    columns: Dict[str, List[float]]
    units: Dict[str, str]

    @model_validator(mode="after")
    def _shape(self):
        n = {len(v) for v in self.columns.values()}
        if len(n) != 1 or n == {0}:
            raise ValueError("every table column must have the same, non-zero length")
        if set(self.units) != set(self.columns):
            raise ValueError("units must name every column")
        return self


class PropulsionTables(MuasModel):
    """The tables of a propulsion system: a dataset of form `tables`, role propulsion."""

    prop_ctcp: Table = Field(description="Columns J, CT, CP")
    throttle_map: Table = Field(description="Columns esc_command_norm, power_fraction")

    @model_validator(mode="after")
    def _columns(self):
        if set(self.prop_ctcp.columns) != {"J", "CT", "CP"}:
            raise ValueError("prop_ctcp needs the columns J, CT and CP")
        if set(self.throttle_map.columns) != {"esc_command_norm", "power_fraction"}:
            raise ValueError("throttle_map needs the columns esc_command_norm and power_fraction")
        return self


class PropulsionSystemData(MuasModel):
    """The propulsion system that flies, from a Propalyser contract B file. Its Ct/Cp table and throttle map are a
    dataset (`PropulsionTables`, role propulsion) in `muas.datasets` of the same node."""

    system_id: str = Field(min_length=1)
    basis: str = Field(min_length=1, description="stand, vendor or mixed (contract B)")
    p_max: Quantity = Field(description="Shaft power at full command, the scale of power_fraction")
    diameter: Quantity
    blades: int = Field(ge=1)
    ixx: Quantity = Field(description="Propeller moment of inertia about the shaft")
    model: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    source: SourceRef
    placeholder: bool = False


class AeroSettings(MuasModel):
    """Hand values that shape the aero model where the analysis has no data (the stall)."""

    cl_max: float
    cl_min: float
    source: str = Field(min_length=1)
    placeholder: bool = True


class BuildRecord(MuasModel):
    """Who built the file, with which AeroPlan commit, and which spokes gave data."""

    aeroplan_commit: str
    aeroplan_dirty: bool
    built: date
    author: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    spokes: Dict[str, str] = Field(default_factory=dict, description="Spoke name -> what it gave in this build")
    placeholder_items: List[str] = Field(default_factory=list, description="Every value marked placeholder")
