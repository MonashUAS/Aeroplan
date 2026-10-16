"""The multirotor seed: the ADH items of a quadcopter from the numbers of a settings file.

A multirotor starts in AeroPlan the way a fixed-wing aircraft starts from the AeroSandbox sizing output: the
AeroSandbox spoke reads `AeroSandbox/settings/<aircraft>.yaml` with `kind: multirotor` and calls `seed`. The seed
writes the structure that no other spoke knows: the four lift rotors, the motor outputs of the autopilot, the
reference data, the ground contacts and the demo shapes of the 3D view. The mass comes from the SpecSheet spoke, the
propulsion system from the Propalyser spoke, the body drag and the EMST results from the AeroSandbox worker.

Frames. The design frame is x aft, y right, z up (metres), origin at the middle of the four hubs (the body origin).
A CAD arm vector is turned into it by `design_from_cad` (CAD axes: -Z forward, +Y up, X right: x_design = Z_cad,
y_design = X_cad, z_design = Y_cad). The hub of the given arm is d * cos(angle) on each CAD axis, with no rounding.
The other hubs are its mirror images.

Rotor sense. ArduPilot gives the turn direction seen from above. A lift rotor has its thrust up, so the sense that
`muas.propeller.spin` states (looking along the thrust vector from behind the rotor, the JSBSim convention) is the view
from below: ArduPilot CCW is `cw` and ArduPilot CW is `ccw`. CW then means that the angular velocity points along the
thrust axis (right-hand rule).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

import numpy as np

from . import adh_doc

#: ArduPilot Quad X (AP_MotorsMatrix, frame class 1, type 1): motor number -> (position, turn direction seen from above)
QUAD_X = {1: ("front_right", "ccw"), 2: ("rear_left", "ccw"), 3: ("front_left", "cw"), 4: ("rear_right", "cw")}
#: position name -> signs of (x, y) in the design frame (x aft, y right)
SIGNS = {"front_right": (-1.0, 1.0), "front_left": (-1.0, -1.0), "rear_right": (1.0, 1.0), "rear_left": (1.0, -1.0)}
CAD_AXES = {"x": 0, "y": 1, "z": 2}
UNIT_UP = [0.0, 0.0, 1.0]


def spin_from_ardupilot(seen_from_above: str) -> str:
    """ArduPilot turn direction seen from above -> `muas.propeller.spin` (seen along the thrust, thrust up)."""
    if seen_from_above not in ("cw", "ccw"):
        raise ValueError(f"turn direction {seen_from_above!r} is not cw or ccw")
    return "ccw" if seen_from_above == "cw" else "cw"


def arm_in_design(arm: Dict[str, Any]) -> np.ndarray:
    """The arm vector in the design frame (m), from d and the three direction angles of the CAD frame.

    arm: distance_mm, angles_deg {x, y, z} (direction angles to the CAD axes), design_from_cad {x, y, z}: for each
    design axis the CAD axis it takes ("z", "-z", ...). No rounding."""
    d = float(arm["distance_mm"]) / 1000.0
    cad = {a: d * math.cos(math.radians(float(arm["angles_deg"][a]))) for a in "xyz"}
    out = []
    for axis in "xyz":
        src = str(arm["design_from_cad"][axis])
        out.append((-1.0 if src.startswith("-") else 1.0) * cad[src.lstrip("-")])
    return np.array(out)


def hubs(st: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """motor number -> {hub [x, y, z], position, spin_ardupilot, spin}. The arm of the settings is the hub of
    `arm.position`; the others are mirror images (x, y signs of the position name)."""
    arm = st["arm"]
    v = arm_in_design(arm)
    pos = arm["position"]
    if pos not in SIGNS:
        raise ValueError(f"arm.position {pos!r} is not one of {sorted(SIGNS)}")
    sx, sy = SIGNS[pos]
    if v[0] * sx <= 0 or v[1] * sy <= 0:
        raise ValueError(f"the arm vector {v.round(4).tolist()} (design frame) does not lie in the quadrant {pos}: "
                         "check design_from_cad and arm.position")
    motors = st.get("motors") or {n: {"position": p_, "spin_ardupilot": s_} for n, (p_, s_) in QUAD_X.items()}
    out = {}
    for n, m in motors.items():
        name, turn = m["position"], m["spin_ardupilot"]
        mx, my = SIGNS[name]
        out[int(n)] = {"hub": [float(mx * abs(v[0])), float(my * abs(v[1])), float(v[2])], "position": name,
                       "spin_ardupilot": turn, "spin": spin_from_ardupilot(turn)}
    if sorted(out) != [1, 2, 3, 4]:
        raise ValueError(f"a quadcopter needs motors 1 to 4, the settings have {sorted(out)}")
    return out


def _q(value: float, units: str) -> Dict[str, Any]:
    return {"value": float(value), "units": units}


def _pos(xyz) -> Dict[str, Any]:
    return {"frame": "design", "xyz": [float(c) for c in xyz], "units": "m"}


def instance(n: int) -> str:
    return f"prop_lift_{n}"


def _src(st: Dict[str, Any], what: str) -> str:
    return f"{st['source']}. {what}"


def seed(doc: Dict[str, Any], aircraft: str, st: Dict[str, Any]) -> List[str]:
    """Write the multirotor items into the ADH document. `st` is the `multirotor` block of the settings.

    Writes: 1.2 muas.reference and initial_conditions, 1.2.2 ground_contacts and the body and arm shapes, 1.2.3.9 the
    four lift rotors (the node and three subcomponents) with the motor and rotor shapes, 1.2.5.10 the autopilot with
    motor1 to motor4. Keeps what other spokes wrote on the same items (the propulsion system, datasets, mass)."""
    H = hubs(st)
    box = st["body_box"]
    size, centre = [float(c) for c in box["size_m"]], [float(c) for c in box.get("centre_m", [0.0, 0.0, 0.0])]
    arm_r = float(st["arm_tube"]["radius_m"])
    mot = st["motor_shape"]
    disc_d = float(st["rotor"]["diameter_m"])
    changes: List[str] = []
    hub_arr = np.array([H[n]["hub"] for n in sorted(H)])

    # 1.2 reference, initial conditions
    air = adh_doc.node(doc, "1.2", create=True)
    am = adh_doc.muas(air, f"{aircraft}_airvehicle")
    old = am.get("reference") or {}
    cg = (old.get("nominal_cg") or {"frame": "design", "xyz": [0.0, 0.0, 0.0], "units": "m"})
    mrp = old.get("mrp") or {"definition": "nominal_cg", "config_id": f"{aircraft}.nominal", "point": dict(cg)}
    s_ref = size[1] * size[2]
    am["reference"] = {
        "design_frame": "x_aft_y_right_z_up_m_bodyOrigin", "body_frame": "FRD", "euler": "3-2-1/NED", "kind": "multirotor",
        "s_ref": _q(s_ref, "m^2"), "b_ref": _q(float(np.ptp(hub_arr[:, 1])), "m"),
        "c_ref": _q(float(np.ptp(hub_arr[:, 0])), "m"), "nominal_cg": cg, "mrp": mrp, "surface_signs": {},
        "placeholder_fields": sorted(set(old.get("placeholder_fields") or []) | {"s_ref", "nominal_cg", "mrp"}),
        "notes": ["Multirotor. The design frame origin is the middle of the four hubs (the body origin). "
                  "s_ref: the frontal area of the demo body box (y times z), a placeholder. b_ref: the hub-to-hub "
                  "distance in y. c_ref: the hub-to-hub distance in x.",
                  "MRP = the CG of the mass model (SpecSheet spoke). It is a mass model value (placeholder)."]}
    am["initial_conditions"] = {
        "rate_frame": "local_NED", "latitude_type": "geodetic", "attitude_sequence": "3-2-1", "units": "SI",
        "values": {"speed_mps": 0.0, "altitude_m": float(st["initial_altitude_m"])}, "placeholder": True}
    changes.append(f"reference: kind multirotor, S {s_ref:.4f} m^2 (body box, placeholder), b {float(np.ptp(hub_arr[:, 1])):.4f} m, "
                   f"c {float(np.ptp(hub_arr[:, 0])):.4f} m; initial conditions: hover, altitude "
                   f"{st['initial_altitude_m']} m (placeholder)")

    # 1.2.3.9: four lift rotors, the node and three subcomponents
    prop_node = adh_doc.node(doc, "1.2.3.9", create=True)
    items = {}
    for n in sorted(H):
        inst = instance(n)
        if n == 1:
            item = prop_node
            adh_doc.muas(item, inst)
        else:
            subs = [s for s in prop_node.get("subcomponents") or [] if (s.get("muas") or {}).get("instance") == inst]
            if subs:
                item = subs[0]
            else:
                item = {"name": f"Lift rotor {n}", "description": f"Lift rotor {n} (ArduPilot motor {n}, "
                                                                    f"{H[n]['position'].replace('_', ' ')})"}
                adh_doc.muas(item, inst)
                adh_doc.put_subcomponent(prop_node, item)
        m = item["muas"]
        keep_system = (m.get("propeller") or {}).get("system")
        m["propeller"] = {"role": "lift", "hub": _pos(H[n]["hub"]), "thrust_axis": list(UNIT_UP), "spin": H[n]["spin"],
                          "diameter": _q(disc_d, "m"), "motor": n}
        if keep_system:
            m["propeller"]["system"] = keep_system
        hub = np.array(H[n]["hub"])
        m["visual"] = [
            {"part": f"motor_{n}", "generator": "cylinder", "material": "motor",
             "shape": {"centre": (hub - 0.5 * float(mot["length_m"]) * np.array(UNIT_UP)).tolist(), "axis": list(UNIT_UP),
                       "length_m": float(mot["length_m"]), "radius_m": float(mot["radius_m"])},
             "source": _src(st, "Demo motor can (no CAD)."), "placeholder": True},
            {"part": f"rotor_{n}", "generator": "disc", "material": "rotor",
             "shape": {"centre": hub.tolist(), "axis": list(UNIT_UP), "radius_m": 0.5 * disc_d,
                       "thickness_m": float(st["rotor"]["disc_thickness_m"]), "alpha": float(st["rotor"]["disc_alpha"])},
             "source": _src(st, "Demo rotor disc, diameter of the propeller (no CAD). Turns about the thrust axis through the hub."),
             "placeholder": True}]
        items[n] = item
    changes.append("lift rotors: " + ", ".join(f"{instance(n)} = motor {n} {H[n]['position']} hub "
                                                f"{[round(c, 4) for c in H[n]['hub']]} spin {H[n]['spin']} "
                                                f"(ArduPilot {H[n]['spin_ardupilot']} from above)" for n in sorted(H)))

    # 1.2.2 airframe: demo shapes and ground contacts
    frame = adh_doc.node(doc, "1.2.2", create=True)
    fm = adh_doc.muas(frame, "airframe")
    vis = [{"part": "body", "generator": "box", "material": "body",
            "shape": {"centre": centre, "size": size},
            "source": _src(st, "Demo body box (no CAD): the size is a stand-in, measure the frame."), "placeholder": True}]
    for n in sorted(H):
        vis.append({"part": f"arm_{n}", "generator": "tube", "material": "arm",
                    "shape": {"p0": [0.0, 0.0, 0.0], "p1": list(H[n]["hub"]), "radius_m": arm_r},
                    "source": _src(st, "Demo arm tube from the body origin to the hub (no CAD): the radius is a stand-in, "
                                       "measure the tube."), "placeholder": True})
    fm["visual"] = vis
    g = st["gear"]
    lowest = min(centre[2] - size[2] / 2, float((hub_arr[:, 2] - float(mot["length_m"])).min()))
    foot_z = lowest - float(g["leg_length_m"])
    contacts = []
    for n in sorted(H):
        sx, sy = SIGNS[H[n]["position"]]
        contacts.append({"name": "FOOT_" + {"front_right": "FR", "front_left": "FL", "rear_right": "RR",
                                           "rear_left": "RL"}[H[n]["position"]], "type": "STRUCTURE",
                         "position": _pos([sx * float(g["foot_x_m"]), sy * float(g["foot_y_m"]), foot_z]),
                         "spring_N_per_m": float(g["spring_N_per_m"]), "damping_N_per_m_s": float(g["damping_N_per_m_s"]),
                         "source": _src(st, f"Landing gear foot: stand-in, measure the gear. z = the lowest point of the "
                                            f"airframe ({lowest:.4f} m) less the leg length. Spring and damping: {g['spring_source']}"),
                         "placeholder": True})
    fm["ground_contacts"] = contacts
    changes.append(f"airframe: {len(vis)} demo shapes, {len(contacts)} ground contacts (placeholder), feet at z {foot_z:.4f} m")

    # 1.2.5.10 autopilot
    ap = adh_doc.node(doc, "1.2.5.10", create=True)
    apm = adh_doc.muas(ap, "autopilot")
    old_out = {o["channel"]: o for o in (apm.get("autopilot") or {}).get("outputs") or []}
    outs = []
    for n in sorted(H):
        o = {"channel": n, "function": f"motor{n}", "targets": [instance(n)],
             "source": _src(st, f"ArduCopter Quad X: output {n} drives motor {n} (SERVO{n}_FUNCTION {32 + n}). "
                                "The ESC end points come from the contract B file (Propalyser spoke); the .parm refines them."),
             "placeholder": True}
        for k in ("pwm_min_us", "pwm_trim_us", "pwm_max_us"):
            if old_out.get(n, {}).get(k) is not None:
                o[k] = old_out[n][k]
        outs.append(o)
    apm["autopilot"] = {"firmware": "ArduCopter", "outputs": outs,
                        "notes": ["Quad X: M1 front right CCW, M2 rear left CCW, M3 front left CW, M4 rear right CW "
                                  "(seen from above), ArduPilot AP_MotorsMatrix FRAME_CLASS 1, FRAME_TYPE 1."]}
    changes.append("autopilot: ArduCopter, outputs motor1 to motor4")
    return changes
