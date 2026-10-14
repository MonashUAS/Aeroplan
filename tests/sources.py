"""Tiny synthetic stand-ins for source files (flow5 sweep, Propalyser .h5). Every number is a test value."""
import json
from pathlib import Path

import h5py
import numpy as np

HEAD = """Type 1: Fixed speed
V∞ = 12m/s
Fluid properties:
   ρ =     1.225 kg/m³
Inertia:
   Mass =  8.000 kg
   CoG = (0.100, 0.000, -0.010)m
Nbr. of data points = {n}
Plane_X
{name}
Freestream speed = 10.000 m/s


 Ctrl        α (°)      β (°)      φ (°)      CL           CD           CY           Cm           Cl           Cn  {first}
{rows}
"""
T6_RANGES = """   Velocity:         10.000,  10.000 m/s
   Range_0:         0.000,   0.000°
   Range_1:       -10.000,  10.000°
   Range_2:        10.000, -10.000°
"""
COLS = "Ctrl alpha beta phi CL CD CY Cm Cl Cn"


def _row(ctrl, alpha, cl):
    return f"{ctrl:g} {alpha:g} 0 0 {cl:g} 0.05 0 -0.1 0.01 0.002"


def polar_text(name="alpha", n=3, t6=False, drop_declared=None):
    rows = [_row(0.0 if t6 else 0, a, 0.1 * a) for a in range(n)] if not t6 else [_row(c, 3, 0.5 + c) for c in (0.0, 0.5, 1.0)]
    n = len(rows) if drop_declared is None else drop_declared
    text = HEAD.format(n=n, name=name, first=rows[0], rows="\n".join(rows[1:]))
    if t6:
        text = text.replace("Nbr. of data points", T6_RANGES + "Nbr. of data points")
    return text


def make_sweep(d: Path):
    d.mkdir(parents=True)
    (d / "alpha.csv").write_text(polar_text("alpha"), encoding="utf-8")
    (d / "elevator.csv").write_text(polar_text("elevator", t6=True), encoding="utf-8")
    (d / "t7_reference.csv").write_text(polar_text("t7_reference", n=1), encoding="utf-8")
    (d / "plane_with_body.xml").write_text("<plane/>", encoding="utf-8")
    (d / "results.json").write_text(json.dumps({
        "name": "sweep_x", "flow5": "7.57", "created_utc": "2026-01-01T00:00:00+00:00",
        "inputs": {"S": 1.0, "b": 2.0, "cbar": 0.5, "mass": 8.0, "cg": [0.1, 0.0, -0.01]}}), encoding="utf-8")


def make_propalyser_h5(path: Path, *, version=2, dirty=False, units=True, status="quantitative", bad_units=False):
    """A contract-B (propulsion-system v2) file with test values. `bad_units` writes an S-119 spelling into an .h5 attr."""
    s = h5py.string_dtype()
    with h5py.File(path, "w") as f:
        f.attrs.update(schema="propulsion-system", schema_version=version, system_id="sys_x", basis="vendor",
                       placeholder=True, created_utc="2026-01-01T00:00:00Z", author="Test Person", data_sha256="0" * 64)
        f.create_group("generator").attrs.update(name="propalyser", commit="abc1234", dirty=dirty)
        t = f.create_group("prop_ctcp")
        cols = {"J": [0.0, 0.3, 0.5], "CT": [0.08, 0.05, 0.01], "CP": [0.02, 0.02, 0.01],
                "CT_sigma": [0.003, 0.002, 0.001], "CP_sigma": [0.002, 0.002, 0.001]}
        for k, v in cols.items():
            t[k] = np.array(v)
            if units:
                t[k].attrs["units"] = "nd"
        t["source_id"] = np.array(["model"] * 3, dtype=s)
        t.attrs.update(valid_J=np.array([0.0, 0.5]), selected_source="model")
        f.create_group("propeller").attrs.update(model="PROP_X", diameter_m=0.5, blades=2, ixx_kgm2=0.001)
        f.create_group("motor").attrs.update(model="MOTOR_X", kv_rpm_per_V=200.0, r_ohm=0.05, i0_A=1.5, pole_pairs=7,
                                             mass_kg=0.4, chain_kappa_nd=1.1, chain_r_tot_ohm=0.12)
        f.create_group("esc").attrs.update(model="ESC_X", pwm_low_us=1000, pwm_high_us=2000, imax_continuous_A=60)
        f.create_group("battery").attrs.update(model="BATT_X", cells_s=6, cells_p=1, capacity_Ah=5.0, v_nominal_V=22.2,
                                               mass_kg=0.7)
        tm = f.create_group("throttle_map")
        tm["esc_command_norm"] = np.array([0.0, 0.5, 1.0])
        tm["power_fraction"] = np.array([0.0, 0.4, 1.0])
        tm.attrs["p_max_W"] = 1000.0
        u = f.create_group("uncertainty/prop_ctcp")
        u.attrs.update(status=status, scope="result", basis="relative 1-sigma model error converted to absolute")
        if status == "quantitative":
            u.attrs.update(method="vendor_spec", distribution="normal", effect="absolute", num_sigmas=1.0)
        f.create_group("results/ct0").attrs.update(median=0.08, lower=0.07, upper=0.09, coverage=0.95, units="nd",
                                                   method="monte_carlo")
        f.create_group("results/torque").attrs.update(median=1.0, lower=0.9, upper=1.1, coverage=0.95,
                                                      units="N_m" if bad_units else "N*m", method="monte_carlo")
        f["warnings"] = np.array(["a warning"], dtype=s)
        f.create_group("daveml")["propulsion.dml"] = np.frombuffer(b"<DAVEfunc/>", dtype=np.uint8)
