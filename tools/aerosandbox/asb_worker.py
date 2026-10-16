"""AeroSandbox worker. It runs in tools/aerosandbox/.venv and imports only aerosandbox, proptimiser, numpy and matplotlib.

    python asb_worker.py <job.json> <result.json>

The job names a task in "job". The result is {"ok": true, ...} or {"ok": false, "error", "trace"}.
The spoke (tools/aerosandbox/spoke.py) builds the spec from the ADH document. The worker holds the tool rules.

Spec (tool-neutral JSON, SI units, angles in degrees where the name says deg, design frame x aft, y right, z up):
    reference    s_m2, b_m, c_m, xyz_ref (the MRP)
    surfaces     name, mirror, sections [xyz_le, chord, twist_deg, foil, controls], foils {name: [[x, z], ...]}
    fuselages    [{name, frames: [[x, y, z] of the right half, top to bottom]}]: the fuselage and the tail boom
    mass         mass_kg, cg, inertia, point_masses
    propulsion   hub, thrust_axis, diameter_m, motor, esc, battery, tables, proptimiser_home, design
    flight       speed_m_s, altitude_m, weight_n

Jobs: version, chain, geometry, polar, cruise_trim, static_check.

Multirotor mode (spec["kind"] == "multirotor"), jobs multirotor_drag, emst_segments, emst_endurance, emst_sensitivity, emst_live:
    rotors       [{motor, instance, hub, thrust_axis, spin, diameter_m}]
    body         {box: {centre, size}, arms: [{p0, p1, radius_m}]}
    propulsion   diameter_m, p_max_W, motor, battery {v_nominal_V, capacity_As, cells_s}, tables {J, CT, CP}, throttle_map
    electrical   rb_ohm, rw_ohm, re_ohm, ia_A, ip_A, eta_e, discharge_fraction
    drag         S_ref_m2, CDx, CDy, CDz, k_rotor_drag_kg (the body drag of the aero dataset)
    analysis     altitude_m, climb_rate_m_s, forward_speeds_m_s, scan_max_m_s, scan_step_m_s, sensitivity_step
    live         home (a Proptimiser home folder), designs [design names] (job emst_live only)
The EMST functions (the section "EMST" below) use numpy only, so tests can import this file in any Python.
"""
from __future__ import annotations

import json
import math
import os
import sys
import traceback
from pathlib import Path

import numpy as np


# ------------------------------------------------------------------------------------------------ the electric chain
def electric_chain(torque_Nm, omega_rad_s, duty, motor, v_bus_V):
    """
    The motor and ESC chain of Propalyser (estimate/chain.py): a first-order DC motor behind an ESC that works as a
    chopper. Works on numbers and on CasADi expressions.

        I_motor = I0 + (Q + Q0) * Kv                    Kv in rad/s per volt
        V_term  = omega / (kappa * Kv) + R_tot * I_motor
        residual = duty * V_bus - V_term                (zero at the solution)
        I_bat   = duty * I_motor,  P_bat = V_bus * I_bat

    motor: kv_rad_s_V, i0_A, kappa, r_tot_ohm, q0_Nm.
    """
    kv = motor["kv_rad_s_V"]
    i_motor = motor["i0_A"] + (torque_Nm + motor.get("q0_Nm", 0.0)) * kv
    v_term = omega_rad_s / (motor["kappa"] * kv) + motor["r_tot_ohm"] * i_motor
    return {"i_motor_A": i_motor, "v_term_V": v_term, "residual_V": duty * v_bus_V - v_term,
            "i_bat_A": duty * i_motor, "p_bat_W": v_bus_V * duty * i_motor, "p_motor_in_W": v_term * i_motor}


# --------------------------------------------------------------------------------------------------- the airplane
def build_airplane(spec):
    import aerosandbox as asb

    foils = {}
    surfaces = []
    for s in spec["surfaces"]:
        xsecs = []
        for sec in s["sections"]:
            name = sec["foil"]
            if name not in foils:
                foils[name] = asb.Airfoil(name=name, coordinates=np.asarray(s["foils"][name], float))
            controls = [asb.ControlSurface(name=c["name"], symmetric=c["symmetric"], hinge_point=c["hinge_x_over_c"],
                                           trailing_edge=True, deflection=0.0) for c in sec.get("controls", [])]
            xsecs.append(asb.WingXSec(xyz_le=sec["xyz_le"], chord=sec["chord"], twist=sec["twist_deg"],
                                      airfoil=foils[name], control_surfaces=controls))
        surfaces.append(asb.Wing(name=s["name"], symmetric=bool(s["mirror"]), xsecs=xsecs))
    fuselages = []
    for body in spec.get("fuselages") or []:
        xsecs = []
        for f in body["frames"]:
            f = np.asarray(f, float)
            zmin, zmax = f[:, 2].min(), f[:, 2].max()
            xsecs.append(asb.FuselageXSec(xyz_c=[float(f[0, 0]), 0.0, float(0.5 * (zmin + zmax))],
                                          width=float(2.0 * np.abs(f[:, 1]).max()), height=float(zmax - zmin),
                                          shape=2.0))
        fuselages.append(asb.Fuselage(name=body["name"], xsecs=xsecs))
    prop = spec["propulsion"]
    propulsors = [asb.Propulsor(name="propeller", xyz_c=prop["hub"], xyz_normal=prop["thrust_axis"],
                                radius=0.5 * prop["diameter_m"])]
    ref = spec["reference"]
    return asb.Airplane(name=spec["name"], xyz_ref=ref["xyz_ref"], wings=surfaces, fuselages=fuselages,
                        propulsors=propulsors, s_ref=ref["s_m2"], b_ref=ref["b_m"], c_ref=ref["c_m"])


def build_mass(spec):
    import aerosandbox as asb
    m = spec["mass"]
    i = m.get("inertia") or {}
    return asb.MassProperties(mass=m["mass_kg"], x_cg=m["cg"][0], y_cg=m["cg"][1], z_cg=m["cg"][2],
                              Ixx=i.get("ixx", 0.0), Iyy=i.get("iyy", 0.0), Izz=i.get("izz", 0.0),
                              Ixy=i.get("ixy", 0.0), Iyz=i.get("iyz", 0.0), Ixz=i.get("ixz", 0.0))


def _with_ref(airplane, xyz_ref):
    import copy
    new = copy.copy(airplane)
    new.xyz_ref = list(xyz_ref)
    return new


def _f(x):
    return float(np.ravel(x)[0])


def _aero(airplane, speed, alpha_deg, altitude, deflections=None):
    import aerosandbox as asb
    plane = airplane.with_control_deflections(deflections) if deflections else airplane
    op = asb.OperatingPoint(atmosphere=asb.Atmosphere(altitude=altitude), velocity=speed, alpha=alpha_deg)
    return op, asb.AeroBuildup(airplane=plane, op_point=op).run()


def _motor_chain(spec):
    m, b = spec["propulsion"]["motor"], spec["propulsion"]["battery"]
    chain = dict(kv_rad_s_V=m["kv_rad_s_V"], i0_A=m["i0_A"], kappa=m["kappa"], r_tot_ohm=m["r_tot_ohm"],
                 q0_Nm=m.get("q0_Nm", 0.0))
    return chain, float(b["v_nominal_V"])


def _installed(name):
    import importlib.metadata as md
    try:
        md.version(name)
        return True
    except md.PackageNotFoundError:
        return False


def _prop_model(spec):
    if not _installed("proptimiser"):
        raise RuntimeError("Proptimiser is not installed in the AeroSandbox Python: run "
                           "`python -m aeroplan setup AeroSandbox --proptimiser <checkout>`")
    os.environ["PROPTIMISER_HOME"] = spec["propulsion"]["proptimiser_home"]
    from proptimiser.casadi_prop import PropellerModel
    from proptimiser.init import Propeller
    prop = Propeller.load(spec["propulsion"]["design"])
    return PropellerModel.from_propeller(prop, n_psi=1), prop


# ------------------------------------------------------------------------------------------------------- EMST
# Electric Multirotor Sizing Tool, segment analysis: Bershadsky, Haviland, Johnson, "Electric Multirotor UAV
# Propulsion System Sizing for Performance Prediction and Design Optimization", AIAA 2016-0581, section III.A.
#
#   Vs  = d s Vc - Id (Rb + Rw + Re + Rm)          eq. (9)   mean voltage at the motor coils
#   RPM = Kv Vs / G                                 eq. (10)  no-load speed
#   Id  = Nm (Q w / (etaM Vs) + I0) / etaE          eq. (11)  drive current
#   It  = Id + Ip + Ia                              eq. (12)  total current
#
# What differs from the paper, on purpose:
#   - The rotor load (thrust and torque against the shaft speed) comes from the CT/CP table of the propulsion dataset
#     (contract B, manufacturer basis). The paper uses a BEMT with a NACA 0015 section and names it its largest error
#     (section III.A.9).
#   - The motor and ESC chain is the Propalyser chain (electric_chain above): I_motor = I0 + (Q + Q0) Kv and
#     V_term = w / (kappa Kv) + R I_motor. It replaces the two forms Q w / (etaM Vs) and Kv Vs / G, which describe the
#     same first-order motor with an efficiency etaM. The throttle d is the duty of the ESC chopper.
#   - Rm and Re act on the current of one motor. Rb and Rw act on the bus current. The paper writes one Id for all
#     motors. For Nm = 1 the two forms are equal.
#   - Nm = N identical rotors with the same speed (a symmetric vehicle in steady flight: no trim moment is solved).
# The paper sets the thrust to the weight (hover) or, in forward flight, loops on the tilt angle until the lift of the
# body and the thrust carry the weight (section III.A.3). Here the body has drag and no lift: the tilt loop solves
#   T sin(th) = Dh,  T cos(th) = W + Fv     (Dh: aerodynamic force against the flight direction, Fv: downward part).

G0 = 9.80665                        # m/s^2, standard gravity
OR_MOTOR_MASS = (4.0499, -0.5329)   # paper eq. (1), outrunner: m_motor [g] = 10^p1 Kv^p2, Kv in rpm/V
BATT_MASS = (0.026373, 2.0499e-05)  # paper eq. (4): m_batt [g] = (p1 s + p2) C, C in mAh, 1P


def rotor_coeffs(tab, j):
    """CT and CP of the table at the advance ratio j (held at the end values outside the table)."""
    return float(np.interp(j, tab["J"], tab["CT"])), float(np.interp(j, tab["J"], tab["CP"]))


def rotor_load(n_rev_s, v_ax, m):
    """Thrust (N), shaft torque (N m), shaft power (W) and J of one rotor at n (rev/s) and axial inflow v_ax (m/s)."""
    if m.get("live") is not None:                  # a live propeller model (emst_live): see live_rotor
        return m["live"](n_rev_s, v_ax)
    d, rho = m["diameter_m"], m["rho"]
    j = v_ax / (n_rev_s * d)
    ct, cp = rotor_coeffs(m["tab"], j)
    thrust = ct * rho * n_rev_s ** 2 * d ** 4
    power = cp * rho * n_rev_s ** 3 * d ** 5
    return {"thrust_N": thrust, "torque_Nm": power / (2.0 * math.pi * n_rev_s), "p_shaft_W": power, "J": j, "CT": ct,
            "CP": cp}


def solve_speed(thrust_N, v_ax, m, n_max=500.0):
    """The rotor speed (rev/s) at which one rotor gives `thrust_N` at the axial inflow v_ax. Bisection on the first
    crossing of the thrust curve. Raises ValueError when the table cannot give that thrust below n_max.
    With a live model in m["live"] the secant method runs on the live thrust (each call is slow, so the loop is short)."""
    if m.get("live") is not None:
        return _solve_speed_live(thrust_N, v_ax, m)
    f = lambda n: rotor_load(n, v_ax, m)["thrust_N"] - thrust_N
    grid = np.geomspace(0.5, n_max, 600)
    lo = grid[0]
    for hi in grid[1:]:
        if f(hi) >= 0.0:
            if f(lo) > 0.0:
                break
            for _ in range(100):
                mid = 0.5 * (lo + hi)
                lo, hi = (mid, hi) if f(mid) < 0.0 else (lo, mid)
            return 0.5 * (lo + hi)
        lo = hi
    raise ValueError(f"the CT table gives no thrust of {thrust_N:.3f} N below {n_max:g} rev/s at an inflow of {v_ax:.3f} m/s")


def _solve_speed_live(thrust_N, v_ax, m, rtol=1e-7, max_iter=30):
    """The rotor speed (rev/s) at which the live model gives `thrust_N`. Secant method. The first guess is the table
    solution, or momentum-free scaling T = 0.05 rho n^2 D^4 when the table cannot give the thrust."""
    f = lambda n: m["live"](n, v_ax)["thrust_N"] - thrust_N
    try:
        x0 = solve_speed(thrust_N, v_ax, {**m, "live": None})
    except ValueError:
        x0 = math.sqrt(thrust_N / (0.05 * m["rho"] * m["diameter_m"] ** 4))
    f0 = f(x0)
    x1 = x0 * math.sqrt(thrust_N / (thrust_N + f0)) if thrust_N + f0 > 0.0 else 1.1 * x0
    for _ in range(max_iter):
        f1 = f(x1)
        if abs(f1) <= rtol * thrust_N:
            return x1
        if f1 == f0:
            break
        x0, f0, x1 = x1, f1, x1 - f1 * (x1 - x0) / (f1 - f0)
    raise ValueError(f"the live propeller model gives no thrust of {thrust_N:.3f} N at an inflow of {v_ax:.3f} m/s (secant method did not converge)")


def live_rotor(prop, rho):
    """A function (n rev/s, axial inflow m/s) -> rotor_load dict from the Proptimiser BEMT of one Propeller `prop`.
    Each call solves the BEMT (about 0.8 s). The model of a Propeller is built once and kept by Proptimiser."""
    from proptimiser.casadi_prop import static_and_axial

    def fn(n_rev_s, v_ax):
        r = static_and_axial(prop, n_rev_s * 60.0, v_ax, rho=rho)
        return {"thrust_N": r.thrust_N, "torque_Nm": r.torque_Nm, "p_shaft_W": r.shaft_power_W, "J": r.J, "CT": r.CT,
                "CP": r.CP}
    return fn


def live_segment(name, climb, thrust_total, fns, m):
    """One vertical segment (hover or climb) with one live model for each rotor. The rotor speed is solved with the first
    model. Every rotor is then evaluated at that speed and inflow. The electrical state uses the mean torque."""
    N = m["n_rotors"]
    if len(fns) != N:
        raise ValueError(f"{len(fns)} live rotor models for {N} rotors")
    seg = _segment(name, 0.0, climb, 0.0, thrust_total, climb, {**m, "live": fns[0]})
    loads = [fn(seg["rev_s"], climb) for fn in fns]
    mean_q = sum(r["torque_Nm"] for r in loads) / N
    el = electric_state(seg["rev_s"], mean_q, m)
    seg.update(el)
    seg["endurance_min"] = m["electrical"]["discharge_fraction"] * m["capacity_As"] / el["i_total_A"] / 60.0
    seg["rotors"] = [{"thrust_N": r["thrust_N"], "p_shaft_W": r["p_shaft_W"], "torque_Nm": r["torque_Nm"]} for r in loads]
    seg["thrust_each_N"] = sum(r["thrust_N"] for r in loads) / N
    seg["p_shaft_each_W"] = sum(r["p_shaft_W"] for r in loads) / N
    return seg


def electric_state(n_rev_s, torque_Nm, m):
    """The electrical state for N rotors at the speed n and the torque Q: eq. (9) to (12) with the Propalyser chain.
    Returns the duty, the currents, the voltages and the powers. `saturated` is True when the duty is above 1."""
    mo, e, N = m["motor"], m["electrical"], m["n_rotors"]
    omega = 2.0 * math.pi * n_rev_s
    i_m = mo["i0_A"] + (torque_Nm + mo.get("q0_Nm", 0.0)) * mo["kv_rad_s_V"]
    r_m = mo["r_tot_ohm"] + e["re_ohm"]
    v_term = omega / (mo["kappa"] * mo["kv_rad_s_V"]) + r_m * i_m
    i_aux = e["ip_A"] + e["ia_A"]
    v0 = m["v_nominal_V"] - e["rb_ohm"] * i_aux                    # the pack under the auxiliary load
    a = N * i_m / e["eta_e"] * (e["rb_ohm"] + e["rw_ohm"])         # bus voltage drop per unit duty: V_bus = v0 - a d
    # duty * V_bus = V_term  ->  a d^2 - v0 d + V_term = 0
    if a == 0.0:
        duty = v_term / v0
    else:
        disc = v0 * v0 - 4.0 * a * v_term
        if disc < 0.0:
            raise ValueError("the battery cannot deliver this load (the resistances use the whole voltage)")
        duty = (v0 - math.sqrt(disc)) / (2.0 * a)
    i_d = N * duty * i_m / e["eta_e"]
    i_t = i_d + i_aux
    v_bus = v0 - (e["rb_ohm"] + e["rw_ohm"]) * i_d
    return {"duty": duty, "saturated": bool(duty > 1.0), "i_motor_A": i_m, "i_drive_A": i_d, "i_total_A": i_t,
            "v_term_V": v_term, "v_bus_V": v_bus, "p_motor_in_W": N * v_term * i_m, "p_bus_W": v_bus * i_d,
            "p_battery_W": m["v_nominal_V"] * i_t, "p_shaft_W": N * torque_Nm * omega,
            "chain_efficiency": N * torque_Nm * omega / (m["v_nominal_V"] * i_t)}


def throttle_command(p_shaft_each_W, m):
    """The ESC command at which the static throttle map of the propulsion dataset gives this shaft power per rotor, or
    None without a map. A static map: an approximation in flight."""
    tm = m.get("throttle_map")
    if not tm or not m.get("p_max_W"):
        return None
    return float(np.interp(p_shaft_each_W / m["p_max_W"], tm["power_fraction"], tm["esc_command_norm"]))


def _segment(name, speed, climb, theta, thrust_total, v_ax, m):
    N = m["n_rotors"]
    n = solve_speed(thrust_total / N, v_ax, m)
    r = rotor_load(n, v_ax, m)
    el = electric_state(n, r["torque_Nm"], m)
    endurance_min = m["electrical"]["discharge_fraction"] * m["capacity_As"] / el["i_total_A"] / 60.0
    return {"name": name, "speed_m_s": speed, "climb_rate_m_s": climb, "tilt_deg": math.degrees(theta),
            "thrust_total_N": thrust_total, "thrust_each_N": thrust_total / N, "axial_inflow_m_s": v_ax,
            "rev_s": n, "rpm": n * 60.0, "J": r["J"], "CT": r["CT"], "CP": r["CP"], "torque_Nm": r["torque_Nm"],
            "p_shaft_each_W": r["p_shaft_W"], "esc_command_equiv": throttle_command(r["p_shaft_W"], m), **el,
            "endurance_min": endurance_min, "range_km": speed * endurance_min * 60.0 / 1000.0}


def body_force(u, v, w, n_sum, m):
    """The body drag of the aero dataset (src/aeroplan/multirotor_aero.py): forces on the body, body axes FRD."""
    d = m["drag"]
    q = 0.5 * m["rho"] * d["S_ref_m2"]
    k = d["k_rotor_drag_kg"]
    return (-q * d["CDx"] * u * abs(u) - k * n_sum * u, -q * d["CDy"] * v * abs(v) - k * n_sum * v,
            -q * d["CDz"] * w * abs(w))


def emst_hover(m):
    """Hover: T = W (paper section III.A.1)."""
    return _segment("hover", 0.0, 0.0, 0.0, m["mass_kg"] * G0, 0.0, m)


def emst_climb(m, rate):
    """Vertical climb at a steady rate: the axial inflow is the climb rate, the thrust carries the weight and the body drag."""
    fz = body_force(0.0, 0.0, -rate, 0.0, m)[2]            # w < 0 in FRD: the body moves up, the force is down
    return _segment("climb", 0.0, rate, 0.0, m["mass_kg"] * G0 + fz, rate, m)


def emst_forward(m, speed, tol=1e-12, max_iter=500):
    """Level forward flight at `speed`: the loop on the tilt angle th of the thrust axis from the vertical
    (paper section III.A.3). The body is pitched nose down by th. The rotors see the axial inflow V sin(th)."""
    if speed == 0.0:
        return emst_hover(m)
    W, N = m["mass_kg"] * G0, m["n_rotors"]
    th, n_sum = 0.0, N * solve_speed(W / N, 0.0, m)
    for _ in range(max_iter):
        u, w = speed * math.cos(th), -speed * math.sin(th)
        fx, _, fz = body_force(u, 0.0, w, n_sum, m)
        d_h = -(fx * math.cos(th) - fz * math.sin(th))               # aerodynamic force against the flight direction
        f_v = fx * math.sin(th) + fz * math.cos(th)                  # aerodynamic force downward
        th_new, thrust = math.atan2(d_h, W + f_v), math.hypot(d_h, W + f_v)
        n_new = N * solve_speed(thrust / N, speed * math.sin(th_new), m)
        done = abs(th_new - th) < tol and abs(n_new - n_sum) < 1e-9
        th, n_sum = th_new, n_new
        if done:
            break
    else:
        raise ValueError(f"the tilt loop did not converge at {speed} m/s")
    seg = _segment("forward", speed, 0.0, th, thrust, speed * math.sin(th), m)
    seg["body_drag_N"] = d_h
    return seg


def emst_full_throttle(m):
    """Static thrust at full throttle (duty 1, V = 0) with the battery sag, and the thrust-to-weight ratio."""
    mo, e, N = m["motor"], m["electrical"], m["n_rotors"]
    v0 = m["v_nominal_V"] - e["rb_ohm"] * (e["ip_A"] + e["ia_A"])

    def resid(n):
        r = rotor_load(n, 0.0, m)
        i_m = mo["i0_A"] + (r["torque_Nm"] + mo.get("q0_Nm", 0.0)) * mo["kv_rad_s_V"]
        v_bus = v0 - (e["rb_ohm"] + e["rw_ohm"]) * N * i_m / e["eta_e"]
        return v_bus - (2.0 * math.pi * n / (mo["kappa"] * mo["kv_rad_s_V"]) + (mo["r_tot_ohm"] + e["re_ohm"]) * i_m)

    lo, hi = 1.0, 500.0
    if resid(lo) <= 0.0:
        raise ValueError("the chain cannot turn the rotor at full throttle")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if resid(mid) > 0.0 else (lo, mid)
    n = 0.5 * (lo + hi)
    r = rotor_load(n, 0.0, m)
    el = electric_state(n, r["torque_Nm"], m)
    return {"rev_s": n, "rpm": n * 60.0, "thrust_each_N": r["thrust_N"], "thrust_total_N": N * r["thrust_N"],
            "thrust_to_weight": N * r["thrust_N"] / (m["mass_kg"] * G0), "p_shaft_each_W": r["p_shaft_W"],
            "i_motor_A": el["i_motor_A"], "i_total_A": el["i_total_A"], "duty_check": el["duty"]}


def emst_model(spec, rho):
    """The flat model dict of the EMST functions, from a multirotor spec and the air density (kg/m^3)."""
    p, e, d = spec["propulsion"], spec["electrical"], spec["drag"]
    mo, b = p["motor"], p["battery"]
    return {"rho": rho, "n_rotors": len(spec["rotors"]), "diameter_m": p["diameter_m"], "mass_kg": spec["mass"]["mass_kg"],
            "tab": {k: list(v) for k, v in p["tables"].items()},
            "motor": {**{k: mo[k] for k in ("kv_rad_s_V", "i0_A", "kappa", "r_tot_ohm")}, "q0_Nm": mo.get("q0_Nm", 0.0)},
            "v_nominal_V": b["v_nominal_V"], "capacity_As": b["capacity_As"], "electrical": dict(e), "drag": dict(d),
            "throttle_map": p.get("throttle_map"), "p_max_W": p.get("p_max_W")}


def emst_scan(m, v_max, step):
    """Hover and forward flight from 0 to v_max (m/s). The best speeds for endurance and range (paper section III.A.4)."""
    rows = [emst_forward(m, float(v)) for v in np.arange(0.0, v_max + 0.5 * step, step)]
    return {"rows": rows, "best_endurance": max(rows, key=lambda r: r["endurance_min"]),
            "best_range": max(rows, key=lambda r: r["range_km"])}


def motor_mass_kg(kv_rpm_per_V):
    return 10.0 ** OR_MOTOR_MASS[0] * kv_rpm_per_V ** OR_MOTOR_MASS[1] / 1000.0


def emst_sensitivity(m, cells_s, step=0.01):
    """Central differences of the hover endurance (min) with the motor Kv, the rotor diameter, the mass and the battery
    capacity (paper section III.A.5): the analyser runs again with x(1 + h) and x(1 - h). The Kv change moves the
    motor mass by eq. (1) and the capacity change moves the battery mass by eq. (4); the diameter change moves no mass
    (the constant p3 of eq. (5) is not in the source text)."""
    import copy

    base = emst_hover(m)["endurance_min"]
    out = {"base_endurance_min": base, "step": step, "parameters": {}}

    def run(name, x0, change):
        ends = []
        for sgn in (+1.0, -1.0):
            mm = copy.deepcopy(m)
            change(mm, x0 * (1.0 + sgn * step), x0)
            ends.append(emst_hover(mm)["endurance_min"])
        d_dx = (ends[0] - ends[1]) / (2.0 * step * x0)
        out["parameters"][name] = {"x0": x0, "d_endurance_min_per_unit": d_dx, "percent_per_percent": d_dx * x0 / base}

    def kv(mm, x, x0):
        mm["motor"]["kv_rad_s_V"] = x * 2.0 * math.pi / 60.0
        mm["mass_kg"] += mm["n_rotors"] * (motor_mass_kg(x) - motor_mass_kg(x0))

    def diameter(mm, x, x0):
        mm["diameter_m"] = x

    def mass(mm, x, x0):
        mm["mass_kg"] = x

    def capacity(mm, x, x0):                      # x in A s; 1 mAh = 3.6 A s
        mm["capacity_As"] = x
        mm["mass_kg"] += (x - x0) / 3.6 * (BATT_MASS[0] * cells_s + BATT_MASS[1]) / 1000.0

    run("kv_rpm_per_V", m["motor"]["kv_rad_s_V"] * 60.0 / (2.0 * math.pi), kv)
    run("diameter_m", m["diameter_m"], diameter)
    run("mass_kg", m["mass_kg"], mass)
    run("capacity_As", m["capacity_As"], capacity)
    return out


# -------------------------------------------------------------------------------------------------------- the jobs
def job_version(job):
    import importlib.metadata as md
    import aerosandbox
    import casadi
    have = lambda name: f"{name} {md.version(name)}" if _installed(name) else f"no {name}"
    return {"version": f"aerosandbox {aerosandbox.__version__}, casadi {casadi.__version__}, {have('proptimiser')}, "
                       f"{have('jax')}"}


def job_chain(job):
    """electric_chain at numbers (tests and checks)."""
    out = electric_chain(job["torque_Nm"], job["omega_rad_s"], job["duty"], job["motor"], job["v_bus_V"])
    return {k: float(v) for k, v in out.items()}


def job_library_check(job):
    """The chain at kappa 1 and Q0 0 against the first-order motor of the AeroSandbox library (test)."""
    from aerosandbox.library.propulsion_electric import motor_electric_performance
    m = dict(job["motor"], kappa=1.0, q0_Nm=0.0)
    ours = electric_chain(job["torque_Nm"], job["omega_rad_s"], 1.0, m, job["v_bus_V"])
    lib = motor_electric_performance(rpm=job["omega_rad_s"] * 60 / (2 * math.pi), torque=job["torque_Nm"],
                                     kv=m["kv_rad_s_V"] * 60 / (2 * math.pi), resistance=m["r_tot_ohm"],
                                     no_load_current=m["i0_A"])
    return {"v_term_V": float(ours["v_term_V"]), "i_motor_A": float(ours["i_motor_A"]),
            "library_voltage_V": float(lib["voltage"]), "library_current_A": float(lib["current"])}


def job_synthetic_design(job):
    """Write a small Proptimiser design (default blade) into the Proptimiser home of the job (test)."""
    os.environ["PROPTIMISER_HOME"] = job["home"]
    from proptimiser.init import Inputs, Propeller
    Path(job["home"], "designs").mkdir(parents=True, exist_ok=True)
    Path(job["home"], "propellers").mkdir(parents=True, exist_ok=True)
    prop = Propeller.default(inputs=Inputs(coeff_method=3, n_r=8, n_psi=1, V_x=[job["V_x"], 0.8], V_yz=[0.0, 0.0]),
                             c=job["chord_m"], beta_deg=job["beta_deg"])
    prop.save(job["name"], overwrite=True)
    return {"saved": job["name"]}


def job_geometry(job):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    spec, out = job["spec"], Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    plane = build_airplane(spec)
    main = next(w for w in plane.wings if w.name == job["main_wing"])
    res = {"s_m2": float(main.area()), "b_m": float(main.span()), "mac_m": float(main.mean_aerodynamic_chord()),
           "aspect_ratio": float(main.aspect_ratio())}
    files = []
    plane.draw_three_view(show=False)
    png = out / "three_view.png"
    plt.gcf().savefig(png, dpi=150)
    plt.close("all")
    files.append(str(png))
    try:
        fig = plane.draw(backend="plotly", show=False)
        html = out / "airplane_3d.html"
        fig.write_html(str(html), include_plotlyjs="cdn")
        files.append(str(html))
    except Exception as e:                     # the 3D view is a convenience
        res["html_error"] = str(e)
    return {"geometry": res, "files": files}


def job_polar(job):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    spec, out = job["spec"], Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    plane = _with_ref(build_airplane(spec), spec["mass"]["cg"])
    fl = spec["flight"]
    rows = []
    for a in job["alpha_deg"]:
        op, r = _aero(plane, fl["speed_m_s"], a, fl["altitude_m"])
        rows.append({"alpha_deg": float(a), "CL": _f(r["CL"]), "CD": _f(r["CD"]), "Cm": _f(r["Cm"])})
    csv = out / "polar.csv"
    csv.write_text("alpha_deg,CL,CD,Cm\n" + "".join(f"{r['alpha_deg']},{r['CL']},{r['CD']},{r['Cm']}\n" for r in rows),
                   encoding="utf-8")
    ref = job.get("reference")
    fig, ax = plt.subplots(1, 3, figsize=(13, 4))
    al = [r["alpha_deg"] for r in rows]
    for k, key in enumerate(("CL", "CD", "Cm")):
        ax[k].plot(al, [r[key] for r in rows], "o-", label="AeroSandbox AeroBuildup")
        if ref:
            ax[k].plot(ref["alpha_deg"], ref[key], "s--", label="flow5 (DAVE-ML in the ADH)")
        ax[k].set_xlabel("alpha [deg]")
        ax[k].set_ylabel(key)
        ax[k].grid(True)
    ax[0].legend()
    fig.tight_layout()
    png = out / "polar.png"
    fig.savefig(png, dpi=150)
    plt.close(fig)
    return {"rows": rows, "files": [str(csv), str(png)]}


def job_cruise_trim(job):
    """Level flight at the cruise speed: alpha, elevator, shaft speed and duty from one Opti problem."""
    import aerosandbox as asb
    import aerosandbox.numpy as np_
    spec = job["spec"]
    plane = _with_ref(build_airplane(spec), spec["mass"]["cg"])
    fl = spec["flight"]
    V, W = fl["speed_m_s"], fl["weight_N"]
    atm = asb.Atmosphere(altitude=fl["altitude_m"])
    chain, v_bus = _motor_chain(spec)
    model, prop = _prop_model(spec)
    hub_z, cg_z = spec["propulsion"]["hub"][2], spec["mass"]["cg"][2]
    omega_max = 343.0 / (0.5 * spec["propulsion"]["diameter_m"])

    opti = asb.Opti()
    alpha = opti.variable(init_guess=3.0, lower_bound=-10.0, upper_bound=15.0)
    de = opti.variable(init_guess=0.0, lower_bound=-20.0, upper_bound=20.0)
    omega = opti.variable(init_guess=560.0, lower_bound=50.0, upper_bound=omega_max)
    duty = opti.variable(init_guess=0.5, lower_bound=0.01, upper_bound=1.0)
    op = asb.OperatingPoint(atmosphere=atm, velocity=V, alpha=alpha)
    r = asb.AeroBuildup(airplane=plane.with_control_deflections({"elevator": de}), op_point=op).run()
    thrust_scale = max(W / 12.0, 1.0)
    out = model.add_to(opti, omega, V * np_.cosd(alpha), 0.0, thrust_scale, rho_kg_m3=float(atm.density()),
                       mu_Pa_s=float(atm.dynamic_viscosity()), a_m_s=float(atm.speed_of_sound()))
    ch = electric_chain(out.torque_Nm, omega, duty, chain, v_bus)
    drag, lift = -r["F_w"][0], -r["F_w"][2]
    opti.subject_to([out.thrust_N * np_.cosd(alpha) - drag == 0,
                     lift + out.thrust_N * np_.sind(alpha) - W == 0,
                     r["M_b"][1] + out.thrust_N * (cg_z - hub_z) == 0,
                     ch["residual_V"] == 0])
    model.warm_start(opti, out, 560.0, V, 0.0, thrust_scale, float(atm.density()), float(atm.dynamic_viscosity()),
                     float(atm.speed_of_sound()))
    sol = opti.solve(verbose=False, max_iter=300)
    v = lambda x: float(sol(x))
    T, Q, w, d = v(out.thrust_N), v(out.torque_Nm), v(omega), v(duty)
    c = {k: v(x) for k, x in ch.items()}
    batt = spec["propulsion"]["battery"]
    energy_J = batt.get("capacity_As", 0.0) * v_bus
    result = {"speed_m_s": V, "weight_N": W, "alpha_deg": v(alpha), "elevator_deg": v(de), "omega_rad_s": w,
              "rpm": w * 60 / (2 * math.pi), "duty": d, "thrust_N": T, "torque_Nm": Q, "p_shaft_W": Q * w,
              "lift_N": v(lift), "drag_N": v(drag), "L_over_D": v(lift) / v(drag), "CL": v(r["CL"]), "CD": v(r["CD"]),
              **c, "chain_efficiency": Q * w / c["p_bat_W"], "battery_energy_J": energy_J,
              "endurance_min": (energy_J / c["p_bat_W"] / 60.0) if energy_J else None,
              "motor_current_limit_A": spec["propulsion"]["motor"].get("imax_A")}
    return {"cruise_trim": result}


def job_static_check(job):
    """Full command at zero speed: the BEMT and the chain against the Propalyser Ct/Cp table and power at full command."""
    import aerosandbox as asb
    spec = job["spec"]
    chain, v_bus = _motor_chain(spec)
    model, prop = _prop_model(spec)
    atm = asb.Atmosphere(altitude=spec["flight"]["altitude_m"])
    rho, mu, a = float(atm.density()), float(atm.dynamic_viscosity()), float(atm.speed_of_sound())
    D = spec["propulsion"]["diameter_m"]
    opti = asb.Opti()
    omega = opti.variable(init_guess=600.0, lower_bound=50.0, upper_bound=343.0 / (0.5 * D))
    out = model.add_to(opti, omega, 0.0, 0.0, 30.0, rho, mu, a)
    ch = electric_chain(out.torque_Nm, omega, 1.0, chain, v_bus)
    opti.subject_to(ch["residual_V"] == 0)
    model.warm_start(opti, out, 600.0, 0.0, 0.0, 30.0, rho, mu, a)
    sol = opti.solve(verbose=False, max_iter=200)
    w, T, Q = float(sol(omega)), float(sol(out.thrust_N)), float(sol(out.torque_Nm))
    n = w / (2 * math.pi)
    tab = spec["propulsion"]["tables"]
    ct0, cp0 = float(np.interp(0.0, tab["J"], tab["CT"])), float(np.interp(0.0, tab["J"], tab["CP"]))
    # the Propalyser table at the same shaft speed
    T_tab, P_tab = ct0 * rho * n ** 2 * D ** 4, cp0 * rho * n ** 3 * D ** 5
    # the Propalyser power at full command is p_max; the table of this speed gives the speed that has p_max
    n_pmax = (spec["propulsion"]["p_max_W"] / (cp0 * rho * D ** 5)) ** (1 / 3)
    res = {"omega_rad_s": w, "rpm": w * 60 / (2 * math.pi), "thrust_N": T, "torque_Nm": Q, "p_shaft_W": Q * w,
           "i_motor_A": float(sol(ch["i_motor_A"])), "p_bat_W": float(sol(ch["p_bat_W"])),
           "ct0_bemt": T / (rho * n ** 2 * D ** 4), "cp0_bemt": Q * w / (rho * n ** 3 * D ** 5),
           "ct0_table": ct0, "cp0_table": cp0, "thrust_table_same_omega_N": T_tab, "p_shaft_table_same_omega_W": P_tab,
           "p_max_propalyser_W": spec["propulsion"]["p_max_W"], "rpm_propalyser_table_at_pmax": n_pmax * 60.0,
           "rho_kg_m3": rho}
    return {"static_check": res}


# ------------------------------------------------------------------------------------------------ multirotor jobs
def isa_density(altitude_m):
    """ISA air density (kg/m^3) in the troposphere (ISO 2533): T = 288.15 - 0.0065 h, p = 101325 (T/288.15)^5.25588."""
    t = 288.15 - 0.0065 * altitude_m
    return 101325.0 * (t / 288.15) ** 5.25588 / (287.05287 * t)


def _rho_of(job):
    spec = job["spec"]
    return float(job.get("rho_kg_m3") or isa_density(spec["analysis"]["altitude_m"]))


def build_multirotor_airplane(spec):
    """The body box and the arm tubes as AeroSandbox fuselages (the airplane has no wing). The box is a superellipse
    (shape 10) that spans the box edges. An arm is a round tube with its cross sections along its path, listed in
    rising x (AeroSandbox fuselages run along x)."""
    import aerosandbox as asb

    body = spec["body"]
    bx = body["box"]
    lx, ly, lz = bx["size"]
    cx, cy, cz = bx["centre"]
    n = int(spec["drag_job"].get("box_edge_sections", 5))
    fus = [asb.Fuselage(name="body", xsecs=[asb.FuselageXSec(xyz_c=[float(x), cy, cz], width=ly, height=lz, shape=10.0)
                                            for x in np.linspace(cx - lx / 2, cx + lx / 2, n)])]
    for i, arm in enumerate(body["arms"], 1):
        p0, p1 = sorted((np.asarray(arm["p0"], float), np.asarray(arm["p1"], float)), key=lambda p: p[0])
        if p1[0] - p0[0] <= 0.0:
            raise ValueError(f"arm {i} has no extent along x: AeroSandbox fuselages run along x")
        fus.append(asb.Fuselage(name=f"arm_{i}", xsecs=[asb.FuselageXSec(xyz_c=list(p0 + t * (p1 - p0)), radius=arm["radius_m"])
                                                       for t in np.linspace(0.0, 1.0, 5)]))
    props = [asb.Propulsor(name=f"rotor_{r['motor']}", xyz_c=r["hub"], xyz_normal=r["thrust_axis"], radius=0.5 * r["diameter_m"])
             for r in spec["rotors"]]
    ref = spec["reference"]
    return asb.Airplane(name=spec["name"], xyz_ref=ref["xyz_ref"], fuselages=fus, propulsors=props, s_ref=ref["s_m2"],
                        b_ref=ref["b_m"], c_ref=ref["c_m"])


def hoerner_cda(spec, h):
    """The hand check of the body drag: C_D A along each body axis from the crossflow drag of the bluff shapes
    (Hoerner, Fluid-Dynamic Drag, 1965, chapter 3). The box takes its flat-face coefficient on the face normal to the flow.
    A tube takes the cylinder crossflow coefficient on its projected area, with the independence principle: only the
    velocity component normal to the tube axis counts, so the force along the flow is C_d 2 r L (1 - a_i^2)^1.5 for a
    flow along axis i (a_i: the axis component of the tube direction)."""
    lx, ly, lz = spec["body"]["box"]["size"]
    out = {"x": h["cd_box_flat_face"] * ly * lz, "y": h["cd_box_flat_face"] * lx * lz, "z": h["cd_box_flat_face"] * lx * ly}
    for arm in spec["body"]["arms"]:
        v = np.asarray(arm["p1"], float) - np.asarray(arm["p0"], float)
        length = float(np.linalg.norm(v))
        a = v / length
        for i, ax in enumerate("xyz"):
            out[ax] += h["cd_cylinder_crossflow"] * 2.0 * arm["radius_m"] * length * (1.0 - a[i] ** 2) ** 1.5
    return out


def job_multirotor_drag(job):
    """Body drag of the multirotor (AeroBuildup of the box and the arm tubes). The flow runs along +x, -x, +y, -y, +z
    and -z of the body axes FRD (alpha and beta of the operating point). C_D A of an axis is the mean of the two
    directions of the force component along the flow: |F_b,i| / q. C_Di = C_D A / S_ref. AeroBuildup also gives a force
    along x for a pure side or vertical flow (a slender-body term of the fuselage model): it is not used.

    AeroBuildup is a slender-body method: it has no pressure drag on the flat front face of a bluff box. The hand check
    (hoerner_cda) has it. `drag_job.combine` picks the C_D A of each axis: asb, hoerner, or max (the larger one; the
    default, because a too small drag area is the unsafe error)."""
    import aerosandbox as asb

    spec = job["spec"]
    cfg = spec["drag_job"]
    plane = build_multirotor_airplane(spec)
    atm = asb.Atmosphere(altitude=cfg["altitude_m"])
    rho, speed = float(atm.density()), cfg["speed_m_s"]
    q = 0.5 * rho * speed ** 2
    flows = {"+x": (0.0, 0.0, 0), "-x": (0.0, 180.0, 0), "+y": (0.0, 90.0, 1), "-y": (0.0, -90.0, 1),
             "+z": (90.0, 0.0, 2), "-z": (-90.0, 0.0, 2)}
    cda = {}
    for key, (alpha, beta, i) in flows.items():
        op = asb.OperatingPoint(atmosphere=atm, velocity=speed, alpha=alpha, beta=beta)
        r = asb.AeroBuildup(airplane=plane, op_point=op).run()
        cda[key] = abs(_f(r["F_b"][i])) / q
        if not math.isfinite(cda[key]):
            raise RuntimeError(f"AeroBuildup gave no force for the flow {key}")
    mean = {ax: 0.5 * (cda["+" + ax] + cda["-" + ax]) for ax in "xyz"}
    s_ref = spec["reference"]["s_m2"]
    hoerner = hoerner_cda(spec, cfg["hoerner"])
    combine = cfg.get("combine", "max")
    pick = {"asb": lambda a, h: a, "hoerner": lambda a, h: h, "max": max}[combine]
    used = {ax: pick(mean[ax], hoerner[ax]) for ax in "xyz"}
    return {"multirotor_drag": {
        "speed_m_s": speed, "rho_kg_m3": rho, "S_ref_m2": s_ref, "CdA_by_direction_m2": cda, "CdA_asb_m2": mean,
        "hoerner_CdA_m2": hoerner, "combine": combine, "CdA_m2": used,
        "CD": {"CDx": used["x"] / s_ref, "CDy": used["y"] / s_ref, "CDz": used["z"] / s_ref},
        "asb_over_hoerner": {ax: mean[ax] / hoerner[ax] for ax in "xyz"},
        "asymmetry": {ax: abs(cda["+" + ax] - cda["-" + ax]) / mean[ax] for ax in "xyz"}}}


def job_emst_segments(job):
    """Hover, climb and forward flight (the tilt loop), and the full-throttle limit. Paper section III.A."""
    spec = job["spec"]
    a = spec["analysis"]
    m = emst_model(spec, _rho_of(job))
    segs = [emst_hover(m), emst_climb(m, a["climb_rate_m_s"])] + [emst_forward(m, v) for v in a["forward_speeds_m_s"]]
    return {"emst_segments": {"rho_kg_m3": m["rho"], "mass_kg": m["mass_kg"], "weight_N": m["mass_kg"] * G0,
                              "n_rotors": m["n_rotors"], "segments": segs, "full_throttle": emst_full_throttle(m)}}


def job_emst_live(job):
    """Hover and vertical climb with the live Proptimiser BEMT in place of the CT/CP table. One Propeller for each rotor
    (reused for both segments). The designs are spec["live"]["designs"] (the first one is the main case). Fit C is the
    main case and Fit B a comparison. The table result of the same segments comes back as the maker check."""
    spec = job["spec"]
    live = spec["live"]
    if not _installed("proptimiser"):
        raise RuntimeError("Proptimiser is not installed in the AeroSandbox Python: run "
                           "`python -m aeroplan setup AeroSandbox --proptimiser <checkout>`")
    os.environ["PROPTIMISER_HOME"] = live["home"]
    from proptimiser.init import Propeller
    a = spec["analysis"]
    m = emst_model(spec, _rho_of(job))
    W = m["mass_kg"] * G0
    table = {"hover": emst_hover(m), "climb": emst_climb(m, a["climb_rate_m_s"])}
    out = {"rho_kg_m3": m["rho"], "n_rotors": m["n_rotors"], "table": table, "designs": {}}
    for design in live["designs"]:
        props = [Propeller.load(design) for _ in range(m["n_rotors"])]
        fns = [live_rotor(p, m["rho"]) for p in props]
        fz = body_force(0.0, 0.0, -a["climb_rate_m_s"], 0.0, m)[2]
        out["designs"][design] = {
            "hover": live_segment("hover", 0.0, W, fns, m),
            "climb": live_segment("climb", a["climb_rate_m_s"], W + fz, fns, m)}
    return {"emst_live": out}


def job_emst_endurance(job):
    """Endurance and range against the airspeed, with the best speeds (paper section III.A.4)."""
    a = job["spec"]["analysis"]
    m = emst_model(job["spec"], _rho_of(job))
    return {"emst_endurance": emst_scan(m, a["scan_max_m_s"], a["scan_step_m_s"])}


def job_emst_sensitivity(job):
    """Central differences of the hover endurance (paper section III.A.5)."""
    spec = job["spec"]
    m = emst_model(spec, _rho_of(job))
    return {"emst_sensitivity": emst_sensitivity(m, spec["propulsion"]["battery"]["cells_s"], spec["analysis"]["sensitivity_step"])}


JOBS = {"version": job_version, "chain": job_chain, "library_check": job_library_check,
        "synthetic_design": job_synthetic_design, "geometry": job_geometry, "polar": job_polar,
        "cruise_trim": job_cruise_trim, "static_check": job_static_check,
        "multirotor_drag": job_multirotor_drag, "emst_segments": job_emst_segments, "emst_endurance": job_emst_endurance,
        "emst_sensitivity": job_emst_sensitivity, "emst_live": job_emst_live}


def main(argv):
    job_file, result_file = Path(argv[1]), Path(argv[2])
    try:
        job = json.loads(job_file.read_text(encoding="utf-8"))
        res = {"ok": True, **JOBS[job["job"]](job)}
    except Exception as e:
        res = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
    result_file.write_text(json.dumps(res), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
