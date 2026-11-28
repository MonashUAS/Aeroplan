"""The AeroSandbox spoke: the ADH aircraft -> the spec -> the AeroSandbox model, and the quadplane ingest. Every number
is synthetic. The quadplane ingest tests are different: they read the committed model file and base tree, and type no number.

The tests that run the worker need AeroSandbox in this Python (`pip install -e ".[sizing]"`, ADR 0030).
Without it they skip (CI has none). The other tests run everywhere.
"""
import json
import math

import numpy as np
import pytest

from aeroplan import REPO_ROOT, adh_doc, source_tree
from aeroplan.geometry import body_frames, planform_of, planform_reference
from aeroplan.spokes import Context, load
from test_openvsp import HTAIL, make_doc

asb_spoke = load("AeroSandbox")
runner = asb_spec = asb_spoke
needs_asb = pytest.mark.skipif(not runner.available(), reason="no AeroSandbox here: run `pip install -e .[sizing]`")



def _has_proptimiser():
    if not runner.available():
        return False
    return "no proptimiser" not in runner.run({"job": "version"})["version"]


needs_prop = pytest.mark.skipif(not _has_proptimiser(), reason="no Proptimiser in the AeroSandbox Python: "
                                "run `pip install -e .[prop]`")

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
    adh_doc.set_reference(doc, 0.9, 2.8, 0.33)
    air["muas"].update({
        "reference": {"mrp": {"point": {"frame": "design", "xyz": [0.2, 0.0, 0.0], "units": "m"}}},
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
        pf = planform_of(adh_doc.find(doc, inst))
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
    with pytest.raises(runner.AeroSandboxError, match="pip install"):
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


# The notebook rules are in tests/architecture (AP017).


def test_the_targets_take_the_mass_limit_that_the_model_file_has(tmp_path):
    """A model file with the competition cap and no MTOW gives the cap target only (synthetic numbers)."""
    import json

    comps = {}
    for _, comp, par, _, _ in asb_spoke.TARGETS:
        if par != "mtow_kg":
            comps.setdefault(comp, {"params": {}})["params"][par] = {"value": 1.5, "source": "test"}
    path = tmp_path / "test.json"
    path.write_text(json.dumps({"format": "aeroplan-asb-model/1", "components": comps}), encoding="utf-8")
    keys = [r["muas"]["target"]["key"] for r in asb_spoke._targets(asb_spoke.ModelFile(path))]
    assert "uas_mass_without_cargo" in keys and "mtow" not in keys and len(keys) == len(asb_spoke.TARGETS) - 1


# --------------------------------------------------------------------------------------------- the quadplane ingest
@pytest.fixture(scope="module")
def quadplane():
    """The Rosella from its model file and the base tree, on a new aircraft in memory. Nothing is written."""
    acft = source_tree.new("rosella", consumers=["review"])
    asb_spoke.ingest(acft.doc, Context("rosella", REPO_ROOT, "AeroSandbox", acft))
    base = source_tree.read(source_tree.aircraft_dir("currawong", REPO_ROOT)).doc
    return acft.doc, base


def _contacts(doc):
    return {c["name"]: c for c in adh_doc.node(doc, "1.2.2")["muas"]["ground_contacts"]}


def test_the_quadplane_has_two_boom_skids_and_a_tail_skid(quadplane):
    doc, base = quadplane
    got = _contacts(doc)
    assert sorted(got) == ["LEFT_SKID", "RIGHT_SKID", "TAIL_SKID"]
    tail = _contacts(base)["TAIL_SKID"]
    for c in got.values():
        assert c["type"] == "STRUCTURE" and c["placeholder"] is True and c["source"]
        assert c["spring_N_per_m"] == tail["spring_N_per_m"] and c["damping_N_per_m_s"] == tail["damping_N_per_m_s"]
    adh_doc.validate_document(doc)


def test_the_quadplane_skids_are_symmetric_below_the_fuselage_and_the_nose_propeller(quadplane):
    """The foot is below the lowest point of the fuselage and of the nose propeller disc, by the rotor tip clearance."""
    doc, _ = quadplane
    left, right, tail = (_contacts(doc)[n]["position"]["xyz"] for n in ("LEFT_SKID", "RIGHT_SKID", "TAIL_SKID"))
    boom_y = abs(adh_doc.find(doc, "boom_right")["muas"]["tube"]["p0"][1])
    assert right[1] == pytest.approx(boom_y) and left[1] == pytest.approx(-boom_y) and tail[1] == 0.0
    assert left[0] == right[0]
    lift_x = [it["muas"]["propeller"]["hub"]["xyz"][0] for _, it, _ in adh_doc.iter_nodes(doc)
              if ((it.get("muas") or {}).get("propeller") or {}).get("role") == "lift"]
    assert left[0] == pytest.approx(max(lift_x))                     # FRD: the front lift rotor station
    fus = max(f[:, 2].max() for f in body_frames(adh_doc.find(doc, "fuselage")["geometry"]["body"]))      # z is down
    pr = adh_doc.find(doc, "prop_cruise")["muas"]["propeller"]
    tip = pr["hub"]["xyz"][2] + 0.5 * pr["diameter"]["value"]
    gap = asb_spoke.ModelFile(asb_spoke.SETTINGS / "rosella.json").param("rotor", "tip_clearance_m")["value"]
    assert [left[2], right[2], tail[2]] == pytest.approx([max(fus, tip) + gap] * 3)
    assert tip > fus                                         # Rosella: the nose propeller sets the foot, not the fuselage
    le = adh_doc.find(doc, "htail")["geometry"]["lifting_surface"]["leading_edge_spline"]["points"][0]
    assert tail[0] == pytest.approx(le["x"])


def test_the_quadplane_cg_is_inside_the_contact_triangle(quadplane):
    """In plan view each barycentric weight of the CG is positive."""
    doc, _ = quadplane
    xy = np.array([c["position"]["xyz"][:2] for c in _contacts(doc).values()])
    cg = adh_doc.node(doc, "1.2")["muas"]["mass_properties"]["cg"]["xyz"]
    weights = np.linalg.solve(np.vstack([xy.T, np.ones(3)]), [cg[0], cg[1], 1.0])
    assert (weights > 0.0).all(), weights


def test_the_quadplane_takes_the_stall_values_of_the_base_wing(quadplane):
    doc, base = quadplane
    got = dict(adh_doc.node(doc, "1.2")["muas"]["aero_settings"])
    want = dict(adh_doc.node(base, "1.2")["muas"]["aero_settings"])
    assert got.pop("source").endswith(want.pop("source")) and got == {**want, "placeholder": True}


# ------------------------------------------------------------------------------------------- the aero dataset (from_aerosandbox)
SYN_KEYS = ("CLa", "Cma", "CLq", "Cmq", "CYb", "CYp", "CYr", "Clb", "Cnb", "Clp", "Cnp", "Clr", "Cnr",
            "CLde", "Cmde", "CDde", "Clda", "Cnda", "CYdr", "Cldr", "Cndr")
SYN_CDA = {"boom": 0.001, "nacelles": 0.004, "stopped_props": 0.005}
SYN_S = 1.0
SYN_STALL = {"CL_max": 1.2, "CL_min": -0.5, "placeholder": True}


def _synthetic_stability():
    """A stability block with test numbers (no worker): trim alpha 2 deg and elevator -3 deg."""
    return {"method": "combined", "alpha_deg": 2.0, "elevator_deg": -3.0, "speed_m_s": 20.0, "CL": 0.6, "CD": 0.03, "Cm": 0.02,
            "derivatives": {**{k: 0.1 * (i + 1) for i, k in enumerate(SYN_KEYS)}, "CLa": 5.0, "Cma": -0.5, "CLde": 0.4, "Cmde": -1.6},
            "trim_check": {"alpha_deg": 2.5, "elevator_deg": -2.0}}


def _synthetic_polar():
    """CD = 0.01 + 0.05 CL^2 inside the stall range, and one row above CL_max with a stall drag that the fit must not use."""
    rows = [{"alpha_deg": a, "CL": cl, "CD": 0.01 + 0.05 * cl ** 2, "Cm": 0.0} for a, cl in ((-2, 0.1), (0, 0.4), (4, 0.8), (8, 1.1))]
    return rows + [{"alpha_deg": 14, "CL": 1.4, "CD": 0.5, "Cm": 0.0}]


def _synthetic_buildup():
    return asb_spoke.from_aerosandbox(_synthetic_polar(), _synthetic_stability(), SYN_CDA, SYN_S, SYN_STALL, 10.0,
                                      [0.1, 0.0, 0.0], "test/asb/results.json")


def test_the_converter_gives_cl0_and_cm0_at_the_trim_in_radians():
    bu = _synthetic_buildup()
    s, d = _synthetic_stability(), _synthetic_stability()["derivatives"]
    a0, de0 = math.radians(2.0), math.radians(-3.0)
    assert bu.coefs["CL0"].value == pytest.approx(s["CL"] - d["CLa"] * a0 - d["CLde"] * de0, abs=1e-12)
    assert bu.coefs["Cm0"].value == pytest.approx(s["Cm"] - d["Cma"] * a0 - d["Cmde"] * de0, abs=1e-12)
    for k in SYN_KEYS:                                                   # no sign change and no unit change
        assert bu.coefs[k].value == d[k] and bu.coefs[k].units == "1_per_rad"
    assert bu.trim["alpha_rad"] == pytest.approx(a0) and bu.trim["elevator_rad"] == pytest.approx(de0)


def test_the_converter_fits_cd_inside_the_stall_range_and_adds_the_drag_areas():
    bu = _synthetic_buildup()
    assert bu.coefs["K"].value == pytest.approx(0.05, abs=1e-12)          # the row above CL_max (CD 0.5) is not in the fit
    assert bu.coefs["CD0"].value == pytest.approx(0.01 + sum(SYN_CDA.values()) / SYN_S, abs=1e-12)
    assert bu.coefs["CD0"].placeholder is True and "stopped_props" in bu.coefs["CD0"].source
    assert "4 rows with CL from 0.100 to 1.100" in bu.coefs["K"].source
    assert bu.coefs["CD0"].units == bu.coefs["K"].units == bu.coefs["CL0"].units == "nd"


def test_every_converted_coefficient_names_its_run_and_method():
    bu = _synthetic_buildup()
    assert len(bu.coefs) == 25
    for k, c in bu.coefs.items():
        assert c.source and "test/asb/results.json" in c.source and ("method combined" in c.source or "job polar" in c.source), k
    assert any("no propeller slipstream" in n for n in bu.notes) and any("Trim check" in n for n in bu.notes)


def test_the_build_up_gives_the_job_cl_and_cm_at_the_trim():
    from aeroplan.aero_buildup import evaluate

    bu, s = _synthetic_buildup(), _synthetic_stability()
    x = dict.fromkeys(("alpha", "beta", "phat", "qhat", "rhat", "de", "da", "dr"), 0.0)
    x.update(alpha=bu.trim["alpha_rad"], de=bu.trim["elevator_rad"])
    out = evaluate(bu, x)
    assert out["CL"] == pytest.approx(s["CL"], abs=1e-9) and out["Cm"] == pytest.approx(s["Cm"], abs=1e-9)


def test_the_converted_dml_passes_the_dtd():
    from aeroplan.aero_buildup import to_daveml
    from aeroplan.dml_validate import validate_dml

    xml = to_daveml(_synthetic_buildup(), name="Test aerodynamic model", author="test", org="MUAS", created="2026-01-01",
                    description="synthetic")
    assert validate_dml(xml) == []


def _fake_context(tmp_path):
    from types import SimpleNamespace

    return SimpleNamespace(work=tmp_path / "work", root=tmp_path, aircraft="rosella", acft=source_tree.new("rosella"))


def _write_results(tmp_path, **doc):
    f = tmp_path / "work" / "asb" / "results.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps(doc), encoding="utf-8")


def test_a_missing_or_stale_results_file_gives_one_line_and_no_dataset(tmp_path):
    mf = asb_spoke.ModelFile(asb_spoke.SETTINGS / "rosella.json")
    ctx = _fake_context(tmp_path)
    line, ref = asb_spoke._aero_dataset({"muas": {}}, {}, ctx, mf)
    assert ref is None and "missing" in line
    _write_results(tmp_path, polar={"rows": []}, inputs={"model_file_sha256": "0" * 64})
    line, ref = asb_spoke._aero_dataset({"muas": {}}, {}, ctx, mf)
    assert ref is None and "no stability block" in line
    (tmp_path / "work" / "asb" / "results.json").write_text(
        json.dumps({"stability": {"stability": {}}, "polar": {"rows": []},
                    "inputs": {"model_file_sha256": "0" * 64, "cg_frd_m": [0, 0, 0]}}), encoding="utf-8")
    line, ref = asb_spoke._aero_dataset({"muas": {}}, {}, ctx, mf)
    assert ref is None and "stale" in line


def test_a_stale_results_file_removes_the_old_aero_dataset(tmp_path):
    from aeroplan import assets

    mf = asb_spoke.ModelFile(asb_spoke.SETTINGS / "rosella.json")
    ctx = _fake_context(tmp_path)
    air = adh_doc.node(ctx.acft.doc, "1.2", create=True)
    adh_doc.muas(air, "rosella_airvehicle")
    aid = "asset:sha256:" + "a" * 64
    assets.register(ctx.acft.doc).append({"id": aid, "kind": "dataset", "name": "aero.rosella", "role": "aero model",
                                          "tool": "AeroSandbox", "media_type": "application/json", "size": 2})
    ctx.acft.datasets[aid] = {"a": 1}
    assets.set_item_dataset(air, "aero", aid)
    _write_results(tmp_path, stability={"stability": {}}, polar={"rows": []},
                   inputs={"model_file_sha256": "0" * 64, "cg_frd_m": [0, 0, 0]})
    line, ref = asb_spoke._aero_dataset(air, ctx.acft.doc, ctx, mf)
    assert ref is None and "stale" in line and "is removed" in line
    assert assets.item_dataset(air, "aero") is None and not assets.register(ctx.acft.doc) and not ctx.acft.datasets


def test_a_job_cg_that_is_not_the_tree_cg_gives_no_dataset(tmp_path):
    from aeroplan.consumers import MRP_CG_TOL_M

    mf = asb_spoke.ModelFile(asb_spoke.SETTINGS / "rosella.json")
    cg = [0.1, 0.0, 0.0]
    air = {"muas": {"mass_properties": {"cg": {"xyz": cg}}, "reference": {"mrp": {"point": {"xyz": cg}}}}}
    ctx = _fake_context(tmp_path)
    off = [cg[0] + 2 * MRP_CG_TOL_M, 0.0, 0.0]
    _write_results(tmp_path, stability={"stability": {}}, polar={"rows": []},
                   inputs={"model_file_sha256": asb_spoke._sha(mf.path), "cg_frd_m": off})
    line, ref = asb_spoke._aero_dataset(air, {}, ctx, mf)
    assert ref is None and "CG" in line


def test_the_quadplane_view_draws_the_control_surfaces_with_their_hinges(quadplane):
    """The copy drops the Currawong CAD views. The surfaces come from the ADH planform, so Aerolink can move them."""
    from aeroplan import parts

    doc, _ = quadplane
    got = parts.part_meshes(doc, REPO_ROOT).parts
    for name in ("aileron_l", "aileron_r", "elevator", "rudder"):
        assert len(got[name].tri) > 0 and got[name].hinge is not None, name
