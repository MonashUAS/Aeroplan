"""Prototype spoke (meetprototype.com): the published specs of a Prototype project -> ADH sizing targets, and the first
propulsion sizing from the MTOW target.

Input (git ignores it): work/prototype/<aircraft>/specs.json, the answer of `GET /projects/<project>/specs`.
`aeroplan generate Prototype <aircraft>` downloads it (needs the environment variable PROTOTYPE_TOKEN, scope
specs:read). The API is read only for specs: a person publishes a spec in the app, and this spoke only reads it.
Settings (committed): tools/prototype/settings/<aircraft>.yaml (see README.md)
    base_url, project   where the specs come from
    specs               spec slug -> {key, bound, units}: one ADH sizing target on node 1.2 for each spec
    mtow_spec           the slug of the spec that gives the design MTOW (it must be in `specs`, units of mass)
    propulsion_sizing   the assumptions of propulsion_sizing.size (optional: without it only the targets are written)

What ingest writes: ADH `Requirement` items (category "sizing", `muas.target`). The spec targets go on node 1.2
AirVehicle. The propulsion targets that propulsion_sizing derives from the MTOW go on node 1.2.3 Propulsion. Both
carry a source that starts with "Prototype". A later ingest replaces every requirement whose source starts with
"Prototype" and keeps the others. The propulsion targets are `placeholder` until `propulsion_sizing.confirmed` is true.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from aeroplan import adh_doc, propulsion_sizing
from aeroplan.muas.requirement import Target, target_requirement
from aeroplan.muas.units import parse_units, ureg
from aeroplan.spokes import Context, set_sources

NAME = "Prototype"
FILE = "specs.json"
PREFIX = "Prototype"                      # the start of the `source` of every requirement this spoke owns
TOKEN_ENV = "PROTOTYPE_TOKEN"
GENERATE_NEEDS_TREE = False               # the download works before the aircraft has a source tree


def read_specs(path: Path) -> Dict[str, Dict[str, Any]]:
    """The published specs of a saved API answer, by slug. Raises ValueError for an answer that is not usable."""
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("ok") is False:
        raise ValueError(f"{path.name}: the API answer says ok=false: {body.get('error')}")
    data = body.get("data")
    rows = data.get("specs") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError(f"{path.name}: no list of specs in the answer (expected data or data.specs)")
    out = {}
    for s in rows:
        latest = s.get("latest") or {}
        if latest.get("value") is None:
            continue                      # a spec with no published version has no value
        out[s["slug"]] = {"name": s.get("name", s["slug"]), "units": s.get("units") or "nd",
                          "value_type": s.get("valueType", "number"), **latest}
    return out


def convert(value: Any, from_units: str, to_units: str, slug: str) -> float:
    """The value of a spec in the units of its target. Refuse a value that is not a number or a unit that differs."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"spec {slug}: the value {value!r} is not a number")
    try:
        return float(ureg.Quantity(float(value), parse_units(from_units)).to(parse_units(to_units)).magnitude)
    except Exception as e:
        raise ValueError(f"spec {slug}: cannot convert {from_units!r} to {to_units!r}: {e}") from e


def _source(slug: str, spec: Dict[str, Any]) -> str:
    return f"{PREFIX} spec {slug} version {spec.get('version')} (published {spec.get('publishedAt', 'unknown')})"


def _drop_owned(item: Dict[str, Any]) -> None:
    keep = [r for r in item.get("requirements") or []
            if not str(((r.get("muas") or {}).get("target") or {}).get("source", "")).startswith(PREFIX)]
    if keep:
        item["requirements"] = keep
    else:
        item.pop("requirements", None)


def spec_targets(specs: Dict[str, Dict[str, Any]], mapping: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The ADH requirements of the mapped specs. Raises ValueError when a mapped spec is not published."""
    missing = sorted(set(mapping) - set(specs))
    if missing:
        raise ValueError(f"spec(s) not published in Prototype: {', '.join(missing)}")
    out = []
    for slug, m in mapping.items():
        s = specs[slug]
        value = convert(s["value"], s["units"], m["units"], slug)
        t = Target(key=m["key"], value=value, bound=m["bound"], units=m["units"], source=_source(slug, s))
        out.append(target_requirement(t, "sizing", f"{s['name']} (Prototype spec {slug})"))
    return out


def propulsion_targets(mtow_kg: float, mtow_source: str, st: Dict[str, Any]) -> tuple:
    """(the ADH requirements, the sizing results) of the propulsion sizing from the MTOW."""
    result = propulsion_sizing.size(propulsion_sizing.inputs_from(st, mtow_kg))
    placeholder = not st.get("confirmed", False)
    reqs = []
    for rkey, key, bound, units, text in propulsion_sizing.REQUIREMENTS:
        t = Target(key=key, value=result[rkey], bound=bound, units=units, placeholder=placeholder,
                   source=f"{PREFIX} spoke propulsion sizing from MTOW ({mtow_source})")
        reqs.append(target_requirement(t, "sizing", text))
    return reqs, result


def ingest(doc: Dict[str, Any], ctx: Context) -> Optional[List[str]]:
    path = ctx.work / FILE
    if not path.is_file():
        return None
    st = ctx.settings()
    mapping = st.get("specs") or {}
    mtow_slug = st.get("mtow_spec")
    if mtow_slug and mtow_slug not in mapping:
        raise ValueError(f"{ctx.settings_file.name}: mtow_spec {mtow_slug!r} is not in specs")
    specs = read_specs(path)
    air = adh_doc.node(doc, "1.2", create=True)
    adh_doc.muas(air, f"{ctx.aircraft}_airvehicle")
    _drop_owned(air)
    air.setdefault("requirements", []).extend(spec_targets(specs, mapping))
    set_sources(air, NAME, [ctx.source_ref(path, "published specs (Prototype API)")])
    lines = [f"{len(mapping)} spec targets on 1.2: {', '.join(m['key'] for m in mapping.values())}"]
    if st.get("propulsion_sizing"):
        if not mtow_slug:
            raise ValueError(f"{ctx.settings_file.name}: propulsion_sizing needs mtow_spec")
        mtow_kg = convert(specs[mtow_slug]["value"], specs[mtow_slug]["units"], "kg", mtow_slug)
        prop = adh_doc.node(doc, "1.2.3", create=True)
        adh_doc.muas(prop, "propulsion")
        _drop_owned(prop)
        reqs, r = propulsion_targets(mtow_kg, _source(mtow_slug, specs[mtow_slug]), st["propulsion_sizing"])
        prop.setdefault("requirements", []).extend(reqs)
        flag = "" if st["propulsion_sizing"].get("confirmed") else " (placeholder: assumptions not confirmed)"
        lines.append(f"propulsion sizing from MTOW {mtow_kg:g} kg{flag}: "
                     f"lift motor peak {r['lift_motor_thrust_peak_n']:.1f} N / {r['lift_motor_power_peak_w']:.0f} W, "
                     f"rotor {r['lift_rotor_diameter_m'] * 1000:.0f} mm, cruise {r['cruise_power_w']:.0f} W, "
                     f"battery {r['battery_energy_wh']:.0f} Wh / {r['battery_mass_kg']:.2f} kg "
                     f"({r['battery_mass_fraction'] * 100:.0f} % of MTOW)")
    return lines


def generate(doc: Optional[Dict[str, Any]], ctx: Context) -> List[Path]:
    """Download the published specs of the project into work/<aircraft>/specs.json."""
    st = ctx.settings()
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise ValueError(f"set the environment variable {TOKEN_ENV} (a Prototype API token with scope specs:read)")
    for k in ("base_url", "project"):
        if not st.get(k):
            raise ValueError(f"{ctx.settings_file.name}: {k} is missing")
    url = f"{st['base_url'].rstrip('/')}/projects/{st['project']}/specs"
    if not url.startswith("https://"):
        raise ValueError("base_url must be https")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:           # noqa: S310 (https checked above)
        body = json.loads(r.read().decode("utf-8"))
    ctx.work.mkdir(parents=True, exist_ok=True)
    path = ctx.work / FILE
    path.write_text(json.dumps(body, indent=1), encoding="utf-8")
    read_specs(path)                                              # refuse an answer that ingest cannot read
    return [path]


def describe() -> str:
    return "published specs -> sizing targets, propulsion sizing from MTOW"
