"""The Rosella sizing script (tools/aerosandbox/rosella.py). Every number is synthetic.

rosella.py needs the AeroSandbox Python (`python -m aeroplan setup AeroSandbox`). That Python has no pytest. So each check is a
plain function (`check_*`) and each test runs it in one of two ways:
  - the Python that runs pytest has aerosandbox: the test calls the check directly;
  - it has not, but the AeroSandbox Python exists: the test runs this file there (`python tests/test_rosella.py NAME`);
  - neither: the test skips (CI has none).
Run all checks in the AeroSandbox Python with `tools/aerosandbox/.venv/Scripts/python tests/test_rosella.py`.
"""
import csv
import importlib.util
import math
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import pytest
except ImportError:                                    # the AeroSandbox Python has no pytest
    pytest = None

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "tools" / "aerosandbox"
HAS_ASB = importlib.util.find_spec("aerosandbox") is not None
CHECKS = {}


def check(fn):
    CHECKS[fn.__name__] = fn
    return fn


def rel(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-300)


def load_rosella():
    sys.path.insert(0, str(TOOL))
    import rosella
    return rosella


def synthetic_settings(rosella):
    """The real settings file: it holds only stand-in numbers and sources. The check changes what it needs."""
    return rosella.settings()


# ------------------------------------------------------------------------------------------------ settings helpers
@check
def check_val_apply_sets_placeholders():
    r = load_rosella()
    st = {"a": {"value": 2.0, "source": "x"}, "b": 3, "c": {"d": {"value": 1.0, "placeholder": True}, "e": [1, 2]},
          "f": {"placeholder": True, "value": None}}
    assert r.val(st["a"]) == 2.0 and r.val(st, "b") == 3.0 and r.val(st["c"], "d") == 1.0
    assert sorted(r.placeholders(st)) == ["c.d", "f"]
    out = r.apply_sets(st, ["a=5.5", "c.e=[3, 4]", "c.d=7", "b=hello"])
    assert out["a"]["value"] == 5.5 and out["a"]["source"] == "x"            # a `value` entry keeps its source
    assert out["c"]["e"] == [3, 4] and out["c"]["d"]["value"] == 7 and out["b"] == "hello"
    assert out["_changed"] == ["a=5.5", "c.e=[3, 4]", "c.d=7", "b=hello"]
    assert r.apply_sets({"x": 1}, None)["_changed"] == []
    try:
        r.apply_sets({"x": 1}, ["y.z=1"])
    except KeyError:
        pass
    else:
        raise AssertionError("an unknown settings key must raise KeyError")
    real = r.settings()
    assert r.val(r.apply_sets(real, ["cruise_aero.map_speed_m_s=19"])["cruise_aero"], "map_speed_m_s") == 19.0


@check
def check_parse_levels_and_awg_and_margin():
    r = load_rosella()
    assert r.parse_levels("L0..L4") == ["L0", "L1", "L2", "L3", "L4"]
    assert r.parse_levels("L2") == ["L2"] and r.parse_levels("L0, L1") == ["L0", "L1"]
    d_mm = 0.127 * 92 ** ((36 - 10) / 39)                                   # ASTM B258, AWG 10
    assert abs(r.awg_of(math.pi / 4 * (d_mm / 1000) ** 2) - 10.0) < 1e-9
    assert rel(r.margin({"value": 8.0, "lo": None, "hi": 10.0}), 0.2)
    assert rel(r.margin({"value": 8.0, "lo": 6.0, "hi": 10.0}), 0.2)
    assert r.margin({"value": 12.0, "lo": None, "hi": 10.0}) < 0.0


# ---------------------------------------------------------------------------------------------------- the mass fits
def write_survey(path, a=(math.log(300.0), -0.3, 0.8), b=(math.log(0.12), 1.5, -1.0), c=(math.log(0.7), 0.5, 0.6)):
    """A survey whose rows follow exact power laws (kv in rpm/V, q_cap in N m, m in g). References: kv 150, q 3, m 300."""
    rows = []
    for kv in (80.0, 120.0, 160.0, 220.0, 300.0, 400.0):
        for q in (2.0, 3.0, 4.5, 6.0):
            m = math.exp(a[0]) * (kv / 150.0) ** a[1] * (q / 3.0) ** a[2]
            rm = math.exp(b[0]) * (kv / 150.0) ** b[1] * (m / 300.0) ** b[2]
            i0 = math.exp(c[0]) * (kv / 150.0) ** c[1] * (m / 300.0) ** c[2]
            imax = i0 + q * kv * 2.0 * math.pi / 60.0
            rows.append({"maker": "T", "model": f"M{kv:.0f}_{q}", "kv_rpm_per_V": kv, "mass_g": m, "rm_mohm": 1000.0 * rm,
                         "i0_A": i0, "imax_A": imax})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def survey_laws(kv, q):
    m = 300.0 * (kv / 150.0) ** -0.3 * (q / 3.0) ** 0.8
    rm = 0.12 * (kv / 150.0) ** 1.5 * (m / 300.0) ** -1.0
    i0 = 0.7 * (kv / 150.0) ** 0.5 * (m / 300.0) ** 0.6
    return m, rm, i0


@check
def check_motor_fit_recovers_exact_power_laws():
    r = load_rosella()
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "survey.csv"
        rows = write_survey(p)
        fit = r.MotorFit(p)
    kept = [x for x in rows if 150.0 <= x["mass_g"] <= 1600.0]
    assert fit.n == len(kept) and fit.n >= 8
    assert fit.mass_rms < 1e-9 and fit.rm_rms < 1e-9 and fit.i0_rms < 1e-9
    # exponents: m ~ kv^-0.3 q^0.8, Rm ~ kv^1.5 m^-1, I0 ~ kv^0.5 m^0.6 (the constant is exp(c0) in the fit)
    assert all(abs(x - y) < 1e-9 for x, y in zip(fit.mass_fit[1:], (-0.3, 0.8)))
    assert all(abs(x - y) < 1e-9 for x, y in zip(fit.rm_fit[1:], (1.5, -1.0)))
    assert all(abs(x - y) < 1e-9 for x, y in zip(fit.i0_fit[1:], (0.5, 0.6)))
    for kv, q in ((100.0, 2.5), (250.0, 5.0)):                              # between the survey rows
        m, rm, i0 = survey_laws(kv, q)
        assert rel(float(fit.mass_g(kv, q)), m, 1e-9)
        assert rel(float(fit.rm_ohm(kv, m)), rm, 1e-9) and rel(float(fit.i0_A(kv, m)), i0, 1e-9)
    s = fit.summary()
    assert s["rows"] == fit.n and len(s["mass"]) == 3 and s["q_cap_range_Nm"][0] <= s["q_cap_range_Nm"][1]


@check
def check_motor_fit_on_the_committed_survey():
    """The committed survey gives a motor near the Redback M6C10 (234 g, KV150, holds about 2.3 N m)."""
    r = load_rosella()
    fit = r.MotorFit(r.HERE / "data" / "motor_survey.csv")
    assert fit.n >= 10
    assert 150.0 < float(fit.mass_g(150.0, 2.3)) < 1200.0
    assert fit.mass_fit[2] > 0.0                                            # a stronger motor is heavier


@check
def check_bershadsky_equations():
    r = load_rosella()
    st = r.settings()
    # Eq. 1: m = 10^p1 Kv^p2 (g)
    assert rel(r.bershadsky_motor_g(150.0), 10 ** 4.0499 * 150.0 ** -0.5329)
    assert rel(r.bershadsky_motor_g(150.0, 4.4482, -0.5242), 10 ** 4.4482 * 150.0 ** -0.5242)
    assert r.bershadsky_motor_g(150.0) > r.bershadsky_motor_g(300.0)       # the paper curve falls with Kv
    # Eq. 5: m = 0.1207 D^2 - 0.5122 D (g, D in inch). 22 in: 58.4188 - 11.2684 = 47.1504 g (hand value)
    assert abs(r.carbon_prop_g(22 * 0.0254, st) - 47.1504) < 1e-9
    assert abs(r.carbon_prop_g(0.0, st)) < 1e-12
    # Eq. 4 with the NXE 6S 4500 calibration: the 6S 4.5 Ah pack weighs 0.631 kg, and the mass is linear in capacity
    assert abs(r.battery_mass_kg(6, 4.5, st) - 0.631) < 1e-9
    assert rel(r.battery_mass_kg(6, 9.0, st), 2.0 * 0.631)
    p1, p2 = 0.026373, 2.0499e-05
    assert rel(r.battery_mass_kg(12, 4.5, st) / r.battery_mass_kg(6, 4.5, st), (p1 * 12 + p2) / (p1 * 6 + p2))


# --------------------------------------------------------------------------------------------- a small L0 sizing problem
class StubAirframe:
    """Synthetic airframe numbers in the place of the Currawong tree and the VLM run. The methods are the real ones."""

    @staticmethod
    def make(rosella):
        a = object.__new__(rosella.Airframe)
        pt = lambda m, x, y=0.0, z=0.0: {"mass": {"value": m}, "position": {"xyz": [x, y, z]}}
        a.points = {"WINGS-1": pt(0.9, 0.12, 0.5), "WINGS-2": pt(0.9, 0.12, -0.5), "TAIL-S1": pt(0.15, 1.42, 0.0),
                    "TAIL-BOOM": pt(0.25, 0.9), "AVIONICS-REST": pt(0.5, -0.1), "PROPULSION-MOTOR": pt(0.4, -0.65),
                    "PROPULSION-ESC": pt(0.1, -0.4), "PROPULSION-PROP": pt(0.06, -0.68), "PROPULSION-REST": pt(0.1, -0.5)}
        a.wing_pts = [a.points["WINGS-1"], a.points["WINGS-2"]]
        a.tail_pts = [a.points["TAIL-S1"]]
        a.m_tail_boom, a.m_avionics = 0.25, 0.5
        a.m_cruise_esc, a.m_cruise_prop, a.m_cruise_rest = 0.1, 0.06, 0.1
        a.cruise = {"kv_rad_s_V": 23.0, "i0_A": 2.0, "kappa": 1.05, "r_tot_ohm": 0.04, "mass_kg": 0.4, "imax_A": 70.0, "diameter_m": 0.5}
        a.cruise_offsets = {"motor": 0.0, "esc": 0.25, "prop": -0.03, "rest": 0.15}
        a.s_ref, a.b_ref, a.c_ref = 1.0, 3.3, 0.33
        a.neutral_point, a.x_cg, a.x_hub = 0.15, 0.12, -0.68
        a.polar = {"cd0": 0.03, "k": 0.05, "cl_max": 1.2}
        a.wing_le_x = (0.02, 0.0)                                           # x = 0.02 y
        a.wing_te_x = (0.02, 0.30)
        a.tail_boom_frames = [[[0.561, 0.0, 0.0]]]
        a.tail_boom_z, a.htail_le_x = -0.0255, 1.40                         # synthetic
        return a


def small_case(r, config="H4", cells=12, fixed=None):
    r._CONST["momentum"] = {"FM": 0.65, "CT0": 0.0646, "T_hover_N": 37.0, "eta_cruise": 0.70, "J_cruise": 0.6}
    r._CONST["cruise_D"] = 0.5
    r.lift_model = r.cruise_model = lambda st: None                         # L0 uses no BEMT, but prop() asks for the models first
    st = r.apply_sets(r.settings(), ["limits.mtow_kg=20.0"])           # room for the synthetic airframe
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "survey.csv"
        write_survey(p)
        fit = r.MotorFit(p)
    air = StubAirframe.make(r)
    air.st = st
    case = r.Case(st, air, fit, config, cells, level="L0", fixed=fixed).build()
    return st, air, case


@check
def check_l0_solve_and_the_hand_formulas():
    r = load_rosella()
    st, air, case = small_case(r)
    case.solve(max_iter=400, attempts=2)
    assert case.sol is not None, case.error
    rep = case.report()
    n, d, con = rep["names"], rep["design"], rep["constraints"]
    G0 = r.G0
    # SI: the diameter is D_m (no D_in); the report holds the status word, ok, c_ref, the rotor z and the boom z
    assert "D_m" in rep and "D_in" not in rep and abs(rep["D_m"] - 2.0 * rep["R_m"]) < 1e-12
    assert rep["status_word"] in ("ok", "acceptable") and rep["ok"] is True
    assert rep["c_ref_m"] == air.c_ref and abs(rep["rotor_z_m"] - (air.tail_boom_z + r.val(st["structure"], "mount_offset_m"))) < 1e-12
    assert rep["spacing_m"] is None and abs(rep["pitch_m"] - 0.16764 / 0.5588 * rep["D_m"]) < 1e-9
    md, rows = r.order_sheet(rep, st)
    assert "INDICATIVE" not in md and "mm" in md
    bad = dict(rep, ok=False, status_word="failed")
    md, rows = r.order_sheet(bad, st)
    assert md.startswith("**INDICATIVE ONLY: solver status failed") and "INDICATIVE ONLY" in rows[0][2]
    assert r.passes({"margin": -5e-7, "equality": False}) and not r.passes({"margin": -5e-6, "equality": False})
    assert r.passes({"margin": -5e-5, "equality": True}) and not r.passes({"margin": -5e-4, "equality": True})
    assert r.normalise_block({"inputs": {"prop_pitch_in": 6.6}})["inputs"] == {"prop_pitch_m": 6.6 * 0.0254}
    # the mass limit and the CG fix
    assert n["M"] <= 20.0 + 1e-6
    assert abs(sum(i["mass_kg"] * i["x"] for i in rep["items"]) / n["M"] - air.x_cg) < 1e-6
    assert abs(sum(i["mass_kg"] for i in rep["items"]) - n["M"]) < 1e-9
    # Bershadsky Eq. 2: ESC mass = 0.8421 g/A on 1.2 x the peak current
    assert rel(n["m_esc"], 0.8421e-3 * 1.2 * n["I_pk"], 1e-9)
    assert abs(n["m_prop"] * 1000.0 - r.carbon_prop_g(2.0 * rep["R_m"], st)) < 1e-6      # Eq. 5
    assert abs(n["m_batt"] - r.battery_mass_kg(12, d["cap_Ah"], st)) < 1e-9              # Eq. 4

    # ---- beam: independent hand calculation from the solution
    mat = st["material"][st["material"]["design_choice"]]
    E, rho = r.val(mat, "E_axial_Pa"), r.val(mat, "density_kg_m3")
    ro, t, a = d["r_boom"], d["t_boom"], d["a"]
    ri = ro - t
    I = math.pi / 4.0 * (ro ** 4 - ri ** 4)
    A = math.pi * (ro ** 2 - ri ** 2)
    L = 2.0 * a + 2.0 * r.val(st["structure"], "overhang_m")
    assert abs(L - n["L_boom"]) < 1e-12
    m_boom_each = rho * A * L
    assert abs(n["m_boom"] - 2.0 * m_boom_each) < 1e-9
    m_unit = n["m_motor"] + n["m_prop"] + n["m_esc"] + r.val(st["fixed_mass_kg"], "motor_mount_each")
    m_arm = m_boom_each * a / L
    # frequency: f1 = sqrt(3 E I / (a^3 m_eff)) / 2 pi, m_eff = m_tip + 0.236 m_arm (H4: one rotor on each end)
    m_eff = m_unit + 0.236 * m_arm
    f1 = math.sqrt(3.0 * E * I / (a ** 3 * m_eff)) / (2.0 * math.pi)
    assert rel(rep["f1_Hz"], f1, 1e-9)
    # buckling: sigma_cr = 0.605 E_c t / r_mid x knockdown
    Ec, kd = r.val(mat, "E_axial_compression_Pa"), r.val(st["material"]["buckling_knockdown"])
    assert rel(n["sigma_cr"], 0.605 * Ec * t / (ro - 0.5 * t) * kd, 1e-9)
    # stress at the full-throttle thrust, front end, thrust load case (structure[0])
    SF, n_g = r.val(st["limits"], "safety_factor"), r.val(st["limits"], "load_factor")
    F, Q = rep["rotors"]["MAX_f"]["T_N"], rep["rotors"]["MAX_f"]["Q_Nm"]
    Mb = SF * math.hypot(F * a + n_g * G0 * m_arm * a / 2.0, Q)
    sigma = Mb / I * ro
    tau = SF * F * r.val(st["structure"], "mount_offset_m") * ro / (2.0 * I)
    s0 = rep["structure"][0]
    assert rel(s0["F_N"], F, 1e-9) and rel(s0["sigma_Pa"], sigma, 1e-9)
    assert rel(s0["von_mises_Pa"], math.sqrt(sigma ** 2 + 3.0 * tau ** 2), 1e-9)
    assert rel(s0["slope_deg"], math.degrees(F * a ** 2 / (2.0 * E * I)), 1e-9)
    # the same numbers sit in the constraint table that the report and the order sheet use
    assert rel(con["boom_buckling_Pa_front_T"]["hi"], n["sigma_cr"], 1e-9)
    assert rel(con["boom_f1_over_1P_hover_front"]["value"], f1, 1e-9)

    # ---- mission reduction: the time of each segment, the energy of each segment, and the total
    mis, lim = st["mission"], st["limits"]
    t_ = rep["time_s"]
    assert abs(t_["vtol_takeoff_climb"] - 30.0 / 2.5) < 1e-12
    assert abs(t_["transitions"] - 2.0 * 15.0) < 1e-12
    assert abs(t_["fw_climb"] - (93.0 - 30.0) / 2.6) < 1e-12
    dist = 656.0 + 3370.0 * 10 + 660.0
    assert rel(t_["transit_laps_rtl"], dist / n["V_lap"], 1e-12)
    lines, turns = 6 * 259.0, 5 * math.pi * r.val(st["cruise_aero"], "map_turn_radius_m")
    assert rel(t_["survey"], (lines + turns) / n["V_map"], 1e-12)
    assert t_["deploy_hover"] == 60.0 and abs(t_["landing"] - 30.0 / 1.5) < 1e-12 and t_["reserve"] == 300.0
    P, e = rep["P_battery_W"], rep["energy_Wh"]
    assert rel(e["reserve"], P["H_L"] * 300.0 / 3600.0, 1e-9) and rel(e["deploy_hover"], P["H_L"] * 60.0 / 3600.0, 1e-9)
    assert rel(e["landing"], P["H_L"] * 20.0 / 3600.0, 1e-9) and rel(e["transitions"], P["H_TO"] * 30.0 / 3600.0, 1e-9)
    assert rel(e["vtol_takeoff_climb"], P["C_TO"] * 12.0 / 3600.0, 1e-9)
    assert rel(sum(e.values()), rep["energy_total_Wh"], 1e-9)
    assert rep["energy_total_Wh"] <= r.val(lim, "battery_usable_fraction") * rep["energy_nominal_Wh"] * (1 + 1e-6)
    assert rel(rep["energy_nominal_Wh"], 12 * r.val(st["electrical"], "cell_nominal_V") * d["cap_Ah"], 1e-9)
    # lap speed is above 1.3 Vs (the stall margin)
    assert n["V_lap"] >= r.val(st["cruise_aero"], "stall_margin") * n["Vs"] * (1 - 1e-6)


@check
def check_h8_has_eight_rotors_and_the_coaxial_factor():
    r = load_rosella()
    st, air, case = small_case(r, config="H8", cells=10)
    assert case.N == 8 and case.n_per == 2 and abs(case.k_int - 1.28) < 1e-12
    st4, air4, case4 = small_case(r, config="H4", cells=10)
    assert case4.N == 4 and case4.k_int == 1.0
    assert len(case.rotors) == len(case4.rotors) == 8                      # four states, front and rear end


@check
def check_fixed_variables_are_parameters():
    r = load_rosella()
    st, air, case = small_case(r, fixed={"kv": 150.0, "r_boom": 0.0125})
    assert "kv" not in case.named and "r_boom" not in case.named and "t_boom" in case.named
    case.solve(max_iter=400, attempts=2)
    assert case.sol is not None, case.error
    rep = case.report()
    assert rep["design"]["kv"] == 150.0 and rep["design"]["r_boom"] == 0.0125


# --------------------------------------------------------------------------------------------------------- pytest hooks
def run_check(name):
    if HAS_ASB:
        CHECKS[name]()
        return
    sys.path.insert(0, str(HERE))
    from aeroplan.spokes import load
    runner = load("AeroSandbox").runner
    if not runner.available():
        pytest.skip("no AeroSandbox Python here: run `python -m aeroplan setup AeroSandbox`")
    p = subprocess.run([str(runner.python()), "-I", str(Path(__file__).resolve()), name], capture_output=True, text=True,
                       cwd=str(TOOL))
    assert p.returncode == 0, (p.stdout + p.stderr)[-2500:]


def test_settings_helpers():
    run_check("check_val_apply_sets_placeholders")


def test_levels_awg_and_margin():
    run_check("check_parse_levels_and_awg_and_margin")


def test_motor_fit_recovers_power_laws():
    run_check("check_motor_fit_recovers_exact_power_laws")


def test_motor_fit_on_the_committed_survey():
    run_check("check_motor_fit_on_the_committed_survey")


def test_bershadsky_equations():
    run_check("check_bershadsky_equations")


def test_small_l0_solve_beam_and_mission_hand_values():
    run_check("check_l0_solve_and_the_hand_formulas")


def test_h8_has_eight_rotors():
    run_check("check_h8_has_eight_rotors_and_the_coaxial_factor")


def test_fixed_variables_are_parameters():
    run_check("check_fixed_variables_are_parameters")


if __name__ == "__main__":
    names = sys.argv[1:] or list(CHECKS)
    failed = 0
    for nm in names:
        try:
            CHECKS[nm]()
            print("ok  ", nm)
        except Exception as e:                                              # print every failure, then exit with 1
            failed += 1
            print("FAIL", nm, type(e).__name__, e)
            import traceback
            traceback.print_exc()
    sys.exit(1 if failed else 0)
