"""The AeroSandbox spoke: the ADH aircraft -> the spec -> the AeroSandbox model. Every number is synthetic.

The tests that run the worker need the AeroSandbox Python of this machine (`python -m aeroplan setup AeroSandbox`).
Without it they skip (CI has none). The other tests run everywhere.
"""
import math

import numpy as np
import pytest

from aeroplan import adh_doc
from aeroplan.geometry import planform_reference
from aeroplan.spokes import load
from test_openvsp import HTAIL, make_doc

asb_spoke = load("AeroSandbox")
runner = asb_spec = asb_spoke
needs_asb = pytest.mark.skipif(not runner.available(), reason="no AeroSandbox Python here: run `python -m aeroplan setup AeroSandbox`")



def _has_proptimiser():
    if not runner.available():
        return False
    return "no proptimiser" not in runner.run({"job": "version"})["version"]


needs_prop = pytest.mark.skipif(not _has_proptimiser(), reason="no Proptimiser in the AeroSandbox Python: "
                                "run `python -m aeroplan setup AeroSandbox --proptimiser <checkout>`")

STAND_IN = {"wings": ["wing_main", "htail", "fin"], "body": "fuselage", "propeller": "prop_cruise",
            "proptimiser_design": "synthetic", "cruise_speed_output": "Cruise speed", "altitude_m": 0.0}
KV_RAD = 22.0                                       # rad/s per volt, a test value
MOTOR = {"kv_rad_s_V": KV_RAD, "i0_A": 1.2, "kappa": 1.08, "r_tot_ohm": 0.14, "q0_Nm": 0.01}


class Ctx:
    """Gives the tables of the propulsion dataset, the one thing that spec_from_doc takes from a Context."""

    def dataset(self, ref):
        return {"prop_ctcp": {"columns": {"J": [0.0, 0.5, 1.0], "CT": [0.1, 0.05, 0.0], "CP": [0.05, 0.04, 0.02]}}}


def q(value, units):
    return {"value": value, "units": units}


def make_full_doc():
    doc = make_doc()
    air = adh_doc.node(doc, "1.2")
    air["muas"].update({
        "reference": {"s_ref": q(0.9, "m^2"), "b_ref": q(2.8, "m"), "c_ref": q(0.33, "m"),
                      "mrp": {"point": {"frame": "design", "xyz": [0.2, 0.0, 0.0], "units": "m"}}},
        "mass_properties": {"mass": q(2.0, "kg"), "cg": {"frame": "design", "xyz": [0.2, 0.0, 0.0], "units": "m"},
                            "inertia": {"ixx": 0.2, "iyy": 0.3, "izz": 0.4}, "placeholder": True},
        "point_masses": [{"tag": "A", "mass": q(0.5, "kg"), "position": {"xyz": [0.0, 0.0, 0.0]}, "placeholder": True}]})
    air["performance"] = [{"name": "sizing", "tools": [{"data_exchange": {"outputs": [
        {"name": "Cruise speed", "value": 15.0, "units": "m/s", "units_basis": "magnitude"}]}}]}]
    prop = adh_doc.node(doc, "1.2.3.9", create=True)
    adh_doc.muas(prop, "prop_cruise")
    prop["muas"].update({
        "propeller": {"hub": {"xyz": [-0.6, 0.0, -0.03]}, "thrust_axis": [-1.0, 0.0, 0.0], "diameter": q(0.5, "m")},
        "datasets": [{"role": "propulsion", "ref": "x"}],
        "propulsion_system": {
            "p_max": q(900.0, "W"), "placeholder": False,
            "motor": {"kv": q(KV_RAD, "rad/s/V"), "i0": q(1.2, "A"), "kappa": 1.08, "r_tot": q(0.14, "ohm"),
                      "q0": q(0.01, "N*m"), "imax_continuous": q(60.0, "A")},
            "battery": {"cells_s": 6, "cells_p": 1, "v_nominal": q(22.2, "V"), "capacity": q(5.0 * 3600, "A*s")}}})
    return doc


# --------------------------------------------------------------------------------------------- no worker needed
def test_the_spec_inserts_sections_at_the_control_surface_ends():
    spec = asb_spec.spec_from_doc(make_full_doc(), STAND_IN, Ctx())
    wing = next(s for s in spec["surfaces"] if s["name"] == "wing_main")
    assert [round(s["xyz_le"][1], 6) for s in wing["sections"]] == [0.0, 0.77, 0.8, 1.26, 1.4]
    with_aileron = [s["xyz_le"][1] for s in wing["sections"] if s["controls"]]
    assert with_aileron == pytest.approx([0.77, 0.8])
    ail = wing["sections"][1]["controls"][0]
    assert ail["name"] == "aileron" and ail["symmetric"] is False and ail["hinge_x_over_c"] == 0.75
    fin = next(s for s in spec["surfaces"] if s["name"] == "fin")
    assert fin["mirror"] is False and fin["sections"][-1]["xyz_le"][2] > fin["sections"][0]["xyz_le"][2]


def test_the_spec_twist_holds_the_pitch_incidence_of_the_surface():
    """AeroSandbox ignores the trailing edge point, so the ry_deg of a surface must be in the section twist."""
    doc = make_full_doc()
    spec = asb_spec.spec_from_doc(doc, STAND_IN, Ctx())
    for inst in ("wing_main", "htail", "fin"):
        pf = adh_doc.find(doc, inst)["muas"]["planform"]
        got = next(s for s in spec["surfaces"] if s["name"] == inst)
        for sec in got["sections"]:
            if pf["kind"] == "FIN":
                assert sec["twist_deg"] == pytest.approx(0.0, abs=1e-9)
        if pf["kind"] != "FIN":
            first, last = pf["sections"][0], pf["sections"][-1]
            assert got["sections"][0]["twist_deg"] == pytest.approx(first["twist_deg"] + pf["ry_deg"], abs=1e-6)
            assert got["sections"][-1]["twist_deg"] == pytest.approx(last["twist_deg"] + pf["ry_deg"], abs=1e-6)


def test_the_spec_keeps_the_si_values_and_the_placeholder_flags():
    spec = asb_spec.spec_from_doc(make_full_doc(), STAND_IN, Ctx())
    assert spec["flight"]["weight_N"] == pytest.approx(2.0 * 9.80665) and spec["flight"]["speed_m_s"] == 15.0
    assert spec["propulsion"]["battery"]["capacity_As"] == pytest.approx(18000.0)
    assert spec["propulsion"]["motor"]["kv_rad_s_V"] == KV_RAD            # the document holds SI: rad/s per volt
    assert spec["propulsion"]["motor"]["r_tot_ohm"] == 0.14
    text = " ".join(asb_spec.spec_placeholders(spec))
    assert "mass model" in text and "point mass A" in text and "cruise speed" in text


def test_the_spec_has_every_body_of_the_settings():
    doc = make_full_doc()
    load("CREO").write_tubes(doc, {"tail_boom": {"node": "1.2.2.4", "name": "Tail boom", "radius_m": 0.02,
                                                 "from_instance": "fuselage", "to_instance": "htail", "source": "test"}})
    spec = asb_spec.spec_from_doc(doc, dict(STAND_IN, bodies=["fuselage", "tail_boom"]), Ctx())
    assert [b["name"] for b in spec["fuselages"]] == ["fuselage", "tail_boom"]
    assert [b["name"] for b in asb_spec.spec_from_doc(doc, STAND_IN, Ctx())["fuselages"]] == ["fuselage"]   # old key


def test_the_spec_needs_the_chain_constants():
    doc = make_full_doc()
    del adh_doc.find(doc, "prop_cruise")["muas"]["propulsion_system"]["motor"]["kappa"]
    with pytest.raises(ValueError, match="chain constants"):
        asb_spec.spec_from_doc(doc, STAND_IN, Ctx())


def test_the_runner_says_what_to_do_without_the_python(monkeypatch, tmp_path):
    monkeypatch.setenv("AEROSANDBOX_PYTHON", str(tmp_path / "missing"))
    assert not runner.available()
    with pytest.raises(runner.AeroSandboxError, match="setup AeroSandbox"):
        runner.run({"job": "version"})


# ------------------------------------------------------------------------------------------------ worker needed
@needs_asb
def test_the_chain_matches_a_hand_calculation():
    omega, torque, duty, v_bus = 400.0, 0.5, 0.6, 22.2
    r = runner.run({"job": "chain", "motor": MOTOR, "torque_Nm": torque, "omega_rad_s": omega, "duty": duty,
                    "v_bus_V": v_bus})
    i_m = MOTOR["i0_A"] + (torque + MOTOR["q0_Nm"]) * KV_RAD
    v_term = omega / (MOTOR["kappa"] * KV_RAD) + MOTOR["r_tot_ohm"] * i_m
    assert r["i_motor_A"] == pytest.approx(i_m, rel=1e-12) and r["v_term_V"] == pytest.approx(v_term, rel=1e-12)
    assert r["residual_V"] == pytest.approx(duty * v_bus - v_term, rel=1e-12)
    assert r["i_bat_A"] == pytest.approx(duty * i_m) and r["p_bat_W"] == pytest.approx(v_bus * duty * i_m)


@needs_asb
def test_the_chain_is_the_library_motor_at_kappa_one_and_no_friction():
    r = runner.run({"job": "library_check", "motor": MOTOR, "torque_Nm": 0.4, "omega_rad_s": 350.0, "v_bus_V": 22.2})
    assert r["v_term_V"] == pytest.approx(r["library_voltage_V"], rel=1e-9)
    assert r["i_motor_A"] == pytest.approx(r["library_current_A"], rel=1e-9)


@needs_asb
def test_the_airplane_has_the_planform_area_of_the_adh(tmp_path):
    spec = asb_spec.spec_from_doc(make_full_doc(), STAND_IN, Ctx())
    r = runner.run({"job": "geometry", "spec": spec, "out_dir": str(tmp_path), "main_wing": "htail"})
    ref = planform_reference(HTAIL)         # the tail has 2 deg incidence, so the two area rules differ by about 1e-5
    assert r["geometry"]["s_m2"] == pytest.approx(ref["area_m2"], rel=1e-4)
    assert r["geometry"]["b_m"] == pytest.approx(ref["span_m"], rel=1e-4)
    assert r["geometry"]["mac_m"] == pytest.approx(ref["mac_m"], rel=1e-4)
    assert (tmp_path / "three_view.png").is_file()


@needs_prop
def test_cruise_trim_balances_forces_moment_and_the_chain(tmp_path):
    spec = asb_spec.spec_from_doc(make_full_doc(), STAND_IN, Ctx())
    home = tmp_path / "home"
    runner.run({"job": "synthetic_design", "home": str(home), "name": "synthetic", "V_x": 15.0, "chord_m": 0.04,
                "beta_deg": 18.0})
    spec["propulsion"]["proptimiser_home"] = str(home)
    t = runner.run({"job": "cruise_trim", "spec": spec})["cruise_trim"]
    assert t["thrust_N"] * math.cos(math.radians(t["alpha_deg"])) == pytest.approx(t["drag_N"], rel=1e-6)
    assert t["lift_N"] + t["thrust_N"] * math.sin(math.radians(t["alpha_deg"])) == pytest.approx(spec["flight"]["weight_N"], rel=1e-6)
    assert abs(t["residual_V"]) < 1e-6 and 0.0 < t["duty"] <= 1.0
    assert t["p_bat_W"] > t["p_shaft_W"] > 0.0


# ---------------------------------------------------------------------------------------------------- the notebooks
NOTEBOOKS = sorted((runner.HERE / "notebooks").glob("*.ipynb"))


def test_the_notebooks_are_committed_with_outputs_and_stay_small():
    """A notebook in git holds its outputs, so GitHub shows the study (ADR 0024). A big output (a widget state, a figure) makes the
    repository grow on every run: each notebook stays below 5 MB. The deprecated notebooks are old files, not checked."""
    import json

    assert NOTEBOOKS, "tools/aerosandbox/notebooks has no notebook"
    for nb in NOTEBOOKS:
        assert nb.stat().st_size < 5_000_000, f"{nb.name} is {nb.stat().st_size / 1e6:.1f} MB: strip the widget state"
        d = json.loads(nb.read_text(encoding="utf-8"))
        code = [c for c in d["cells"] if c["cell_type"] == "code"]
        assert any(c.get("outputs") for c in code), f"{nb.name} has no outputs: run it and save it"
        assert "widgets" not in d.get("metadata", {}), f"{nb.name} holds a widget state"
