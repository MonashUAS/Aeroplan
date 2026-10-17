"""Packing profiles and what each consumer of a `.muas` package needs.

| Profile         | Embedded                                         | Linked          |
|-----------------|--------------------------------------------------|-----------------|
| `aerolink`      | ADH JSON, aero and propulsion datasets, the flight files (autopilot parameters, waypoints, geofence), glTF | everything else |
| `review`        | ADH JSON, glTF preview, summary plots (images)   | data and CAD    |
| `flight-record` | flight-record, segments and parameter datasets   | raw logs, video |
| `archive`       | everything that can be fetched                   | nothing         |

A small embedded dataset (INLINE_MAX bytes of canonical JSON or less) goes inline in the ADH JSON.

A consumer states what it needs. Aerolink refuses a package unless every item it needs is in it. A linked asset
that is missing on this machine does not make a package invalid.
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from . import adh_doc, assets

PROFILES = ("aerolink", "review", "flight-record", "archive")
INLINE_MAX = 4096
MRP_CG_TOL_M = 1e-3          # Aerolink needs MRP = nominal CG within 1 mm
#: the dataset name of the autopilot parameters of the aircraft (the ArduPilot spoke)
FLIGHT_PARAMETERS = "autopilot.parameters"
PREVIEW = {"aerolink": "required", "review": "optional", "archive": "optional", "flight-record": None}

#: what Aerolink needs to fly a fixed-wing aircraft (muas key on an item -> what gives it)
FLIGHT_ITEMS = {
    "reference": "air_vehicle muas.reference (S, b, cbar, MRP)",
    "initial_conditions": "air_vehicle muas.initial_conditions (trim speed, altitude)",
    "mass_properties": "air_vehicle muas.mass_properties",
    "propulsion_system": "propeller node muas.propulsion_system (Propalyser)",
    "propeller": "propeller node muas.propeller (installation)",
    "control_surface": "four control surfaces (aileron_l, aileron_r, elevator, rudder)",
    "autopilot": "1.2.5.10 muas.autopilot (servo map)",
    "ground_contacts": "1.2.2 muas.ground_contacts",
}
#: what Aerolink needs to fly a multirotor (reference.kind multirotor): no control surfaces, motor outputs instead
FLIGHT_ITEMS_MULTIROTOR = {
    "reference": "air_vehicle muas.reference (kind multirotor: s_ref body frontal area, b_ref, c_ref hub span, MRP)",
    "initial_conditions": "air_vehicle muas.initial_conditions (speed 0 for hover, altitude)",
    "mass_properties": "air_vehicle muas.mass_properties",
    "propulsion_system": "one item muas.propulsion_system (Propalyser), named by every lift rotor",
    "propeller": "four lift rotors, muas.propeller role lift, motor 1 to 4",
    "autopilot": "1.2.5.10 muas.autopilot (outputs motor1 to motor4 with the ESC end points)",
    "ground_contacts": "1.2.2 muas.ground_contacts",
}
#: what Aerolink would need to fly a quadplane (reference.kind quadplane). Aerolink has no quadplane contract yet, so
#: a quadplane lists `review` and `archive` only. The list is the fixed-wing one, with lift rotors on motor outputs 5 and up.
FLIGHT_ITEMS_QUADPLANE = {**FLIGHT_ITEMS,
                          "propeller": "one cruise propeller (muas.propeller role cruise) and the lift rotors "
                                       "(role lift, motor 5 and up)",
                          "autopilot": "1.2.5.10 muas.autopilot (servo map: surfaces, throttle, motor5 and up)"}
#: the items by vehicle kind (muas.reference.kind; absent means fixed_wing)
FLIGHT_ITEMS_BY_KIND = {"fixed_wing": FLIGHT_ITEMS, "multirotor": FLIGHT_ITEMS_MULTIROTOR,
                        "quadplane": FLIGHT_ITEMS_QUADPLANE}
#: datasets Aerolink needs (role -> what gives it)
FLIGHT_DATASETS = {
    "aero": "air_vehicle aero model (dataset role aero: DAVE-ML in ADH form)",
    "propulsion": "propeller node Ct/Cp table and throttle map (dataset role propulsion)",
}
MOTOR_NUMBERS = (1, 2, 3, 4)


def tier(profile: str, e: Dict[str, Any]) -> str:
    """The storage tier of a register entry in a profile: embedded or linked (inline is set by the packer)."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r} (profiles: {', '.join(PROFILES)})")
    if profile == "archive":
        return "embedded"
    if e["kind"] == "dataset":
        role = e.get("dataset_role")
        if profile == "aerolink" and role in ("aero", "propulsion", "waypoints", "geofence"):
            return "embedded"
        if profile == "aerolink" and e["name"] == FLIGHT_PARAMETERS:      # not the parameters of a past flight
            return "embedded"
        if profile == "flight-record" and role in ("flight-record", "segments", "parameters"):
            return "embedded"
        return "linked"
    if profile == "review" and e["media_type"].startswith("image/"):
        return "embedded"
    return "linked"


def vehicle_kind(doc: Dict[str, Any]) -> str:
    """fixed_wing, multirotor or quadplane: `muas.reference.kind` of the air vehicle (absent means fixed_wing)."""
    if adh_doc.has_node(doc, "1.2"):
        ref = (adh_doc.node(doc, "1.2").get("muas") or {}).get("reference") or {}
        return ref.get("kind") or "fixed_wing"
    return "fixed_wing"


def multirotor_problems(doc: Dict[str, Any]) -> List[str]:
    """What is wrong with the rotors, motor outputs and ESC end points of a multirotor. Empty when it is complete."""
    out: List[str] = []
    lift: Dict[int, Dict[str, Any]] = {}
    systems = set()
    for _, item, _ in adh_doc.iter_nodes(doc):
        m = item.get("muas") or {}
        if m.get("propulsion_system"):
            systems.add(m["propulsion_system"]["system_id"])
        pr = m.get("propeller")
        if pr and pr["role"] == "lift":
            if pr.get("motor") in lift:
                out.append(f"propeller: motor {pr['motor']} is used by two lift rotors")
            lift[pr.get("motor")] = {"instance": m["instance"], **pr}
        elif pr:
            out.append(f"propeller {m['instance']}: role {pr['role']} on a multirotor (only lift rotors)")
        if m.get("control_surface"):
            out.append(f"control_surface {m['instance']}: a multirotor has no control surfaces")
    if sorted(lift) != list(MOTOR_NUMBERS):
        out.append(f"propeller: lift rotors with motor {sorted(k for k in lift if k)} (needs {list(MOTOR_NUMBERS)})")
    for k, r in sorted(lift.items(), key=lambda kv: kv[0] or 0):
        if r.get("system") not in systems:
            out.append(f"propeller {r['instance']}: system {r.get('system')!r} is not a muas.propulsion_system system_id "
                       f"({sorted(systems) or 'none in the document'})")
        if abs(r["thrust_axis"][2] - 1.0) > 1e-6:
            out.append(f"propeller {r['instance']}: a lift rotor thrust_axis must be [0, 0, 1] (up)")
    if adh_doc.has_node(doc, "1.2.5.10"):
        ap = (adh_doc.node(doc, "1.2.5.10").get("muas") or {}).get("autopilot") or {}
        outs = {o["function"]: o for o in ap.get("outputs") or []}
        for n in MOTOR_NUMBERS:
            o = outs.get(f"motor{n}")
            if o is None:
                out.append(f"autopilot: no output motor{n}")
                continue
            if n in lift and o["targets"] != [lift[n]["instance"]]:
                out.append(f"autopilot output motor{n}: targets {o['targets']}, the rotor with motor {n} is "
                           f"{lift[n]['instance']!r}")
            if o.get("pwm_min_us") is None or o.get("pwm_max_us") is None:
                out.append(f"autopilot output motor{n}: no ESC end points (pwm_min_us, pwm_max_us): they come from "
                           "the contract B file (Propalyser spoke)")
    contacts = [c for _, item, _ in adh_doc.iter_nodes(doc) for c in (item.get("muas") or {}).get("ground_contacts") or []]
    if 0 < len(contacts) < 3:
        out.append(f"ground_contacts: {len(contacts)} contacts (needs at least 3 to stand)")
    return out


def missing_for_flight(doc: Dict[str, Any]) -> List[str]:
    """What Aerolink needs to fly and the document lacks. Empty when the aircraft is flight ready."""
    kind = vehicle_kind(doc)
    have: Dict[str, int] = {}
    roles: Dict[str, int] = {}
    for _, item, _ in adh_doc.iter_nodes(doc):
        m = item.get("muas") or {}
        for k in m:
            have[k] = have.get(k, 0) + 1
        for d in m.get("datasets") or []:
            roles[d["role"]] = roles.get(d["role"], 0) + 1
    out = [f"{k}: {why}" for k, why in FLIGHT_ITEMS_BY_KIND[kind].items() if not have.get(k)]
    out += [f"dataset {k}: {why}" for k, why in FLIGHT_DATASETS.items() if not roles.get(k)]
    if kind == "multirotor":
        out += multirotor_problems(doc)
    elif have.get("control_surface", 0) and have["control_surface"] < 4:
        out.append(f"control_surface: {have['control_surface']} of 4 surfaces")
    if adh_doc.has_node(doc, "1.2"):
        m = adh_doc.node(doc, "1.2").get("muas") or {}
        if m.get("reference") and m.get("mass_properties"):
            gap = float(np.linalg.norm(np.array(m["reference"]["mrp"]["point"]["xyz"], float)
                                       - np.array(m["mass_properties"]["cg"]["xyz"], float)))
            if gap > MRP_CG_TOL_M:
                out.append(f"muas.reference mrp: {gap * 1000:.1f} mm from the mass CG (Aerolink needs {MRP_CG_TOL_M * 1000:g} mm). "
                           "Run a new flow5 sweep of the mass model" if kind == "fixed_wing" else
                           f"muas.reference mrp: {gap * 1000:.1f} mm from the mass CG (Aerolink needs {MRP_CG_TOL_M * 1000:g} mm). "
                           "Run the SpecSheet spoke (it sets the MRP to the rolled-up CG)")
    return out


def profile_problems(acft, profile: str) -> List[str]:
    """Why the aircraft cannot be packed in this profile. Empty when it can."""
    if profile not in PROFILES:
        return [f"unknown profile {profile!r} (profiles: {', '.join(PROFILES)})"]
    out = []
    if profile not in (acft.info.get("consumers") or []):
        out.append(f"aircraft.yaml consumers does not list {profile}")
    if profile == "aerolink":
        out += missing_for_flight(acft.doc)
    if profile == "flight-record" and acft.info.get("kind") != "flight-record":
        if not any(e.get("dataset_role") == "flight-record" for e in assets.register(acft.doc, create=False)):
            out.append("no flight-record dataset in the register")
    return out
