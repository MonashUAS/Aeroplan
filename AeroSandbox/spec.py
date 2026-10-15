"""The tool-neutral spec of the AeroSandbox worker, built from the ADH document, and the report of a run.

Units are SI. Angles are degrees where the name says deg. The design frame is x aft, y right, z up, the same as the
AeroSandbox geometry axes.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from aeroplan import adh_doc
from aeroplan.geometry import _edges, body_frames, foils_of, planform_wing
from aeroplan.spokes import Context

G0 = 9.80665                  # m/s^2, standard gravity (weight of the mass model)


def _split_planform(pf: Dict[str, Any], etas: List[float]) -> Dict[str, Any]:
    """The planform with extra sections at the span fractions etas. A new section interpolates chord, x offset and twist
    along its panel, and takes the dihedral and the foil of the panel (the inner section). A straight panel keeps its shape."""
    secs = [dict(s) for s in pf["sections"]]
    tip = secs[-1]["y"]
    for eta in sorted(set(etas)):
        y = eta * tip
        if any(abs(s["y"] - y) < 1e-9 for s in secs):
            continue
        k = max(i for i, s in enumerate(secs) if s["y"] < y)
        a, b = secs[k], secs[k + 1]
        t = (y - a["y"]) / (b["y"] - a["y"])
        new = dict(a)
        for key in ("chord", "x_offset", "twist_deg"):
            new[key] = a[key] + t * (b[key] - a[key])
        new["y"] = y
        secs.insert(k + 1, new)
    return {**pf, "sections": secs}


def _controls_of(doc: Dict[str, Any], parent: str) -> List[Dict[str, Any]]:
    """The control surfaces of a wing for AeroSandbox. A left and right pair with one shape is one antisymmetric surface."""
    groups: Dict[Tuple, Dict[str, Any]] = {}
    for _, item, _ in adh_doc.iter_nodes(doc):
        cs = (item.get("muas") or {}).get("control_surface")
        if not cs or cs["parent"] != parent:
            continue
        key = (tuple(cs["eta_span"]), cs["hinge_x_over_c"])
        g = groups.setdefault(key, {"eta": list(cs["eta_span"]), "hinge_x_over_c": cs["hinge_x_over_c"], "names": [],
                                    "sides": set()})
        g["names"].append(item["muas"]["instance"])
        g["sides"].add(cs.get("side", "both"))
    out = []
    for g in groups.values():
        pair = g["sides"] == {"left", "right"}
        name = g["names"][0].rsplit("_", 1)[0] if pair else g["names"][0]
        out.append({"name": name, "symmetric": not pair, "eta": g["eta"], "hinge_x_over_c": g["hinge_x_over_c"]})
    return out


def _surface_spec(doc: Dict[str, Any], inst: str) -> Dict[str, Any]:
    item = adh_doc.find(doc, inst)
    pf = item["muas"]["planform"]
    controls = _controls_of(doc, inst)
    pf2 = _split_planform(pf, [e for c in controls for e in c["eta"]])
    le, te = _edges(planform_wing(pf2))
    tip = pf2["sections"][-1]["y"]
    sections = []
    for sec, a, b in zip(pf2["sections"], le, te):
        here = [{"name": c["name"], "symmetric": c["symmetric"], "hinge_x_over_c": c["hinge_x_over_c"]}
                for c in controls if c["eta"][0] * tip - 1e-9 <= sec["y"] < c["eta"][1] * tip - 1e-9]
        # AeroSandbox ignores the trailing edge point: the angle of the chord line (section twist and the pitch
        # incidence ry_deg of the surface) must go in as the twist. A fin has its span along z: its twist stays.
        twist = float(sec["twist_deg"]) if pf["kind"] == "FIN" else math.degrees(math.atan2(a[2] - b[2], b[0] - a[0]))
        sections.append({"xyz_le": [float(v) for v in a], "chord": float(np.linalg.norm(b - a)),
                         "twist_deg": twist, "foil": sec["foil"], "controls": here})
    mirror = pf.get("symmetric", True) and (pf["kind"] != "FIN" or pf.get("two_sided", True))
    return {"name": inst, "mirror": bool(mirror), "sections": sections,
            "foils": {k: v.tolist() for k, v in foils_of(item).items()}}


def _value(q: Optional[Dict[str, Any]], default: Optional[float] = None) -> Optional[float]:
    return float(q["value"]) if q else default


def _sizing_output(doc: Dict[str, Any], name: str) -> Dict[str, Any]:
    air = adh_doc.node(doc, "1.2")
    for d in air.get("performance") or []:
        if d.get("name") == "sizing":
            for t in d["tools"]:
                for o in t["data_exchange"]["outputs"]:
                    if o["name"] == name:
                        return o
    raise ValueError(f"the sizing record of node 1.2 has no output {name!r}")


def bodies_of(st: Dict[str, Any]) -> List[str]:
    """The ADH items with a body that go into the airplane: `bodies` of the settings, or the older single `body`."""
    if st.get("bodies") is not None:
        return list(st["bodies"])
    return [st["body"]] if st.get("body") else []


def spec_from_doc(doc: Dict[str, Any], st: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    air = adh_doc.node(doc, "1.2")["muas"]
    ref = air["reference"]
    mp = air["mass_properties"]
    prop_item = adh_doc.find(doc, st["propeller"])["muas"]
    inst, psys = prop_item["propeller"], prop_item.get("propulsion_system")
    if psys is None or not psys.get("motor") or not psys.get("battery"):
        raise ValueError(f"{st['propeller']}: muas.propulsion_system has no motor and battery (run the Propalyser spoke)")
    m = psys["motor"]
    if m.get("kappa") is None or m.get("r_tot") is None:
        raise ValueError("the contract B file has no motor chain constants: use a Propalyser stand file of this motor")
    speed = _sizing_output(doc, st["cruise_speed_output"])
    if speed["units"] != "m/s":
        raise ValueError(f"the sizing output {speed['name']!r} has units {speed['units']!r}, not m/s")
    ref_id = next((d["ref"] for d in prop_item.get("datasets", []) if d["role"] == "propulsion"), None)
    if ref_id is None:
        raise ValueError(f"{st['propeller']}: no propulsion dataset (Ct/Cp table)")
    tables = ctx.dataset(ref_id)["prop_ctcp"]["columns"]
    point = [{"tag": p["tag"], "mass_kg": p["mass"]["value"], "xyz": list(p["position"]["xyz"]),
              "placeholder": bool(p.get("placeholder"))} for p in air.get("point_masses") or []]
    mass = {"mass_kg": mp["mass"]["value"], "cg": list(mp["cg"]["xyz"]), "inertia": mp.get("inertia"),
            "point_masses": point, "placeholder": bool(mp.get("placeholder"))}
    return {
        "name": doc.get("name", "aircraft"),
        "reference": {"s_m2": ref["s_ref"]["value"], "b_m": ref["b_ref"]["value"], "c_m": ref["c_ref"]["value"],
                      "xyz_ref": list(ref["mrp"]["point"]["xyz"])},
        "surfaces": [_surface_spec(doc, w) for w in st["wings"]],
        "fuselages": [{"name": b, "frames": [f.tolist() for f in body_frames(adh_doc.find(doc, b)["geometry"]["body"])]}
                      for b in bodies_of(st)],
        "mass": mass,
        "propulsion": {
            "hub": list(inst["hub"]["xyz"]), "thrust_axis": list(inst["thrust_axis"]),
            "diameter_m": inst["diameter"]["value"], "design": st["proptimiser_design"],
            "p_max_W": psys["p_max"]["value"], "placeholder": bool(psys.get("placeholder")),
            "motor": {"kv_rad_s_V": m["kv"]["value"], "i0_A": m["i0"]["value"], "kappa": m["kappa"],
                      "r_tot_ohm": m["r_tot"]["value"], "q0_Nm": _value(m.get("q0"), 0.0),
                      "imax_A": _value(m.get("imax_continuous")), "mass_kg": _value(m.get("mass"))},
            "esc": {k: _value(v) for k, v in (psys.get("esc") or {}).items() if isinstance(v, dict)},
            "battery": {"v_nominal_V": psys["battery"]["v_nominal"]["value"], "cells_s": psys["battery"]["cells_s"],
                        "capacity_As": _value(psys["battery"].get("capacity")),
                        "mass_kg": _value(psys["battery"].get("mass"))},
            "tables": {k: list(v) for k, v in tables.items()},
        },
        "flight": {"speed_m_s": speed["value"], "speed_basis": speed["units_basis"], "altitude_m": st["altitude_m"],
                   "weight_N": mp["mass"]["value"] * G0},
    }


def flow5_polar(doc: Dict[str, Any], ctx: Context, alphas_deg: List[float]) -> Optional[Dict[str, Any]]:
    """CL, CD and Cm of the flow5 aero model (DAVE-ML in the ADH) at the angles of attack, or None without the model."""
    from aeroplan.daveml_eval import Model

    air = adh_doc.node(doc, "1.2")["muas"]
    ref_id = next((d["ref"] for d in air.get("datasets", []) if d["role"] == "aero"), None)
    if ref_id is None:
        return None
    model = Model(ctx.dataset(ref_id))
    inputs = {v["var_id"]: 0.0 for v in model.vars.values() if v.get("is_input")}
    out: Dict[str, Any] = {"alpha_deg": list(alphas_deg), "CL": [], "CD": [], "Cm": []}
    for a in alphas_deg:
        v = model.evaluate({**inputs, "alpha": math.radians(a)})
        for key in ("CL", "CD", "Cm"):
            out[key].append(v[key])
    return out


def placeholders(spec: Dict[str, Any]) -> List[str]:
    out = []
    if spec["mass"]["placeholder"]:
        out.append(f"mass model of node 1.2 ({spec['mass']['mass_kg']:.3f} kg, CG, inertia): placeholder")
    out += [f"point mass {p['tag']}: placeholder" for p in spec["mass"]["point_masses"] if p["placeholder"]]
    if spec["propulsion"]["placeholder"]:
        out.append("propulsion system (contract B): placeholder")
    if spec["flight"]["speed_basis"] != "consistency":
        out.append(f"cruise speed {spec['flight']['speed_m_s']:g} m/s: sizing output, unit basis "
                   f"'{spec['flight']['speed_basis']}'")
    out.append("battery: nominal voltage, no internal resistance (no sourced value); the energy is the full capacity "
               "with no reserve")
    out.append("propeller airfoil: Clark-Y is an assumption (the old blade file does not store it)")
    return out


def report(spec: Dict[str, Any], results: Dict[str, Any], hashes: Dict[str, str], ph: List[str]) -> str:
    L = ["# AeroSandbox model of the aircraft", "",
         "Written by `python -m aeroplan generate AeroSandbox <aircraft>`. Nothing here goes back into the ADH data.", ""]
    g = results["geometry"]["geometry"]
    r = spec["reference"]
    L += ["## Geometry (AeroSandbox against the ADH reference)", "", "| Item | AeroSandbox | ADH | Unit |", "|---|---|---|---|",
          f"| Wing area | {g['s_m2']:.4f} | {r['s_m2']:.4f} | m^2 |", f"| Span | {g['b_m']:.4f} | {r['b_m']:.4f} | m |",
          f"| MAC | {g['mac_m']:.4f} | {r['c_m']:.4f} | m |", "",
          "AeroSandbox measures the wing area and span along the dihedral. The ADH reference is the projected value.", ""]
    ref = results["polar"].get("reference")
    if ref:
        L += ["## Polar at the cruise speed, elevator 0 (AeroSandbox AeroBuildup against flow5)", "",
              "| alpha [deg] | CL asb | CL flow5 | CD asb | CD flow5 | Cm asb | Cm flow5 |", "|---|---|---|---|---|---|---|"]
        for row, i in zip(results["polar"]["rows"], range(len(ref["alpha_deg"]))):
            L.append(f"| {row['alpha_deg']:g} | {row['CL']:.3f} | {ref['CL'][i]:.3f} | {row['CD']:.4f} | "
                     f"{ref['CD'][i]:.4f} | {row['Cm']:.3f} | {ref['Cm'][i]:.3f} |")
        L += ["", "The two models are different methods. A gap here is a finding about the models. It does not say which is right.", ""]
    t = results["cruise_trim"]["cruise_trim"]
    L += ["## Cruise trim", "", f"Level flight at {t['speed_m_s']:g} m/s, weight {t['weight_N']:.2f} N.", "",
          "| Item | Value | Unit |", "|---|---|---|"]
    for k, u in (("alpha_deg", "deg"), ("elevator_deg", "deg"), ("rpm", "rpm"), ("duty", "nd"), ("thrust_N", "N"),
                 ("drag_N", "N"), ("L_over_D", "nd"), ("p_shaft_W", "W"), ("p_bat_W", "W"), ("i_motor_A", "A"),
                 ("i_bat_A", "A"), ("chain_efficiency", "nd"), ("endurance_min", "min")):
        v = t.get(k)
        L.append(f"| {k} | {v:.4g} | {u} |" if v is not None else f"| {k} | n/a | {u} |")
    s = results["static_check"]["static_check"]
    L += ["", "## Static check against Propalyser (full command, V = 0)", "",
          "| Item | AeroSandbox | Propalyser | Unit |", "|---|---|---|---|",
          f"| Shaft power | {s['p_shaft_W']:.1f} | {s['p_max_propalyser_W']:.1f} | W |",
          f"| Shaft speed | {s['rpm']:.0f} | {s['rpm_propalyser_table_at_pmax']:.0f} (table speed at p_max) | rpm |",
          f"| Ct0 | {s['ct0_bemt']:.4f} | {s['ct0_table']:.4f} | nd |",
          f"| Cp0 | {s['cp0_bemt']:.4f} | {s['cp0_table']:.4f} | nd |",
          f"| Thrust at the same speed | {s['thrust_N']:.2f} | {s['thrust_table_same_omega_N']:.2f} | N |", "",
          "The Propalyser table is the Proptimiser curve scaled to the static test. The scale factors are in the "
          "Propalyser provenance text.", ""]
    L += ["## Inputs", "", f"Proptimiser design `{spec['propulsion']['design']}`.", ""]
    L += [f"- `{k}` sha256 {v}" for k, v in hashes.items()]
    L += ["", "## Placeholders that the results use", ""] + [f"- {p}" for p in ph]
    pm = sum(p["mass_kg"] for p in spec["mass"]["point_masses"])
    L += ["", f"The point masses add to {pm:.3f} kg. The mass model total is {spec['mass']['mass_kg']:.3f} kg.", ""]
    return "\n".join(L)
