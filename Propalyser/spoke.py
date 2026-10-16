"""Propalyser spoke: a contract B file (`propulsion-system` schema version 2) -> the propulsion system of the
propeller node (1.2.3.9 PropellerOrFanInstallation, `muas.propulsion_system`).

Input (git ignores it): Propalyser/work/<aircraft>/<system_id>.v2.h5, copied by hand from the Propalyser exports.
Settings (committed): Propalyser/settings/<aircraft>.yaml
    system      the system that flies (the file <system>.v2.h5 is read)
    instance    muas.instance of the propeller node. It holds the system data and the Ct/Cp dataset
    rotors      optional: the muas.instance of every propeller that the system drives (a multirotor has one system and
                four lift rotors). Each one gets `muas.propeller.system` = the system id and the diameter of the file.
                The ESC end points of the file (pwm_low, pwm_high) go into the motor outputs of the autopilot
                (node 1.2.5.10) that drive these rotors.

The file is not required: when it is not in the work folder, the spoke prints a note and the build goes on without it
(the aircraft then lacks the propulsion system and the aerolink profile refuses it).

Read with h5py only (no Propalyser code). Every `units` attribute must be a pint spelling. Another schema or version
is refused: there is no legacy reader. The file stays a raw file (a linked asset). Its Ct/Cp table and throttle
map become a dataset of role propulsion (`propulsion.<system>`) on the propeller node.
"""
from __future__ import annotations

from typing import Any, Dict

import h5py
import numpy as np

from aeroplan import adh_doc
from aeroplan.muas.units import parse_units, ureg
from aeroplan.spokes import Context

NAME = "Propalyser"
SCHEMA, VERSION = "propulsion-system", 2


def _v(x):
    if isinstance(x, bytes):
        return x.decode("utf-8")
    return x.item() if hasattr(x, "item") else x


def _attr(g, key: str, where: str):
    if key not in g.attrs:
        raise ValueError(f"{where}: the attribute {key} is missing")
    return _v(g.attrs[key])


def _col(f, group: str, col: str, where: str) -> list:
    if group not in f or col not in f[group]:
        raise ValueError(f"{where}: /{group}/{col} is missing")
    return [float(v) for v in np.asarray(f[group][col][()], float)]


def _opt(g, key, units, out, name=None):
    """Put the attribute `key` of group g into out as a quantity, when the file has it."""
    if key in g.attrs:
        out[name or key] = {"value": float(_v(g.attrs[key])), "units": units}


def _part_blocks(f, where: str) -> Dict[str, Any]:
    """The motor, ESC and battery blocks (contract B /motor, /esc, /battery). An absent attribute stays absent."""
    out: Dict[str, Any] = {}
    if "motor" in f:
        g, m = f["motor"], {}
        m["kv"] = {"value": float(_attr(g, "kv_rpm_per_V", where)), "units": "rpm/V"}
        m["r"] = {"value": float(_attr(g, "r_ohm", where)), "units": "ohm"}
        m["i0"] = {"value": float(_attr(g, "i0_A", where)), "units": "A"}
        if "chain_kappa_nd" in g.attrs:
            m["kappa"] = float(_v(g.attrs["chain_kappa_nd"]))
        for key, units, name in (("chain_r_tot_ohm", "ohm", "r_tot"), ("chain_q0_Nm", "N*m", "q0"), ("mass_kg", "kg", "mass"),
                                 ("imax_continuous_A", "A", "imax_continuous"), ("vmax_V", "V", "vmax")):
            _opt(g, key, units, m, name)
        if "pole_pairs" in g.attrs:
            m["pole_pairs"] = int(_v(g.attrs["pole_pairs"]))
        if "model" in g.attrs:
            m["model"] = str(_v(g.attrs["model"]))
        out["motor"] = m
    if "esc" in f:
        g, e = f["esc"], {}
        for key, units, name in (("pwm_low_us", "us", "pwm_low"), ("pwm_high_us", "us", "pwm_high"),
                                 ("imax_continuous_A", "A", "imax_continuous"), ("vmax_V", "V", "vmax")):
            _opt(g, key, units, e, name)
        for key in ("model", "protocol"):
            if key in g.attrs:
                e[key] = str(_v(g.attrs[key]))
        out["esc"] = e
    if "battery" in f:
        g, b = f["battery"], {}
        b["cells_s"], b["cells_p"] = int(_attr(g, "cells_s", where)), int(_attr(g, "cells_p", where))
        b["v_nominal"] = {"value": float(_attr(g, "v_nominal_V", where)), "units": "V"}
        for key, units, name in (("capacity_Ah", "A*h", "capacity"), ("cell_v_min_V", "V", "cell_v_min"),
                                 ("cell_v_max_V", "V", "cell_v_max"), ("mass_kg", "kg", "mass")):
            _opt(g, key, units, b, name)
        if "model" in g.attrs:
            b["model"] = str(_v(g.attrs["model"]))
        out["battery"] = b
    return out


def read_system(path) -> Dict[str, Any]:
    """The `PropulsionSystemData` fields of a contract B v2 file (without `source`)."""
    where = path.name
    with h5py.File(path, "r") as f:
        schema, version = _v(f.attrs.get("schema")), f.attrs.get("schema_version")
        if schema != SCHEMA or version is None or int(version) != VERSION:
            raise ValueError(f"{where}: schema {schema!r} version {version}. The spoke reads {SCHEMA} version {VERSION}")
        bad = []

        def visit(name, obj):
            if "units" in obj.attrs:
                try:
                    parse_units(str(_v(obj.attrs["units"])))
                except ValueError:
                    bad.append(f"/{name}")

        f.visititems(visit)
        if bad:
            raise ValueError(f"{where}: units not in pint spelling at {', '.join(bad)}")
        prop = f["propeller"]
        J, CT, CP = (_col(f, "prop_ctcp", c, where) for c in ("J", "CT", "CP"))
        esc, pf = _col(f, "throttle_map", "esc_command_norm", where), _col(f, "throttle_map", "power_fraction", where)
        if any(b <= a for a, b in zip(J, J[1:])):
            raise ValueError(f"{where}: /prop_ctcp J must rise")
        if esc[0] != 0.0 or esc[-1] != 1.0 or any(b <= a for a, b in zip(esc, esc[1:])):
            raise ValueError(f"{where}: /throttle_map esc_command_norm must rise from 0 to 1")
        warnings = [str(_v(w)) for w in f["warnings"][()]] if "warnings" in f else []
        return {
            "system_id": str(_attr(f, "system_id", where)), "basis": str(_attr(f, "basis", where)),
            "prop_ctcp": {"columns": {"J": J, "CT": CT, "CP": CP}, "units": {"J": "nd", "CT": "nd", "CP": "nd"}},
            "throttle_map": {"columns": {"esc_command_norm": esc, "power_fraction": pf},
                             "units": {"esc_command_norm": "nd", "power_fraction": "nd"}},
            "p_max": {"value": float(_attr(f["throttle_map"], "p_max_W", where)), "units": "W"},
            "diameter": {"value": float(_attr(prop, "diameter_m", where)), "units": "m"},
            "blades": int(_attr(prop, "blades", where)),
            "ixx": {"value": float(_attr(prop, "ixx_kgm2", where)), "units": "kg*m^2"},
            "model": str(_v(prop.attrs.get("model", ""))) or None, **_part_blocks(f, where),
            "warnings": warnings, "placeholder": bool(_attr(f, "placeholder", where))}


def ingest(doc: Dict[str, Any], ctx: Context):
    st = ctx.settings()
    if not st:
        return None
    path = ctx.work / f"{st['system']}.v2.h5"
    if not path.is_file():
        print(f"Propalyser: {path.relative_to(ctx.root).as_posix()} is not here: spoke skipped. Copy the contract B "
              f"export of the system {st['system']} into that folder by hand.")
        return None
    data = read_system(path)
    if data["system_id"] != st["system"]:
        raise ValueError(f"{path.name}: system_id {data['system_id']!r} is not {st['system']!r}")
    data["source"] = ctx.source_ref(path, f"contract B file of the propulsion system {st['system']}")
    if data["model"] is None:
        data.pop("model")
    tables = {"prop_ctcp": data.pop("prop_ctcp"), "throttle_map": data.pop("throttle_map")}
    n = adh_doc.node(doc, "1.2.3.9", create=True)
    adh_doc.muas(n, st["instance"])
    n["muas"]["propulsion_system"] = data
    ctx.add_dataset(
        n, f"propulsion.{st['system']}", tables, role="Ct/Cp table and throttle map", dataset_role="propulsion",
        derived_from=[data["source"]["asset"]],
        meta={"form": "tables", "fidelity": "L3" if data["basis"] == "stand" else "L0", "units_system": "SI",
              "model_description": {"generation_tool": "Propalyser (contract B v2)", "model_name": st["system"],
                                    **({"description": data["model"]} if data.get("model") else {})},
              "placeholder": data["placeholder"], "notes": [f"basis {data['basis']}"]})
    inst = n["muas"].get("propeller")
    if inst is not None:
        inst["diameter"] = dict(data["diameter"])
    changes = [f"{st['instance']}: propulsion system {st['system']} ({len(tables['prop_ctcp']['columns']['J'])} J points, "
               f"D {data['diameter']['value']} m, placeholder {data['placeholder']})"]
    rotors = list(st.get("rotors") or [])
    for r in rotors:
        try:
            pr = adh_doc.find(doc, r)["muas"]["propeller"]
        except (KeyError, TypeError):
            raise ValueError(f"settings rotors: {r!r} has no muas.propeller (build with the AeroSandbox seed first)") from None
        pr["system"] = data["system_id"]
        pr["diameter"] = dict(data["diameter"])
    if rotors:
        changes.append(f"{len(rotors)} rotors name the system {data['system_id']}: {', '.join(rotors)}")
        changes += _esc_end_points(doc, data, rotors, path.name)
    return changes


def _esc_end_points(doc: Dict[str, Any], data: Dict[str, Any], rotors, file_name: str):
    """The ESC end points of the contract B file into the autopilot outputs that drive `rotors` (us, whole numbers)."""
    esc = data.get("esc") or {}
    if "pwm_low" not in esc or "pwm_high" not in esc or not adh_doc.has_node(doc, "1.2.5.10"):
        return []
    ap = (adh_doc.node(doc, "1.2.5.10").get("muas") or {}).get("autopilot")
    if not ap:
        return []
    lo, hi = (round(ureg.Quantity(esc[k]["value"], esc[k]["units"]).to("us").magnitude) for k in ("pwm_low", "pwm_high"))
    n = 0
    for o in ap["outputs"]:
        if o["targets"] and all(t in rotors for t in o["targets"]):
            o["pwm_min_us"], o["pwm_max_us"] = lo, hi
            o["source"] = (f"{o['source']} ESC end points {lo} to {hi} us: {file_name} /esc pwm_low_us, pwm_high_us "
                           "(Propalyser spoke).")
            n += 1
    return [f"ESC end points {lo} to {hi} us written to {n} motor outputs of the autopilot"] if n else []
