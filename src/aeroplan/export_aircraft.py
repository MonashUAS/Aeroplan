"""Build the export package of contract C for one aircraft folder of the fleet-data repo (Currawong first).

Inputs, all under `<aircraft_dir>` (nothing else is read)::

  config/currawong.yaml                          hand config (reference, mass, controls, actuators, autopilot,
                                                 stall, propulsion installation, ground, visual, requirements)
  reference.json, datasets/processed/            written by `aeroplan integrate currawong`
  raw/flow5/sweeps/currawongv5_testfuse/         the ground-truth sweep: T7 point, results.json, plane XML
  raw/flow5/xml/*.dat                            the foils of the plane
  raw/propulsion/<system>.v2.h5                  the contract B file of the flying propulsion system
  raw/cad/*.stl                                  the CAD parts
  missions/*.yaml                                the missions

Output: one immutable package folder (package.build_package). Each value carries its source, and each stand-in
carries placeholder true. A check that fails stops the build: nothing is written.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml

from . import MUAS_SCHEMA_VERSION
from .adapters.flow5_geometry import read_foil, read_plane
from .aero_buildup import from_flow5, to_daveml
from .assemble import assemble_adh
from .config import canonical_json, strip_comments
from .datum import DatumReport, datum_checks
from .muas.control_system import Actuator, Autopilot
from .muas.ground import GroundContact
from .muas.ic import InitialConditions
from .muas.mission import Mission, mission_requirement
from .muas.reference import ReferenceData
from .muas.requirement import AnalysisPoints, Target, analysis_requirement, target_requirement
from .package import PackageManifest, Source, build_package, sha256_bytes
from . import visual as vis

SWEEP = "raw/flow5/sweeps/currawongv5_testfuse"
CONFIG_ID = "currawong.nominal"
EXT = {"ext_version": MUAS_SCHEMA_VERSION}
DML_STANDARD = "ANSI/AIAA S-119-2011"

#: hand-config requirement key -> (category, bound, units)
TARGETS = {
    "static_margin_min": ("handling", "min", "nd"), "static_margin_max": ("handling", "max", "nd"),
    "htail_volume": ("sizing", "target", "nd"), "vtail_volume": ("sizing", "target", "nd"),
    "bank_angle_deg": ("sizing", "target", "deg"), "bank_time_s": ("sizing", "max", "s"),
    "vne_ms": ("sizing", "target", "m/s"), "servo_safety_factor": ("sizing", "target", "nd"),
    "short_period_zeta_min": ("handling", "min", "nd"), "short_period_zeta_max": ("handling", "max", "nd"),
    "phugoid_zeta_min": ("handling", "min", "nd"), "dutch_roll_zeta_min": ("handling", "min", "nd"),
    "roll_mode_tau_max_s": ("handling", "max", "s"),
}
#: Aerolink surface name -> (instance, ADH wbs, ADH name, parent instance, JSBSim property, S-119 input, hand key)
SURFACES = (
    ("aileron_l", "1.2.2.3.3", "Ailerons", "wing_main", "fcs/left-aileron-pos-rad", "aileronDeflection", "aileron"),
    ("aileron_r", "1.2.2.3.3", "Ailerons", "wing_main", "fcs/right-aileron-pos-rad", "aileronDeflection", "aileron"),
    ("elevator", "1.2.2.4", "Empennage", "htail", "fcs/elevator-pos-rad", "elevatorDeflection", "elevator"),
    ("rudder", "1.2.2.4", "Empennage", "fin", "fcs/rudder-pos-rad", "rudderDeflection", "rudder"),
)
CONTACTS = (("NOSE", "nose_gear", "BOGEY"), ("LEFT_MAIN", "left_main", "BOGEY"), ("RIGHT_MAIN", "right_main", "BOGEY"),
            ("TAIL_SKID", "tail_skid", "STRUCTURE"), ("LEFT_TIP", "left_tip", "STRUCTURE"),
            ("RIGHT_TIP", "right_tip", "STRUCTURE"))


def _json(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def _pos(xyz) -> dict:
    return {"frame": "design", "xyz": [float(v) for v in xyz], "units": "m"}


def _node(wbs: str, name: str, instance: str, description: str, **muas) -> Dict[str, Any]:
    return {"wbs_no": wbs, "name": name, "description": description, "muas": {**EXT, "instance": instance, **muas}}


# ---------------------------------------------------------------------------------------------------------- ADH nodes
def surface_nodes(cfg: dict) -> List[Dict[str, Any]]:
    ctl, act, surf = cfg["controls"], cfg["actuators"], cfg["visual"]["surfaces"]
    actuator = Actuator(tau_s=act["servo_tau_s"], rate_limit_rad_s=math.radians(act["servo_rate_dps"]),
                        source="hand config actuators (servo_tau_s, servo_rate_dps). Origin: old Aerolink hand config",
                        placeholder=bool(act.get("placeholder", True)))
    nodes = []
    for inst, wbs, name, parent, prop, s119, key in SURFACES:
        lim = math.radians(ctl[f"{key}_max_deg"])
        cs = {"parent": parent, "eta_span": list(surf[key]["span"]), "hinge_x_over_c": surf[key]["hinge_xc"],
              "limit_min_rad": -lim, "limit_max_rad": lim, "positive_sign": "JSBSim", "s119_name": s119,
              "jsbsim_property": prop}
        nodes.append(_node(wbs, name, inst, f"Currawong {inst.replace('_', ' ')}. Limit: hand config controls."
                                            f"{key}_max_deg, a command scale (F-3).", fidelity="L0",
                           control_surface=cs, actuator=actuator.model_dump(mode="json", exclude_none=True)))
    return nodes


def ground_node(cfg: dict) -> Dict[str, Any]:
    g = cfg["ground"]
    k, c, f = g["spring_N_per_m"], g["damping_N_per_m_s"], g["structure_factor"]
    contacts = []
    for name, key, kind in CONTACTS:
        mult = f if kind == "STRUCTURE" else 1.0
        contacts.append(GroundContact(
            name=name, type=kind, position=_pos(g[key]), spring_N_per_m=k * mult, damping_N_per_m_s=c * mult,
            source=f"hand config ground.{key}" + (f", spring and damping times structure_factor {f:g}" if mult != 1 else ""),
            placeholder=bool(g.get("placeholder", True))).model_dump(mode="json"))
    return _node("1.2.2", "Airframe", "airframe", "Currawong airframe. ADH has no landing-gear WBS number: the ground "
                 "contacts sit here.", ground_contacts=contacts)


def autopilot_node(cfg: dict) -> Dict[str, Any]:
    a = cfg["autopilot"]
    src = "hand config autopilot (Aerolink settings flightgear.servo, Propalyser esc_setup)"
    ap = Autopilot(firmware=a["firmware"], board=a.get("board"),
                   outputs=[{**o, "source": src, "placeholder": bool(a.get("placeholder", True))} for o in a["outputs"]],
                   notes=["The surface PWM range, the trims and SERVOn_REVERSED of the Cube are not recorded."])
    return _node("1.2.5.10", "AutomaticFlightControl", "autopilot", "Currawong flight controller and its output map "
                 "(ground truth for SITL and the Cube)", autopilot=ap.model_dump(mode="json", exclude_none=True))


def propeller_node(cfg: dict, diameter_m: float) -> Dict[str, Any]:
    p = cfg["propulsion"]
    prop = {"role": "cruise", "hub": _pos([p["thrust_x"], p["thrust_y"], p["thrust_z"]]), "thrust_axis": [-1.0, 0.0, 0.0],
            "spin": p["spin"], "diameter": {"value": diameter_m, "units": "m"}}
    return _node("1.2.3.9", "PropellerOrFanInstallation", "prop_cruise",
                 f"Currawong cruise propeller of the system {p['system']}. Diameter: the contract B file. Hub: hand config "
                 "propulsion.thrust_xyz. Spin: hand config propulsion.spin (CAD blade pitch).", fidelity="L0", propeller=prop)


def requirement_list(cfg: dict, missions: List[dict]) -> List[dict]:
    r = cfg["requirements"]
    ph = bool(r.get("placeholder", True))
    out = list(missions)
    for key, (cat, bound, units) in TARGETS.items():
        if key not in r:
            continue
        t = Target(key=key, value=r[key], bound=bound, units=units, source=f"hand config requirements.{key}", placeholder=ph)
        out.append(target_requirement(t, cat, f"{cat.capitalize()} target {key}"))
    unknown = sorted(set(r) - set(TARGETS) - {"placeholder"})
    if unknown:
        raise ValueError(f"hand config requirements: unknown keys {unknown}. Add them to export_aircraft.TARGETS")
    ap = cfg["analysis_points"]
    out.append(analysis_requirement(AnalysisPoints(speeds_mps=ap["speeds_ms"], source="hand config analysis_points.speeds_ms",
                                                   placeholder=bool(ap.get("placeholder", True)))))
    return out


# ---------------------------------------------------------------------------------------------------------- parts
def visual_files(root: Path, cfg: dict, wing_fin, foils: Dict[str, np.ndarray]) -> Tuple[Dict[str, bytes], dict]:
    """The CAD files, the fin, the boom and visual/parts.json with an explicit hinge for each movable part."""
    v = cfg["visual"]
    units = v["cad_units"]
    files: Dict[str, bytes] = {}
    parts: Dict[str, dict] = {}
    design: Dict[str, np.ndarray] = {}
    for name, spec in v["parts"].items():
        data = (root / "raw" / "cad" / spec["file"]).read_bytes()
        files[f"visual/parts/{spec['file']}"] = data
        tri = vis.to_design(vis.read_stl(data, spec["file"]), units, spec.get("transform"))
        design[name] = tri
        entry = {"file": f"parts/{spec['file']}", "transform": spec.get("transform", {}),
                 "source": f"raw/cad/{spec['file']} with the hand config transform"}
        if name in vis.MOVABLE:
            a, b = vis.front_edge_axis(tri, vertical=name == "rudder")
            entry["hinge"] = [[round(float(c), 6) for c in a], [round(float(c), 6) for c in b]]
            entry["hinge_source"] = "front edge of the CAD mesh (AeroPlan visual.front_edge_axis)"
        parts[name] = entry

    # fin: the flow5 Fin wing from the leading edge to the rudder hinge (x of the rudder hinge line at each height)
    h0, h1 = (np.array(p) for p in parts["rudder"]["hinge"])

    def hinge_x(z):
        return float(h0[0] + (z - h0[2]) / (h1[2] - h0[2]) * (h1[0] - h0[0]))

    fin = vis.lifting_surface(wing_fin, foils, x_over_c_max=lambda y, le_x, chord: min(1.0, (hinge_x(wing_fin.position[2] + y) - le_x) / chord))
    files["visual/parts/fin.stl"] = vis.write_stl(fin, "fin from flow5 plane Fin wing, cut at the rudder hinge")
    parts["fin"] = {"file": "parts/fin.stl", "units": "m", "material": "wing",
                    "source": f"flow5 plane XML {SWEEP}/plane_with_body.xml wing Fin and its foil, cut at the rudder hinge"}
    design["fin"] = fin

    # boom: the rule of Aerolink 6f7edb7 visual/airframe.py
    fus = design["fuselage"].reshape(-1, 3)
    aft = fus[fus[:, 0] >= fus[:, 0].max() - 0.02]
    start = np.array([aft[:, 0].max() - 0.001, 0.0, aft[:, 2].mean()])
    elev = next(w for w in wing_fin_plane(root).wings if w.kind == "ELEVATOR")
    s0 = elev.sections[0]
    tail = np.array([elev.position[0] + s0.x_offset + vis.PIVOT * s0.chord, 0.0, elev.position[2]])
    boom = vis.tube(start, tail, v["boom_diameter_m"] / 2.0)
    files["visual/parts/boom.stl"] = vis.write_stl(boom, "boom tube, placeholder diameter")
    parts["boom"] = {"file": "parts/boom.stl", "units": "m", "material": "boom", "placeholder": True,
                     "source": "tube from the aft end of the fuselage mesh to the elevator root quarter chord. Diameter: "
                               "hand config visual.boom_diameter_m (placeholder). Rule of Aerolink 6f7edb7 visual/airframe.py"}
    design["boom"] = boom
    files["visual/parts.json"] = _json({"units": units, "parts": parts})
    return files, design


def wing_fin_plane(root: Path):
    return read_plane(root / SWEEP / "plane_with_body.xml")


# ---------------------------------------------------------------------------------------------------------- build
def _missions(root: Path) -> Tuple[List[dict], Dict[str, bytes]]:
    reqs, files = [], {}
    for f in sorted((root / "missions").glob("*.yaml")):
        m = Mission.model_validate(strip_comments(yaml.safe_load(f.read_text(encoding="utf-8"))))
        if m.name != f.stem:
            raise ValueError(f"{f.name}: mission name {m.name!r} differs from the file name")
        reqs.append(mission_requirement(m))
        files[f"missions/{m.name}.json"] = _json(m.model_dump(mode="json", exclude_none=True))
    return reqs, files


def _mass_items(node: dict) -> dict:
    mp = node["muas"]["mass_properties"]
    return {"items": [{"name": "air_vehicle", **mp}]}


def build_aircraft_package(root: Path, out_dir: Path, *, author: str, org: str, version: str,
                           source: Source, created: Optional[str] = None) -> Tuple[PackageManifest, DatumReport]:
    """Build the Currawong package. Returns the manifest and the datum report. A failed datum check stops the build."""
    from .integrate import _mass_node

    root = Path(root)
    if not author.strip():
        raise ValueError("author must name a person")
    created = created or date.today().isoformat()
    cfg = yaml.safe_load((root / "config" / "currawong.yaml").read_text(encoding="utf-8"))
    ref = ReferenceData.model_validate_json((root / "reference.json").read_text(encoding="utf-8"))

    # aero: T7 point + viscous polar + sweep control derivatives
    build = from_flow5(root / SWEEP, root / "datasets/processed/aero.flow5.alpha_viscous.currawong.nominal/points.parquet",
                       cfg["stall"])
    if not np.allclose(build.trim["cog"], ref.mrp.point.xyz, atol=1e-6):
        raise ValueError(f"the T7 moments are about {build.trim['cog']}, the MRP is {ref.mrp.point.xyz}: a moment "
                         "transfer is needed (not done here)")
    dml = to_daveml(build, name="Currawong aerodynamic model", author=author, org=org, created=created,
                    description=f"Currawong ({CONFIG_ID}) aero build-up from the flow5 sweep currawongv5_testfuse. "
                                "Moments about the MRP of reference.json (the nominal CG). " + " ".join(build.notes))

    # propulsion: the contract B file of the flying system, checked by the AeroPlan reader first
    system = cfg["propulsion"]["system"]
    b_file = root / "raw" / "propulsion" / f"{system}.v2.h5"
    prop_manifest = json.loads((root / f"datasets/processed/prop.ctcp.propalyser.{system}/manifest.json").read_text(encoding="utf-8"))
    if prop_manifest["provenance"]["input_sha256"] != sha256_bytes(b_file.read_bytes()):
        raise ValueError(f"datasets/processed/prop.ctcp.propalyser.{system} comes from another file than {b_file.name}: "
                         "run `aeroplan integrate currawong` first")
    import h5py

    with h5py.File(b_file, "r") as f:
        diameter = float(f["propeller"].attrs["diameter_m"])
        if str(f.attrs["system_id"]) != system:
            raise ValueError(f"{b_file.name}: system_id {f.attrs['system_id']!r} is not {system!r}")
        b_placeholder = bool(f.attrs["placeholder"])

    # ADH tree
    air = _mass_node(cfg)
    mission_reqs, mission_files = _missions(root)
    air["requirements"] = requirement_list(cfg, mission_reqs)
    nodes = [air, ground_node(cfg), _node("1.2.2.3", "Wing", "wing_main", "Currawong main wing (flow5 Main Wing)"),
             _node("1.2.2.4.1", "Stabilizer", "htail", "Currawong horizontal tail (flow5 Elevator wing)"),
             _node("1.2.2.4.1", "Stabilizer", "fin", "Currawong fin (flow5 Fin wing)"),
             *surface_nodes(cfg), propeller_node(cfg, diameter), autopilot_node(cfg)]
    adh = assemble_adh(nodes, muas_schema_version=MUAS_SCHEMA_VERSION)

    # visual parts and the datum checks
    plane = wing_fin_plane(root)
    fin_wing = plane.by_kind("FIN")
    foils = {s.foil: read_foil(root / "raw/flow5/xml", s.foil) for s in fin_wing.sections}
    vfiles, design = visual_files(root, cfg, fin_wing, foils)
    report = datum_checks(cfg, ref, plane, design, diameter, build.trim)
    if not report.ok:
        raise ValueError("datum check failed:\n" + report.text())

    rho, g = cfg["atmosphere"]["rho"], cfg["atmosphere"]["g"]
    if not math.isclose(rho, 1.225, rel_tol=1e-6):
        raise ValueError(f"hand config atmosphere.rho {rho} is not the ISA sea-level value: the IC altitude is unknown")
    ic = InitialConditions(rate_frame="local_NED", latitude_type="geodetic", attitude_sequence="3-2-1",
                           values={"speed_mps": build.trim["speed_mps"], "altitude_m": 0.0}, placeholder=False)

    files: Dict[str, bytes] = {
        "reference.json": _json(json.loads(ref.model_dump_json())),
        "adh/aircraft.adh.json": _json(adh),
        "ic/initial_conditions.json": _json(json.loads(ic.model_dump_json())),
        "dml/aero.dml": dml,
        "mass/mass_items.json": _json(_mass_items(air)),
        f"propulsion/{system}.h5": b_file.read_bytes(),
        "checks/datum.json": _json(report.as_dict()),
        **mission_files, **vfiles,
    }
    placeholders = sorted(k for k in ("mass", "controls", "actuators", "autopilot", "stall", "propulsion", "ground", "visual",
                                      "analysis_points", "requirements") if cfg[k].get("placeholder"))
    known = [f"hand config sections marked placeholder: {', '.join(placeholders)}",
             f"propulsion {system}: contract B placeholder {str(b_placeholder).lower()}",
             f"IC altitude 0 m: hand config atmosphere.rho {rho} kg/m^3 is ISA sea level (the flow5 density). g {g} in flow5",
             "placeholder coefficients: CL_basic table (stall shape)",
             "Clr and Cnp of the T7 point are small against the strip-theory estimates (finding F-10)"]
    manifest = build_package(
        Path(out_dir), files, package_id=f"aeroplan.{CONFIG_ID}.{version}", source=source, config_id=CONFIG_ID,
        fidelity_summary={"aero": "L1", "prop": prop_manifest["fidelity"], "mass": "L0"},
        frames={"design": ref.design_frame, "body": ref.body_frame, "euler": ref.euler},
        reference=json.loads(ref.model_dump_json()), standards={"dml/aero.dml": DML_STANDARD},
        datasets_used=[{"id": "aero.flow5.alpha_viscous.currawong.nominal", "role": "nominal",
                        "sha256": sha256_bytes((root / "datasets/processed/aero.flow5.alpha_viscous.currawong.nominal/points.parquet").read_bytes())},
                       {"id": f"propulsion.{system}", "role": "nominal", "sha256": sha256_bytes(b_file.read_bytes())}],
        known_limits=known, placeholder=True)
    return manifest, report
