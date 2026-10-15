"""AeroSandbox worker. It runs in AeroSandbox/.venv and imports only aerosandbox, proptimiser, numpy and matplotlib.

    python asb_worker.py <job.json> <result.json>

The job names a task in "job". The result is {"ok": true, ...} or {"ok": false, "error", "trace"}.
The spoke (AeroSandbox/spoke.py) builds the spec from the ADH document. The worker holds the tool rules.

Spec (tool-neutral JSON, SI units, angles in degrees where the name says deg, design frame x aft, y right, z up):
    reference    s_m2, b_m, c_m, xyz_ref (the MRP)
    surfaces     name, mirror, sections [xyz_le, chord, twist_deg, foil, controls], foils {name: [[x, z], ...]}
    fuselages    [{name, frames: [[x, y, z] of the right half, top to bottom]}]: the fuselage and the tail boom
    mass         mass_kg, cg, inertia, point_masses
    propulsion   hub, thrust_axis, diameter_m, motor, esc, battery, tables, proptimiser_home, design
    flight       speed_m_s, altitude_m, weight_n

Jobs: version, chain, geometry, polar, cruise_trim, static_check.
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


JOBS = {"version": job_version, "chain": job_chain, "library_check": job_library_check,
        "synthetic_design": job_synthetic_design, "geometry": job_geometry, "polar": job_polar,
        "cruise_trim": job_cruise_trim, "static_check": job_static_check}


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
