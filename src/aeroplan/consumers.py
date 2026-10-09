"""Packing profiles and what each consumer of a `.muas` package needs.

| Profile         | Embedded                                         | Linked          |
|-----------------|--------------------------------------------------|-----------------|
| `aerolink`      | ADH JSON, aero and propulsion datasets, glTF      | everything else |
| `review`        | ADH JSON, glTF preview, summary plots (images)   | data and CAD    |
| `flight-record` | flight-record, segments and parameter datasets   | raw logs, video |
| `archive`       | everything that can be fetched                   | nothing         |

A small embedded dataset (INLINE_MAX bytes of canonical JSON or less) goes inline in the ADH JSON.

A consumer states what it needs. Aerolink refuses a package unless every item it needs is in it. A linked asset
that is missing on this machine does not make a package invalid.
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import adh_doc, assets

PROFILES = ("aerolink", "review", "flight-record", "archive")
INLINE_MAX = 4096
PREVIEW = {"aerolink": "required", "review": "optional", "archive": "optional", "flight-record": None}

#: what Aerolink needs to fly (muas key on an item -> what gives it)
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
#: datasets Aerolink needs (role -> what gives it)
FLIGHT_DATASETS = {
    "aero": "air_vehicle aero model (dataset role aero: DAVE-ML in ADH form)",
    "propulsion": "propeller node Ct/Cp table and throttle map (dataset role propulsion)",
}


def tier(profile: str, e: Dict[str, Any]) -> str:
    """The storage tier of a register entry in a profile: embedded or linked (inline is set by the packer)."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r} (profiles: {', '.join(PROFILES)})")
    if profile == "archive":
        return "embedded"
    if e["kind"] == "dataset":
        role = e.get("dataset_role")
        if profile == "aerolink" and role in ("aero", "propulsion"):
            return "embedded"
        if profile == "flight-record" and role in ("flight-record", "segments", "parameters"):
            return "embedded"
        return "linked"
    if profile == "review" and e["media_type"].startswith("image/"):
        return "embedded"
    return "linked"


def missing_for_flight(doc: Dict[str, Any]) -> List[str]:
    """What Aerolink needs to fly and the document lacks. Empty when the aircraft is flight ready."""
    have: Dict[str, int] = {}
    roles: Dict[str, int] = {}
    for _, item, _ in adh_doc.iter_nodes(doc):
        m = item.get("muas") or {}
        for k in m:
            have[k] = have.get(k, 0) + 1
        for d in m.get("datasets") or []:
            roles[d["role"]] = roles.get(d["role"], 0) + 1
    out = [f"{k}: {why}" for k, why in FLIGHT_ITEMS.items() if not have.get(k)]
    out += [f"dataset {k}: {why}" for k, why in FLIGHT_DATASETS.items() if not roles.get(k)]
    if have.get("control_surface", 0) and have["control_surface"] < 4:
        out.append(f"control_surface: {have['control_surface']} of 4 surfaces")
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
