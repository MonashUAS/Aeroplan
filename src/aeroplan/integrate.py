"""Currawong integration: raw artefacts in the fleet-data repo -> SSOT objects (brief section 7, steps 1 to 8).

Input: `<aircraft_dir>/raw/` (files copied by hand from the other repos) and `<aircraft_dir>/inventory_notes.yaml`.
Output, all under `<aircraft_dir>`: `config/currawong.yaml`, `reference.json`, `configs.json`, `adh/1.2_airvehicle.json`,
`datasets/processed/*`, `inventory.yaml`.

Rules: read only from `raw/` and the hand config `config/currawong.yaml` (made from the raw JSON once). Never overwrite hand-edited config. Write `placeholder` and `unverified` flags
instead of assuming a value. This module holds no path to another repository.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

from . import MUAS_SCHEMA_VERSION
from .adapters.flow5 import Flow5SweepAdapter
from .adapters.propalyser import PropalyserAdapter
from .config import canonical_json, json_to_commented_yaml
from .muas.dataset import AeroPointManifest, check_points_file
from .muas.mass import Inertia, MassProperties
from .muas.mission import Mission, mission_requirement
from .muas.node import validate_node
from .muas.provenance import Provenance
from .muas.reference import ReferenceData

CONFIG_ID = "currawong.nominal"
SWEEP = "flow5/sweeps/currawongv5_testfuse"
RAW_CONFIG = "config/currawong.json"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(obj), encoding="utf-8")


def _missions(root: Path) -> List[Dict[str, Any]]:
    """Make missions/<name>.yaml from raw/missions/<name>.json once, then load every YAML as an ADH requirement."""
    from .config import strip_comments

    out_dir = root / "missions"
    for src in sorted((root / "raw" / "missions").glob("*.json")):
        dst = out_dir / f"{src.stem}.yaml"
        if not dst.exists():
            out_dir.mkdir(parents=True, exist_ok=True)
            legacy = json.loads(src.read_text(encoding="utf-8"))
            header = "# Mission (hand YAML). Converted once from the legacy Aerolink JSON. Edit this file."
            dst.write_text(header + "\n" + json_to_commented_yaml(legacy) + "\n", encoding="utf-8")
    reqs = []
    for f in sorted(out_dir.glob("*.yaml")) if out_dir.exists() else []:
        m = Mission.model_validate(strip_comments(yaml.safe_load(f.read_text(encoding="utf-8"))))
        if m.name != f.stem:
            raise ValueError(f"{f.name}: mission name {m.name!r} differs from the file name")
        reqs.append(mission_requirement(m))
    return reqs


def _mass_node(cfg: dict) -> Dict[str, Any]:
    m = cfg["mass"]
    mp = MassProperties(
        mass={"value": m["mass"], "units": "kg"},
        cg={"xyz": m["cg"]},
        inertia=Inertia(ixx=m["Ixx"], iyy=m["Iyy"], izz=m["Izz"], ixz=m["Ixz"] * m.get("ixz_sign", 1.0),
                        unverified_products=["ixz"]),
        source="estimate",
        placeholder=bool(m.get("placeholder", False)),
        provenance=Provenance(tool="flow5 GUI T7 export of a retired plane", tool_version="unknown",
                              author="unknown (not recorded in the source)", method=m.get("_source")),
        notes=[
            "Source field (hand config): " + str(m.get("_source")),
            "How the inertia numbers were first obtained is not recorded (missing data M-03).",
            "Ixz is stored as written, times ixz_sign (1.0). Its sign convention is not verified (M-04).",
            "These values are not a weighing. The hand config marks them placeholder (M-02).",
        ],
    )
    node = {
        "wbs_no": "1.2", "name": "AirVehicle", "description": "Currawong air vehicle (whole aircraft)",
        "muas": {"ext_version": MUAS_SCHEMA_VERSION, "instance": "currawong_airvehicle",
                 "mass_properties": json.loads(mp.model_dump_json())},
    }
    validate_node(node)
    return node


def _reference(cfg: dict, mass_node: dict) -> ReferenceData:
    r, m = cfg["reference"], cfg["mass"]
    mass_sha = hashlib.sha256(canonical_json(mass_node["muas"]["mass_properties"]).encode()).hexdigest()
    return ReferenceData(
        design_frame="x_aft_y_right_z_up_m_flow5Origin",
        s_ref={"value": r["S"], "units": "m^2"}, b_ref={"value": r["b"], "units": "m"},
        c_ref={"value": r["cbar"], "units": "m"},
        nominal_cg={"xyz": m["cg"]},
        mrp={"definition": "nominal_cg", "config_id": CONFIG_ID, "point": {"xyz": m["cg"]},
             "mass_properties_sha256": mass_sha},
        placeholder_fields=["nominal_cg", "mrp"],
        notes=[
            "Origin is the flow5 origin. Its position relative to the nose datum is not known (M-01).",
            "S is implied by lift = weight at the T7 trim point. cbar is implied by (NP.x - CoG.x) / static margin. "
            "The hand config asks to confirm both in flow5 (M-21).",
            "The CG is the placeholder mass CG. The MRP follows it (user decision: MRP = nominal CG).",
        ],
    )


def _configs() -> Dict[str, Any]:
    return {
        "nominal": CONFIG_ID,
        "definition": "flow5 sweep currawongv5_testfuse (plane Currawongv5_n0012-3 with the fuselage frames of the sweep)",
        "definition_source": "user statement 2026-10-08: 'currawongv5_testfuse is the aircraft for ground truth'",
        "off_nominal_effects": [],
        "off_nominal_note": "No off-nominal effect has been named by the team (M-07).",
    }


def _inventory(root: Path) -> Dict[str, Any]:
    notes = yaml.safe_load((root / "inventory_notes.yaml").read_text(encoding="utf-8"))
    groups = {n["path"]: n for n in notes}
    files = []
    for p in sorted((root / "raw").rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        match = rel if rel in groups else next(
            (g for g in sorted(groups, key=len, reverse=True) if rel.startswith(g.rstrip("/") + "/")), None)
        files.append({"path": rel, "sha256": _sha(p), "size_bytes": p.stat().st_size,
                      "group": match or "UNCLASSIFIED"})
    unclassified = [f["path"] for f in files if f["group"] == "UNCLASSIFIED"]
    return {"files": files, "groups": notes, "unclassified": unclassified}


def integrate_currawong(root: Path, force_config: bool = False) -> Dict[str, Any]:
    root = Path(root)
    raw = root / "raw"
    cfg_yaml = root / "config" / "currawong.yaml"
    wrote_config = False
    if force_config or not cfg_yaml.exists():
        cfg = json.loads((raw / RAW_CONFIG).read_text(encoding="utf-8"))
        cfg_yaml.parent.mkdir(parents=True, exist_ok=True)
        header = ("# Currawong hand config. Converted from the legacy JSON on integration. Hand-edit this file from now on.\n"
                  "# `aeroplan integrate` never overwrites it (use --force-config). Keys with placeholder: true are estimates.\n")
        cfg_yaml.write_text(header + json_to_commented_yaml(cfg) + "\n", encoding="utf-8")
        wrote_config = True
    cfg = yaml.safe_load(cfg_yaml.read_text(encoding="utf-8"))  # the hand-edited YAML is the source from now on

    node = _mass_node(cfg)
    missions = _missions(root)
    if missions:
        node["requirements"] = missions
        validate_node(node)
    _write_json(root / "adh" / "1.2_airvehicle.json", node)
    ref = _reference(cfg, node)
    _write_json(root / "reference.json", json.loads(ref.model_dump_json()))
    _write_json(root / "configs.json", _configs())

    out = root / "datasets" / "processed"
    if out.exists():  # generated folder: rebuild it from raw every time
        import shutil

        shutil.rmtree(out)
    mass_sha = ref.mrp.mass_properties_sha256
    written: List[Path] = []
    written += Flow5SweepAdapter(CONFIG_ID, mass_sha).ingest(raw / SWEEP, out)
    skipped = []
    for h5 in sorted((raw / "propulsion").glob("*.h5")):
        try:
            written += PropalyserAdapter(CONFIG_ID).ingest(h5, out)
        except ValueError as e:  # a v1 file or a dirty export: listed, not ingested
            skipped.append(f"{h5.relative_to(root).as_posix()}: {e}")
    for m in (p for p in written if p.name == "manifest.json" and "aero." in p.parent.name):
        check_points_file(AeroPointManifest.model_validate_json(m.read_text(encoding="utf-8")), m.parent)

    inv = _inventory(root)
    (root / "inventory.yaml").write_text(
        "# Generated by `aeroplan integrate currawong`. Hand facts live in inventory_notes.yaml.\n"
        + yaml.safe_dump(inv, sort_keys=False, width=120, allow_unicode=True), encoding="utf-8")
    return {"config_written": wrote_config, "missions": [r["name"] for r in missions], "datasets": sorted({p.parent.name for p in written}),
            "skipped": skipped, "files_inventoried": len(inv["files"]), "unclassified": inv["unclassified"]}
