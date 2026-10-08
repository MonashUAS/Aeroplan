"""Synthetic placeholder aircraft (brief P0 exit criterion).

EVERY number here is an arbitrary stand-in chosen to exercise the pipeline. None is aircraft data,
none comes from a textbook, and none may be used for design. The package is flagged `placeholder`.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from . import MUAS_SCHEMA_VERSION
from .assemble import assemble_adh
from .config import canonical_json
from .dml import points_to_dml
from .muas.dataset import AeroPointManifest
from .muas.ic import InitialConditions
from .muas.propulsion import PropCtCpManifest
from .muas.reference import ReferenceData
from .package import PackageManifest, Source, build_package, sha256_bytes

CONFIG = "cfg_synthetic"
CREATED = "2026-01-01T00:00:00"
GEOM_HASH = sha256_bytes(b"synthetic-geometry")
PROV = {"tool": "aeroplan.synthetic", "tool_version": "0.1.0", "author": "synthetic", "created": CREATED}

_MRP = {"config_id": CONFIG, "point": {"xyz": [0.5, 0.0, 0.0]}}
REFERENCE = {
    "s_ref": {"value": 1.0, "units": "m^2"}, "b_ref": {"value": 2.0, "units": "m"}, "c_ref": {"value": 0.5, "units": "m"},
    "nominal_cg": {"xyz": [0.5, 0.0, 0.0]}, "mrp": _MRP,
}


def _json(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def _nodes() -> List[Dict[str, Any]]:
    ext = {"ext_version": MUAS_SCHEMA_VERSION}
    mass = {"mass": {"value": 1.0, "units": "kg"}, "cg": {"xyz": [0.5, 0.0, 0.0]}, "source": "estimate", "placeholder": True}
    return [
        {"wbs_no": "1.2.2.3", "name": "Wing", "description": "synthetic wing",
         "muas": {**ext, "instance": "wing_main", "fidelity": "L0", "mass_properties": mass}},
        {"wbs_no": "1.2.3.9", "name": "PropellerOrFanInstallation", "description": "synthetic cruise propeller",
         "muas": {**ext, "instance": "prop_cruise", "fidelity": "L0",
                  "propeller": {"role": "cruise", "hub": {"xyz": [0.0, 0.0, 0.0]}, "thrust_axis": [-1.0, 0.0, 0.0],
                                "spin": "cw", "diameter": {"value": 0.25, "units": "m"}}}},
    ]


def _aero_points() -> pd.DataFrame:
    a = [-5.0, 0.0, 5.0, 10.0]
    return pd.DataFrame({"alpha": a, "beta": [0.0] * 4, "Cm": [0.1 - 0.02 * x for x in a], "Cm_sigma": [0.01] * 4})


def _prop_points() -> pd.DataFrame:
    j = [0.0, 0.2, 0.4, 0.6]
    return pd.DataFrame({"J": j, "Ct": [0.12 - 0.1 * x for x in j], "Cp": [0.06 - 0.03 * x for x in j],
                         "Ct_sigma": [0.005] * 4, "Cp_sigma": [0.003] * 4})


def _aero_manifest() -> AeroPointManifest:
    return AeroPointManifest(
        dataset_id="aero.cm_static.synthetic.1", role="nominal", config_id=CONFIG, geometry_hash=GEOM_HASH,
        fidelity="L0", source_tool="synthetic",
        inputs=[{"name": "angleOfAttack", "id": "alpha", "units": "deg", "range": [-5, 10]},
                {"name": "angleOfSideslip", "id": "beta", "units": "deg", "fixed": 0}],
        outputs=[{"name": "pitchingMomentCoefficient", "id": "Cm", "units": "nd", "axis_system": "body",
                  "sign": "nose-up positive", "is_moment": True}],
        reference={"s_ref_m2": 1.0, "b_ref_m": 2.0, "c_ref_m": 0.5, "mrp": _MRP},
        uncertainty={"status": "quantitative", "scope": "result", "basis": "synthetic stand-in value",
                     "effect": "additive", "distribution": "normal", "sigma": 0.01,
                     "per_point_column": "Cm_sigma", "method": "engineering"},
        processing={"binning": "none", "n_raw": 4, "n_points": 4}, provenance=PROV,
    )


def _prop_manifest() -> PropCtCpManifest:
    return PropCtCpManifest(
        dataset_id="prop.ctcp.synthetic.1", config_id=CONFIG, propeller_id="prop_synthetic", fidelity="L0",
        source_tool="synthetic", diameter={"value": 0.25, "units": "m"}, valid_domain="forward_flight",
        uncertainty={"status": "quantitative", "scope": "result", "basis": "synthetic stand-in value",
                     "effect": "additive", "distribution": "normal", "per_point_column": "Ct_sigma",
                     "method": "engineering"},
        columns=["J", "Ct", "Cp", "Ct_sigma", "Cp_sigma"],
        processing={"binning": "none", "n_raw": 4, "n_points": 4}, provenance=PROV,
    )


def _parquet(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def make_placeholder_package(out_dir: Path) -> PackageManifest:
    """Validate, assemble, compile DAVE-ML and write an immutable synthetic package."""
    ref = ReferenceData(**REFERENCE)
    adh = assemble_adh(_nodes(), muas_schema_version=MUAS_SCHEMA_VERSION)

    am, pm = _aero_manifest(), _prop_manifest()
    ap, pp = _aero_points(), _prop_points()
    aero_dml = points_to_dml(
        name="aero_cm_static", inputs=[i.model_dump(mode="json") for i in am.inputs],
        outputs=[o.model_dump(mode="json") for o in am.outputs], points=ap, uncertainty=am.uncertainty,
        author="synthetic", created=CREATED, ref_id="ref_aero", description="synthetic placeholder")
    prop_dml = points_to_dml(
        name="prop_ctcp", inputs=[{"id": "J", "name": "advanceRatio", "units": "nd", "range": [0.0, 0.6]}],
        outputs=[{"id": "Ct", "name": "thrustCoefficient", "units": "nd"},
                 {"id": "Cp", "name": "powerCoefficient", "units": "nd"}],
        points=pp, uncertainty=pm.uncertainty, author="synthetic", created=CREATED, ref_id="ref_prop",
        description="synthetic placeholder")
    ic = InitialConditions(rate_frame="local_NED", latitude_type="geodetic", attitude_sequence="3-2-1",
                           values={"altitude_m": 100.0, "speed_mps": 20.0}, placeholder=True)

    files = {
        "adh/aircraft.adh.json": _json(adh),
        "dml/aero.dml": aero_dml,
        "dml/propulsion.dml": prop_dml,
        "ic/initial_conditions.json": _json(json.loads(ic.model_dump_json())),
        "reference.json": _json(json.loads(ref.model_dump_json())),
        "datasets/aero.cm_static.synthetic.1/manifest.json": _json(json.loads(am.model_dump_json())),
        "datasets/aero.cm_static.synthetic.1/points.parquet": _parquet(ap),
        "datasets/prop.ctcp.synthetic.1/manifest.json": _json(json.loads(pm.model_dump_json())),
        "datasets/prop.ctcp.synthetic.1/points.parquet": _parquet(pp),
    }
    return build_package(
        Path(out_dir), files, package_id=f"synthetic.{CONFIG}.0.1.0",
        source=Source(repo="synthetic", commit="none"), config_id=CONFIG,
        fidelity_summary={"aero": "L0", "prop": "L0", "mass": "L0"},
        frames={"design": ref.design_frame, "body": ref.body_frame, "euler": ref.euler},
        reference=json.loads(ref.model_dump_json()),
        standards={"dml/aero.dml": "ANSI/AIAA S-119-2011", "dml/propulsion.dml": "ANSI/AIAA S-119-2011"},
        datasets_used=[{"id": am.dataset_id, "role": "nominal", "sha256": sha256_bytes(_parquet(ap))},
                       {"id": pm.dataset_id, "role": "nominal", "sha256": sha256_bytes(_parquet(pp))}],
        known_limits=["synthetic placeholder aircraft", "DAVE-ML not validated against the DTD"],
        placeholder=True,
    )
