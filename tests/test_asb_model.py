"""The AeroSandbox model files (tools/aerosandbox: component.py, mission.py, model.py, optimise.py, result.py). Every number is synthetic.

The sizing runs in the AeroSandbox Python (`python -m aeroplan setup AeroSandbox`). That Python has no pytest. So each check is a plain
function (`check_*`) and each test runs it in one of two ways:
  - the Python that runs pytest has aerosandbox: the test calls the check directly;
  - it has not, but the AeroSandbox Python exists: the test runs this file there (`python tests/test_asb_model.py NAME`);
  - neither: the test skips (CI has none).
Run all checks in the AeroSandbox Python with `tools/aerosandbox/.venv/Scripts/python tests/test_asb_model.py`.
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
G0 = 9.80665


def check(fn):
    CHECKS[fn.__name__] = fn
    return fn


def rel(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-300)


def tool():
    """component, mission, model, optimise, result of tools/aerosandbox as modules."""
    if str(TOOL) not in sys.path:
        sys.path.insert(0, str(TOOL))
    import component, mission, model, optimise, result
    return component, mission, model, optimise, result


# ----------------------------------------------------------------------------------------------- a synthetic quadplane
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


def synthetic_components(survey: Path, layout_cells=12):
    """Components with synthetic numbers (not the Rosella numbers). Same names as QuadplaneModel needs."""
    c, mi, m, o, r = tool()
    P = c.P
    s = "test"
    return {
        "limits": c.Spec("limits", mtow_kg=P(20.0, "kg", s), thrust_to_weight=P(2.5, "nd", s), load_factor=P(3.0, "nd", s),
                         safety_factor=P(1.5, "nd", s, placeholder=True)),
        "mission": mi.Mission("mission", climb_height_m=P(93.0, "m", s), climb_rate_m_s=P(2.6, "m/s", s), transit_m=P(656.0, "m", s),
                              lap_length_m=P(3370.0, "m", s), lap_count=P(2, "nd", s), rtl_m=P(660.0, "m", s), survey_lines=P(6, "nd", s),
                              survey_line_length_m=P(259.0, "m", s), survey_turn_bank_deg=P(30.0, "deg", s),
                              deployment_hover_s=P(60.0, "s", s), reserve_hover_s=P(300.0, "s", s), vtol_climb_m=P(30.0, "m", s),
                              vtol_climb_rate_m_s=P(2.5, "m/s", s), vtol_descent_rate_m_s=P(1.5, "m/s", s), transition_s=P(15.0, "s", s)),
        "airframe": c.Airframe("airframe", base=P("none", "", s), static_margin_target=P(0.1, "nd", s), cg_nose_prop_m=P(0.8, "m", s)),
        "fuselage": c.Fuselage("fuselage", stations=P(21, "nd", s), width_m=P(0.24, "m", s), height_m=P(0.18, "m", s),
                               superellipse_n=P(2.5, "nd", s), z_centre_m=P(0.02, "m", s), nose_behind_hub_m=P(0.07, "m", s),
                               mass_kg_per_m2=P(1.0, "kg/m2", s), bay_x_m=P([-0.45, 0.40], "m", s), battery_Wh_per_L=P(330.0, "Wh/L", s)),
        "boom_material": c.Material("test_tube", E_Pa=P(60e9, "Pa", s), E_c_Pa=P(50e9, "Pa", s), density_kg_m3=P(1500.0, "kg/m3", s),
                                    tensile_strength_Pa=P(370e6, "Pa", s), compressive_strength_Pa=P(350e6, "Pa", s),
                                    G_Pa=P(4e9, "Pa", s), buckling_knockdown=P(0.5, "nd", s)),
        "boom": c.Tube("boom", r_o=P(0.020, "m", s, free=True, lo=0.008, hi=0.045, scale=1e-2),
                       t=P(0.0015, "m", s, free=True, lo=0.001, hi=0.005, scale=1e-3),
                       y=P(0.65, "m", s, free=True, lo=0.35, hi=1.0, scale=0.65), dx=P(0.0, "m", s, free=True, lo=-0.35, hi=0.35, scale=0.1),
                       a=P(0.5, "m", s, free=True, lo=0.25, hi=1.0, scale=0.5), overhang_m=P(0.06, "m", s), mount_offset_m=P(0.02, "m", s),
                       clamp_kg=P(0.06, "kg", s), min_wall_m=P(0.001, "m", s), r_over_t_max=P(60.0, "nd", s),
                       tip_slope_max_deg=P(1.0, "deg", s), resonance_margin=P(0.2, "nd", s), resonance_side=P("below", "", s),
                       material=P("boom_material")),
        "rotor": c.Rotor("rotor", design=P("syn", "", s), design_aircraft=P("none", "", s), reference_radius_m=P(0.2794, "m", s),
                         scale=P(1.0, "nd", s, free=True, lo=0.72, hi=1.18, scale=1.0),
                         cant=P(0.05, "rad", s, free=True, lo=0.0, hi=0.17, scale=0.1), blade_diameter_m=P(0.5588, "m", s),
                         blade_pitch_m=P(0.16764, "m", s), mass_kg=P(None), pitch_m=P(None), prop_g_a_in2=P(0.1207, "g/in2", s),
                         prop_g_b_in=P(-0.5122, "g/in", s), tip_clearance_m=P(0.02, "m", s), tip_mach_max=P(0.65, "nd", s),
                         coaxial_spacing_over_D=P(0.25, "nd", s)),
        "cruise_rotor": c.CruiseRotor("cruise_rotor", design=P("syn_cruise", "", s), design_aircraft=P("none", "", s)),
        "motor": c.Motor("motor", kv=P(150.0, "rpm/V", s, free=True, lo=60.0, hi=450.0, scale=150.0),
                         q_cap=P(3.0, "N*m", s, free=True, lo=0.5, hi=9.0, scale=3.0), survey=P(str(survey), "", s),
                         kv_min=P(60.0, "rpm/V", s), kv_max=P(450.0, "rpm/V", s), mass_min_g=P(150.0, "g", s), mass_max_g=P(1600.0, "g", s),
                         mass_kg=P(None), rm_ohm=P(None), i0_A=P(None), mount_kg=P(0.045, "kg", s)),
        "esc": c.ESC("esc", g_per_A=P(0.8421, "g/A", s), peak_factor=P(1.2, "nd", s), re_ohm=P(0.02, "ohm", s), duty_max=P(0.95, "nd", s),
                     mass_kg=P(None), current_A=P(None)),
        "battery": c.Battery("battery", cells_s=P(layout_cells, "nd", s), cap_Ah=P(14.0, "A*h", s, free=True, lo=2.0, hi=60.0, scale=14.0),
                             x_m=P(0.0, "m", s, free=True, lo=-0.45, hi=0.4, scale=0.1), cell_nominal_V=P(3.7, "V", s),
                             cell_end_V=P(3.5, "V", s), cell_resistance_mohm=P(5.0, "mohm", s), c_rate_max=P(25.0, "1/h", s),
                             usable_fraction=P(0.8, "nd", s), eq4_p1=P(0.026373, "g/mAh", s), eq4_p2=P(2.0499e-05, "g/mAh", s),
                             cal_cells_s=P(6, "nd", s), cal_capacity_Ah=P(4.5, "A*h", s), cal_mass_kg=P(0.631, "kg", s), mass_kg=P(None)),
        "cables": c.Cables("cables", current_density_A_m2=P(10e6, "A/m2", s), insulation_factor=P(1.4, "nd", s), run_extra_m=P(0.15, "m", s)),
        "avionics": c.PointMass("avionics", mass_kg=P(0.35, "kg", s), power_W=P(25.0, "W", s)),
        "landing_gear": c.PointMass("landing_gear", mass_kg=P(0.6, "kg", s), x_m=P(0.16, "m", s), z_m=P(-0.1, "m", s)),
        "cargo": c.PointMass("cargo", mass_kg=P(0.572, "kg", s), x_from_cg=P(0.0, "m", s)),
        "camera": c.PointMass("camera", mass_kg=P(0.11, "kg", s), x_m=P(-0.45, "m", s), z_m=P(-0.05, "m", s)),
        "cruise_aero": c.Spec("cruise_aero", boom_cf=P(0.0045, "nd", s), boom_form_factor=P(1.2, "nd", s), nacelle_cda_m2=P(0.001, "m2", s),
                              stopped_prop_cda_per_r2=P(0.01, "nd", s), cl_max_usable_factor=P(0.85, "nd", s), stall_margin=P(1.3, "nd", s),
                              map_turn_radius_m=P(40.0, "m", s)),
        "control": c.Control("control", bandwidth_rad_s=P(2.0, "rad/s", s), bandwidth_length_m=P(11.9, "m", s), amplitude_rad=P(0.1745, "rad", s),
                             margin=P(1.2, "nd", s), yaw_rad_s2=P(1.5, "rad/s2", s), idle_thrust_fraction=P(0.15, "nd", s),
                             k_int=P(1.28, "nd", s)),
    }


def stub_airframe(c, fus):
    """Synthetic airframe numbers in the place of the Currawong tree and the VLM run. The methods are the real ones."""
    a = object.__new__(c.AirframeModel)
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
    a.tail_boom_z, a.htail_le_x = -0.0255, 1.40
    a.fus = fus
    return a


def small_model(layout="H4", cells=12, tmp: Path = None):
    """A synthetic quadplane at level L0: a stub airframe and fixed momentum constants (no Proptimiser)."""
    c, mi, m, o, r = tool()
    tmp = tmp or Path(tempfile.mkdtemp())
    survey = tmp / "survey.csv"
    write_survey(survey)
    comps = synthetic_components(survey, cells)
    model = m.QuadplaneModel("test", comps, layout=layout)
    model.af = stub_airframe(c, comps["fuselage"])
    home = tmp / "home"
    c.proptimiser_home = lambda aircraft, designs: home                   # no copy of design files
    c._CONST[f"momentum|lift|{home}"] = {"FM": 0.65, "CT0": 0.0646, "T_hover_N": 37.0}
    c._CONST[f"momentum|cruise|{home}"] = {"eta_cruise": 0.70, "J_cruise": 0.6}
    return model


def solve_l0(model):
    c, mi, m, o, r = tool()
    p = o.Problem(model, "L0").build()
    p.solve(max_iter=400, attempts=2)
    assert p.sol is not None, p.error
    return p, p.report()


# --------------------------------------------------------------------------------------------------- params and components
@check
def check_param_json_roundtrip_free_fix_and_placeholders():
    c, mi, m, o, r = tool()
    P = c.P
    comp = c.Spec("spec", a=P(1.5, "m", "src A"), b=P(0.0, "m", "zero is kept", free=True, lo=0.0, hi=2.0, scale=0.1),
                  c=P(7, "nd", "", placeholder=True), d=P([1.0, 2.0], "m", "a list"), e=P("text"))
    back = c.Component.from_json(comp.to_json())
    assert isinstance(back, c.Spec) and back.name == "spec" and back["a"] == 1.5 and back["d"] == [1.0, 2.0] and back["e"] == "text"
    assert back.p("b").free and back.p("b").lo == 0.0 and back.p("b").hi == 2.0 and back.p("b").scale == 0.1     # a zero bound survives
    assert back.placeholders() == ["spec.c"] and back.free_params() == ["b"]
    back.fix(b=0.5)
    assert back["b"] == 0.5 and back.free_params() == []
    back.free("a", lo=1.0, hi=2.0)
    assert back.free_params() == ["a"] and comp.free_params() == ["b"]                 # the copy is separate
    assert back.get("missing", 3) == 3 and c.Param.from_json(4.0).value == 4.0


@check
def check_material_with_E_keeps_the_compression_ratio():
    c, mi, m, o, r = tool()
    mat = synthetic_components(Path("x"))["boom_material"]
    new = mat.with_E(80e9, "bought")
    assert new.name == "bought" and new["E_Pa"] == 80e9 and rel(new["E_c_Pa"] / new["E_Pa"], mat["E_c_Pa"] / mat["E_Pa"])
    assert mat["E_Pa"] == 60e9                                                      # the original stays


@check
def check_bershadsky_mass_equations():
    c, mi, m, o, r = tool()
    comps = synthetic_components(Path("x"))
    # Eq. 5: m = 0.1207 D^2 - 0.5122 D (g, D in inch). 22 in: 58.4188 - 11.2684 = 47.1504 g (hand value)
    assert abs(comps["rotor"].mass_kg_of(22 * 0.0254) * 1000.0 - 47.1504) < 1e-9 and abs(comps["rotor"].mass_kg_of(0.0)) < 1e-12
    # Eq. 4 with the calibration pack: the 6S 4.5 Ah pack weighs 0.631 kg, and the mass is linear in capacity
    b = comps["battery"]
    assert abs(b.mass_kg_of(6, 4.5) - 0.631) < 1e-9 and rel(b.mass_kg_of(6, 9.0), 2.0 * 0.631)
    p1, p2 = 0.026373, 2.0499e-05
    assert rel(b.mass_kg_of(12, 4.5) / b.mass_kg_of(6, 4.5), (p1 * 12 + p2) / (p1 * 6 + p2))
    b["mass_kg"] = 0.9                                                              # a bought pack replaces the equation
    assert b.mass_kg_of(12, 4.5) == 0.9


@check
def check_motor_fit_recovers_exact_power_laws():
    c, mi, m, o, r = tool()
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "survey.csv"
        rows = write_survey(p)
        fit = c.MotorModel(p)
    kept = [x for x in rows if 150.0 <= x["mass_g"] <= 1600.0]
    assert fit.n == len(kept) and fit.n >= 8
    assert fit.mass_rms < 1e-9 and fit.rm_rms < 1e-9 and fit.i0_rms < 1e-9
    assert all(abs(x - y) < 1e-9 for x, y in zip(fit.mass_fit[1:], (-0.3, 0.8)))
    assert all(abs(x - y) < 1e-9 for x, y in zip(fit.rm_fit[1:], (1.5, -1.0)))
    assert all(abs(x - y) < 1e-9 for x, y in zip(fit.i0_fit[1:], (0.5, 0.6)))
    for kv, q in ((100.0, 2.5), (250.0, 5.0)):                                      # between the survey rows
        mass, rm, i0 = survey_laws(kv, q)
        assert rel(float(fit.mass_g(kv, q)), mass, 1e-9)
        assert rel(float(fit.rm_ohm(kv, mass)), rm, 1e-9) and rel(float(fit.i0_A(kv, mass)), i0, 1e-9)
    fit.maker = {"mass_kg": 0.3, "rm_ohm": None, "i0_A": 1.0}                       # maker values replace the fit
    assert fit.mass_g(150.0, 3.0) == 300.0 and fit.i0_A(150.0, 300.0) == 1.0 and rel(float(fit.rm_ohm(100.0, 300.0)), float(fit.rm_ohm(100.0, 300.0)))


@check
def check_motor_fit_on_the_committed_survey():
    """The committed survey gives a motor near the Redback M6C10 (234 g, KV150, holds about 2.3 N m)."""
    c, mi, m, o, r = tool()
    fit = c.MotorModel(TOOL / "data" / "motor_survey.csv")
    assert fit.n >= 10 and 150.0 < float(fit.mass_g(150.0, 2.3)) < 1200.0 and fit.mass_fit[2] > 0.0


@check
def check_levels_and_the_rotor_model_kind():
    c, mi, m, o, r = tool()
    assert c.parse_levels("L0..L4") == ["L0", "L1", "L2", "L3", "L4"] and c.parse_levels("L2") == ["L2"] and c.parse_levels("L0, L1") == ["L0", "L1"]
    assert c.level("L2").groups == c.GROUPS_ALL and c.level("L0").groups == c.GROUPS_L0 and "elec" in c.level("L1").groups
    home = Path("home")
    c.proptimiser_home = lambda aircraft, designs: home
    rot = synthetic_components(Path("x"))["rotor"]
    kinds = {lv: c.rotor_model(rot, lv, "H_TO_f").kind for lv in ("L0", "L1", "L2", "L3", "L4")}
    assert kinds == {"L0": "momentum", "L1": "table", "L2": "table", "L3": "bemt", "L4": "bemt"}
    assert c.rotor_model(rot, "L3", "MAX_f").kind == "table"                          # L3: BEMT in the take-off hover states only
    cr = synthetic_components(Path("x"))["cruise_rotor"]
    assert c.rotor_model(cr, "L4", "cr_lap", diameter_m=0.5).role == "cruise"


# -------------------------------------------------------------------------------------------------------------- mission
@check
def check_mission_segments_and_energy():
    c, mi, m, o, r = tool()
    mis = synthetic_components(Path("x"))["mission"]
    assert [x.name for x in mis.conditions(2.5)] == ["H_TO", "C_TO", "H_L", "MAX", "F_LAP", "F_MAP"]
    assert mis.conditions(2.5)[3].thrust_factor == 2.5 and mis.conditions(2.5)[2].payload is False
    sv = mis.survey(40.0)
    assert rel(sv["turn_len"], 5 * math.pi * 40.0) and rel(sv["line_len"], 6 * 259.0)
    assert rel(sv["n_turn"], 1.0 / math.cos(math.radians(30.0)))
    segs = mis.segments(20.0, 15.0, 40.0, 100.0, 0.5)
    t = {s.name: s.time_s for s in segs}
    assert t["vtol_takeoff_climb"] == 12.0 and t["transitions"] == 30.0 and rel(t["fw_climb"], 63.0 / 2.6)
    dist = 656.0 + 3370.0 * 2 + 660.0
    assert rel(t["transit_laps_rtl"], dist / 20.0) and rel(t["survey"], (sv["line_len"] + sv["turn_len"]) / 15.0)
    assert t["deploy_hover"] == 60.0 and t["landing"] == 20.0 and t["reserve"] == 300.0
    power = {"C_TO": 500.0, "H_TO": 400.0, "F_LAP": 200.0, "F_MAP": 150.0, "H_L": 380.0}
    J, tt = mis.energy(power, segs)
    assert rel(J["fw_climb"], 200.0 * t["fw_climb"] + 100.0 * 63.0 / 0.5) and rel(J["reserve"], 380.0 * 300.0)
    assert rel(J["transitions"], 400.0 * 30.0) and tt == t


# ----------------------------------------------------------------------------------------------- a small L0 sizing problem
@check
def check_l0_solve_and_the_hand_formulas():
    c, mi, m, o, r = tool()
    model = small_model()
    p, res = solve_l0(model)
    rep = res.data
    n, d, con = rep["names"], rep["design"], rep["constraints"]
    comps = model.c
    air = model.af
    assert "D_m" in rep and abs(rep["D_m"] - 2.0 * rep["R_m"]) < 1e-12 and rep["status_word"] in ("ok", "acceptable") and res.ok
    assert rep["c_ref_m"] == air.c_ref and abs(rep["rotor_z_m"] - (air.tail_boom_z + 0.02)) < 1e-12
    assert rep["spacing_m"] is None and abs(rep["pitch_m"] - 0.16764 / 0.5588 * rep["D_m"]) < 1e-9
    # the mass limit and the CG fix
    assert n["M"] <= 20.0 + 1e-6
    assert abs(sum(i["mass_kg"] * i["x"] for i in rep["items"]) / n["M"] - air.x_cg) < 1e-6
    assert abs(sum(i["mass_kg"] for i in rep["items"]) - n["M"]) < 1e-9
    # Bershadsky Eq. 2: ESC mass = 0.8421 g/A on 1.2 x the peak current. Eq. 5 and Eq. 4 for the propeller and the battery.
    assert rel(n["m_esc"], 0.8421e-3 * 1.2 * n["I_pk"], 1e-9)
    assert abs(n["m_prop"] - comps["rotor"].mass_kg_of(2.0 * rep["R_m"])) < 1e-9
    assert abs(n["m_batt"] - comps["battery"].mass_kg_of(12, d["cap_Ah"])) < 1e-9

    # ---- beam: independent hand calculation from the solution
    mat = comps["boom_material"]
    E, rho = mat["E_Pa"], mat["density_kg_m3"]
    ro, t, a = d["r_boom"], d["t_boom"], d["a"]
    ri = ro - t
    I = math.pi / 4.0 * (ro ** 4 - ri ** 4)
    A = math.pi * (ro ** 2 - ri ** 2)
    L = 2.0 * a + 2.0 * comps["boom"]["overhang_m"]
    assert abs(L - n["L_boom"]) < 1e-12
    m_boom_each = rho * A * L
    assert abs(n["m_boom"] - 2.0 * m_boom_each) < 1e-9
    m_unit = n["m_motor"] + n["m_prop"] + n["m_esc"] + comps["motor"]["mount_kg"]
    m_arm = m_boom_each * a / L
    m_eff = m_unit + 0.236 * m_arm                                                  # H4: one rotor on each end
    f1 = math.sqrt(3.0 * E * I / (a ** 3 * m_eff)) / (2.0 * math.pi)
    assert rel(rep["f1_Hz"], f1, 1e-9)
    Ec, kd = mat["E_c_Pa"], mat["buckling_knockdown"]
    assert rel(n["sigma_cr"], 0.605 * Ec * t / (ro - 0.5 * t) * kd, 1e-9)
    SF, n_g = comps["limits"]["safety_factor"], comps["limits"]["load_factor"]
    F, Q = rep["rotors"]["MAX_f"]["T_N"], rep["rotors"]["MAX_f"]["Q_Nm"]
    Mb = SF * math.hypot(F * a + n_g * G0 * m_arm * a / 2.0, Q)
    sigma = Mb / I * ro
    tau = SF * F * comps["boom"]["mount_offset_m"] * ro / (2.0 * I)
    s0 = rep["structure"][0]
    assert rel(s0["F_N"], F, 1e-9) and rel(s0["sigma_Pa"], sigma, 1e-9)
    assert rel(s0["von_mises_Pa"], math.sqrt(sigma ** 2 + 3.0 * tau ** 2), 1e-9)
    assert rel(s0["slope_deg"], math.degrees(F * a ** 2 / (2.0 * E * I)), 1e-9)
    assert rel(con["boom_buckling_Pa_front_T"]["hi"], n["sigma_cr"], 1e-9) and rel(con["boom_f1_over_1P_hover_front"]["value"], f1, 1e-9)
    # the resonance rule "below": f1 stays under hover 1P less the margin (the constraint is a limit of the report)
    assert rel(con["boom_f1_over_1P_hover_front"]["hi"], 0.8 * rep["rotors"]["H_TO_f"]["omega_rad_s"] / (2 * math.pi), 1e-9)

    # ---- mission: the time, the energy of each segment and the total
    t_ = rep["time_s"]
    assert abs(t_["vtol_takeoff_climb"] - 30.0 / 2.5) < 1e-12 and abs(t_["transitions"] - 30.0) < 1e-12
    assert rel(t_["transit_laps_rtl"], (656.0 + 3370.0 * 2 + 660.0) / n["V_lap"], 1e-12)
    P, e = rep["P_battery_W"], rep["energy_Wh"]
    assert rel(e["reserve"], P["H_L"] * 300.0 / 3600.0, 1e-9) and rel(e["landing"], P["H_L"] * 20.0 / 3600.0, 1e-9)
    assert rel(sum(e.values()), rep["energy_total_Wh"], 1e-9)
    assert rep["energy_total_Wh"] <= 0.8 * rep["energy_nominal_Wh"] * (1 + 1e-4) and rel(rep["energy_nominal_Wh"], 12 * 3.7 * d["cap_Ah"], 1e-9)
    assert n["V_lap"] >= 1.3 * n["Vs"] * (1 - 1e-4)
    # the compact result keeps what the spoke reads
    cp = res.compact()
    assert cp["case"] == "H4_12S" and cp["names"]["M"] == n["M"] and "multistart" not in cp and "slack" not in cp["constraints"]["mtow_kg"]
    assert set(cp["constraints"]["mtow_kg"]) >= {"value", "hi", "group", "enabled", "equality", "margin"}


@check
def check_resonance_side_above_flips_the_limit():
    c, mi, m, o, r = tool()
    model = small_model()
    model.c["boom"]["resonance_side"] = "above"
    p = o.Problem(model, "L0").build()
    c_ = p.cons["boom_f1_over_1P_hover_front"]
    assert c_[1] is not None and c_[2] is None                                    # "above": f1 >= (1 + margin) x 1P
    model.c["boom"]["resonance_side"] = "beside"
    try:
        o.Problem(model, "L0").build()
    except ValueError as e:
        assert "below or above" in str(e)
    else:
        raise AssertionError("an unknown resonance side must raise ValueError")


@check
def check_h8_has_eight_rotors_and_the_coaxial_factor():
    model = small_model(layout="H8", cells=10)
    p, res = solve_l0(model)
    assert model.N == 8 and model.n_per == 2 and abs(model.d.k_int - 1.28) < 1e-12
    assert rel(res["spacing_m"], 0.25 * res["D_m"], 1e-9)
    m4 = small_model(layout="H4", cells=10)
    p4, res4 = solve_l0(m4)
    assert m4.N == 4 and m4.d.k_int == 1.0 and len(res["rotors"]) == len(res4["rotors"]) == 8   # four states, front and rear end


@check
def check_fixed_params_are_parameters_and_free_ones_are_variables():
    model = small_model()
    model.fix(motor__kv=150.0, boom__r_o=0.0125)
    p, res = solve_l0(model)
    assert "kv" not in p.named and "r_boom" not in p.named and "t_boom" in p.named
    assert res.design["kv"] == 150.0 and res.design["r_boom"] == 0.0125
    assert model.free_params() == ["boom.t", "boom.y", "boom.dx", "boom.a", "rotor.scale", "rotor.cant", "motor.q_cap", "battery.cap_Ah", "battery.x_m"]


@check
def check_the_solver_gives_a_snapshot_at_each_iteration_and_the_plotter_reads_it():
    c, mi, m, o, r = tool()
    model = small_model()
    p = o.Problem(model, "L0").build()
    snaps = []
    p.solve(max_iter=200, callback=snaps.append)
    assert len(snaps) >= 3 and all(isinstance(s, r.Snapshot) for s in snaps)
    assert set(snaps[-1].design) == set(m.DESIGN_VARS) and snaps[-1].violation < 1e-3
    assert abs(snaps[-1].energy_Wh - p.report().energy_Wh) < 0.05 * p.report().energy_Wh
    g = model.geometry(snaps[-1].design)
    assert g["a"] == snaps[-1].design["a"] and g["n_per"] == 1
    discs = model.rotor_discs(snaps[-1].design)
    assert len(discs) == 4 and all(abs(math.hypot(*(d["rim"][0] - d["centre"]))) - g["R"] < 1e-9 for d in discs)


@check
def check_the_model_file_roundtrip():
    c, mi, m, o, r = tool()
    model = small_model()
    model.fix(boom__t=0.001)
    p, res = solve_l0(model)
    model.result_summary = res.compact()
    with tempfile.TemporaryDirectory() as d:
        path = model.save(Path(d) / "t.json")
        back = m.AircraftModel.load(path)
    assert back.name == "test" and back.layout == "H4" and back.free_params() == model.free_params() and back.placeholders() == model.placeholders()
    assert back.c["boom"]["a"] == model.c["boom"]["a"] and back.c["motor"].p("kv").hi == 450.0 and back.result_summary["case"] == "H4_12S"
    assert back.c["boom_material"].name == "test_tube"


@check
def check_evaluate_fixes_every_param_except_the_battery_x():
    c, mi, m, o, r = tool()
    model = small_model()
    p, res = solve_l0(model)
    for name, (ck, pk) in m.DESIGN_VARS.items():
        model.c[ck].params[pk].value = res.design[name]
    ev = o.evaluate(model, "L0")
    assert abs(ev.energy_Wh / res.energy_Wh - 1.0) < 1e-4
    assert not [k for k in ev.violated() if ev.constraints[k]["margin"] < -1e-4]            # the solver tolerance is 1e-5 of the scaled limit
    assert model.free_params() and ev.design["kv"] == res.design["kv"]               # the model is not changed by evaluate


@check
def check_jung_check_functions():
    c, mi, m, o, r = tool()
    import numpy as np
    b = c.jung_blades()
    assert {"KPROP_22", "Tmotor_18", "Tmotor_29", "Tmotor_40"} <= set(b)
    for v in b.values():
        assert 0.3 < v["D_m"] < 1.1 and v["c_m"].max() < 0.15 and v["c_m"].min() > 0 and 0 < v["beta_rad"].max() < 0.8
        assert np.all(np.diff(v["r_over_R"]) > 0) and v["r_over_R"].max() <= 1.0
    assert abs(c.jung_c_max(0.6604) - 0.0640) < 1e-4
    t = b["Tmotor_29"]
    out = c.jung_compare(t["r_over_R"], t["c_m"], t["beta_rad"], t["D_m"])
    assert all(abs(row[3]) < 1e-9 and abs(row[6]) < 1e-9 for row in out["rows"])


# --------------------------------------------------------------------------------------------------------- pytest hooks
def run_check(name):
    if HAS_ASB:
        CHECKS[name]()
        return
    sys.path.insert(0, str(HERE))
    from aeroplan.spokes import load
    spoke = load("AeroSandbox")
    if not spoke.available():
        pytest.skip("no AeroSandbox Python here: run `python -m aeroplan setup AeroSandbox`")
    p = subprocess.run([str(spoke.python()), "-E", "-s", str(Path(__file__).resolve()), name], capture_output=True, text=True, cwd=str(TOOL))
    assert p.returncode == 0, (p.stdout + p.stderr)[-2500:]


if pytest is not None:
    def _make(name):
        def test():
            run_check(name)
        test.__name__ = "test_" + name[len("check_"):]
        return test

    for _name in ("check_param_json_roundtrip_free_fix_and_placeholders", "check_material_with_E_keeps_the_compression_ratio",
                  "check_bershadsky_mass_equations", "check_motor_fit_recovers_exact_power_laws", "check_motor_fit_on_the_committed_survey",
                  "check_levels_and_the_rotor_model_kind", "check_mission_segments_and_energy", "check_l0_solve_and_the_hand_formulas",
                  "check_resonance_side_above_flips_the_limit", "check_h8_has_eight_rotors_and_the_coaxial_factor",
                  "check_fixed_params_are_parameters_and_free_ones_are_variables",
                  "check_the_solver_gives_a_snapshot_at_each_iteration_and_the_plotter_reads_it", "check_the_model_file_roundtrip",
                  "check_evaluate_fixes_every_param_except_the_battery_x", "check_jung_check_functions"):
        globals()["test_" + _name[len("check_"):]] = _make(_name)


if __name__ == "__main__":
    names = sys.argv[1:] or list(CHECKS)
    failed = 0
    for nm in names:
        try:
            CHECKS[nm]()
            print("ok  ", nm)
        except Exception as e:                                                      # print every failure, then exit with 1
            failed += 1
            print("FAIL", nm, type(e).__name__, e)
            import traceback
            traceback.print_exc()
    sys.exit(1 if failed else 0)
