"""The flow5 sweep runner: script and polar XML, the T6 flap table, the log diagnosis and the fits. Every number is
synthetic. A live flow5 run needs flow5 on this machine (FLOW5_EXE or an install in Program Files) and skips without it.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from aeroplan.adapters.flow5 import Polar
from aeroplan.spokes import load

load("flow5")
sw = sys.modules["aeroplan_spokes.flow5.sweep"]

PLANE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<xflplane version="1.0"><Plane><Name>synth</Name>
<Wing><Name>Main Wing</Name><Type>MAINWING</Type></Wing>
<Wing><Name>Elevator</Name><Type>ELEVATOR</Type></Wing>
<Wing><Name>Fin</Name><Type>FIN</Type></Wing>
</Plane></xflplane>
"""
INPUTS = {"S": 1.0, "b": 2.0, "cbar": 0.5, "mass": 3.0, "cg": [0.1, 0.0, 0.01], "inertia": [0.4, 0.5, 0.6, 0.01]}
SR = {"polar": {"method": "TRIUNIFORM"},
      "ranges": {"alpha_deg": [-4, 12, 2], "beta_deg": [-8, 8, 2], "control_points": 7},
      "runs": [{"name": "t7", "type": "T7"}, {"name": "alpha", "type": "T1"},
               {"name": "beta", "type": "T5"},
               {"name": "elev", "type": "T6", "control": "elevator", "surface": "Elevator", "flaps": {1: 1, 2: 1}},
               {"name": "ail", "type": "T6", "control": "aileron", "surface": "Main Wing", "flaps": {1: 1, 2: -1}},
               {"name": "rud", "type": "T6", "control": "rudder", "surface": "Fin", "flaps": {1: 1}}]}


def spec(kind="T1", **kw):
    base = dict(name="p", plane="synth", kind=kind, ref_area=1.0, ref_span=2.0, ref_chord=0.5, mass=3.0,
                cg=(0.1, 0.0, 0.01), inertia=(0.4, 0.5, 0.6, 0.01))
    return sw.PolarSpec(**{**base, **kw})


def polar(columns, rows):
    return Polar(Path("synthetic.csv"), columns, np.array(rows, float), [], None, None)


def test_polar_xml_parses_back():
    root = ET.fromstring(sw.polar_xml(spec("T1", speed=10.0, viscous=True)))
    p = root.find("Polar")
    assert p.findtext("Type") == "FIXEDSPEEDPOLAR"
    assert p.findtext("Fixed_Velocity") == "10.0"
    assert p.findtext("Viscous_Analysis/XFoil_OnTheFly") == "true"
    assert p.findtext("Use_plane_inertia") == "false"
    assert p.findtext("Reference_Dimensions/Reference_Dimensions") == "CUSTOM"
    assert p.findtext("Inertia/CoG") == "0.1, 0.0, 0.01"
    assert p.findtext("Inertia/CoG_Ixz") == "0.01"


def test_polar_xml_refuses_unknown_method_and_type():
    with pytest.raises(sw.Flow5Error):
        sw.polar_xml(spec(method="VLM3"))
    with pytest.raises(sw.Flow5Error):
        sw.polar_xml(spec(kind="T9"))


def test_t6_needs_speed_and_alpha():
    with pytest.raises(sw.Flow5Error):
        sw.polar_xml(spec("T6", angle_ranges=[[(0.0, 0.0)]]))


def test_t6_flap_table_from_surface_names():
    names = ["Main Wing", "Elevator", "Fin"]
    runs = SR["runs"]
    specs = sw._polar_specs([r for r in runs if r["type"] == "T6"], runs, SR, INPUTS, "synth", names, 10.0, 4.0)
    by = {s.name: s for s in specs}
    # one flap table for all T6 runs: tilt + flap 1 + flap 2 on the wing and the elevator, tilt + flap 1 on the fin
    assert by["elev"].angle_ranges == [[(0.0, 0.0)] * 3, [(0.0, 0.0), (-15.0, 15.0), (-15.0, 15.0)], [(0.0, 0.0)] * 2]
    assert by["ail"].angle_ranges[0] == [(0.0, 0.0), (-15.0, 15.0), (15.0, -15.0)]
    assert by["rud"].angle_ranges[2] == [(0.0, 0.0), (-15.0, 15.0)]
    root = ET.fromstring(sw.polar_xml(by["ail"]))
    assert root.findtext("Polar/Angle_range/Wing_0/Range_2") == "15.0 -15.0"
    assert root.findtext("Polar/Operating_range/Velocity") == "10.0 10.0"


def test_unknown_surface_is_refused():
    bad = {"runs": [{"name": "x", "type": "T6", "control": "elevator", "surface": "Canard", "flaps": {1: 1}}]}
    with pytest.raises(sw.Flow5Error):
        sw._load_runs(bad, ["Main Wing"], None)


def test_script_ranges_reach_the_last_control_point():
    rng = sw.script_ranges(SR, SR["runs"])
    assert rng["T12"] == (-4, 12, 2) and rng["T7"] == (0.0, 0.0, 1.0)
    lo, hi, step = rng["T6"]
    assert step == pytest.approx(1 / 6) and hi > 1.0
    n = 0
    while lo + n * step <= hi:      # the way flow5 steps a range
        n += 1
    assert n == 7
    s = sw.ScriptSpec("n", Path("o"), Path("p"), Path("q"), ranges=rng)
    root = ET.fromstring(sw.script_xml(s))
    assert root.findtext("Plane_analysis/Plane_Analysis_Data/T12_Range") == "-4, 12, 2"
    t6 = root.findtext("Plane_analysis/Plane_Analysis_Data/T6_Range").split(",")
    assert float(t6[2]) == pytest.approx(1 / 6, abs=1e-11)      # not 0.166667


def test_diagnose():
    log = "Made 6 valid analysis pairs (plane, polar) to run\nUnsuccessful attempt to trim\nOTF failures:\n"
    res = sw.diagnose(log, 0)
    assert res.pairs == 6 and not res.ok
    assert res.problems == ["Unsuccessful attempt to trim"] and len(res.lost) == 1
    clean = sw.diagnose("Made 2 valid analysis pairs (plane, polar) to run\nOTF failures:\n", 0)
    assert clean.ok and clean.pairs == 2
    assert not sw.diagnose("", 3).ok
    assert not sw.diagnose("Panel analysis completed ... Errors encountered", 0).ok


def test_control_derivatives_known_slopes():
    ctrl = np.linspace(0, 1, 7)
    delta = np.radians(-15 + ctrl * 30)
    # elevator: CL up and Cm down with the deflection
    p = polar(["Ctrl", "CL", "Cm"], np.column_stack([ctrl, 0.2 + 3.0 * delta, 0.1 - 1.2 * delta]))
    d = sw.control_derivatives(p, "elevator", -15, 15)
    assert d["CLde"]["value"] == pytest.approx(3.0) and d["Cmde"]["value"] == pytest.approx(-1.2)
    assert d["CLde"]["linearity"] == pytest.approx(0.0, abs=1e-9)
    # aileron: flow5 Cl and Cn columns have the opposite sign of the aeronautical moments
    a = polar(["Ctrl", "Cl", "Cn"], np.column_stack([ctrl, -0.15 * delta, 0.02 * delta]))
    d = sw.control_derivatives(a, "aileron", -15, 15)
    assert d["Clda"]["value"] == pytest.approx(0.15) and d["Cnda"]["value"] == pytest.approx(-0.02)


def test_control_that_does_nothing_is_refused():
    ctrl = np.linspace(0, 1, 7)
    p = polar(["Ctrl", "CL", "Cm"], np.column_stack([ctrl, np.full(7, 0.3), np.zeros(7)]))
    with pytest.raises(Exception):
        sw.control_derivatives(p, "elevator", -15, 15)


def test_validate_passes_for_a_consistent_set():
    a = np.radians(np.arange(-4, 13, 2.0))
    cla, cma = 4.5, -1.2
    alpha = polar(["alpha", "CL", "Cm"], np.column_stack([np.degrees(a), cla * a + 0.2, cma * a]))
    b = np.radians(np.arange(-8, 9, 2.0))
    beta = polar(["beta", "Cn"], np.column_stack([np.degrees(b), -0.07 * b]))     # flow5 axes: Cn column flipped
    rho_q = 0.5 * sw.RHO * 12.0 ** 2
    op = {"VInf": 12.0, "CL": INPUTS["mass"] * sw.G / (rho_q * INPUTS["S"]), "alpha": 4.0, "Cma": cma,
          "Cnb": 0.07, "NP_x": INPUTS["cg"][0] - INPUTS["cbar"] * cma / cla}
    v = sw.validate(op, {"T1:alpha": alpha, "T5:beta": beta}, INPUTS, 0, {})
    assert v["ok"], v["rows"]
    op["Cma"] = -2.5
    assert not sw.validate(op, {"T1:alpha": alpha}, INPUTS, 0, {})["ok"]


def test_dry_run_writes_both_passes(tmp_path):
    plane = tmp_path / "synth.xml"
    plane.write_text(PLANE_XML, encoding="utf-8")
    res = sw.run(plane_xml=plane, inputs=INPUTS, sr=SR, name="n", dest=tmp_path / "dest", work_root=tmp_path / "w",
                 dry_run=True, trim_hint=(12.0, 4.0))
    assert res["dry_run"] and len(res["script"]) == 2
    assert sorted(p.stem for p in (tmp_path / "w" / "pass1_t7" / "polars").glob("*.xml")) == ["t7"]
    assert sorted(p.stem for p in (tmp_path / "w" / "pass2" / "polars").glob("*.xml")) == ["ail", "alpha", "beta", "elev", "rud"]
    assert (tmp_path / "w" / "pass2" / "planes" / "synth.xml").is_file()
    assert not (tmp_path / "dest").exists()                      # a dry run does not make the sweep folder
    # without a trim hint pass 2 holds only the runs that need no trim
    res = sw.run(plane_xml=plane, inputs=INPUTS, sr=SR, name="n", dest=tmp_path / "dest", work_root=tmp_path / "w2",
                 dry_run=True)
    assert [p.stem for p in (tmp_path / "w2" / "pass2" / "polars").glob("*.xml")] == ["alpha"]


def test_run_refuses_an_unknown_run_name(tmp_path):
    plane = tmp_path / "synth.xml"
    plane.write_text(PLANE_XML, encoding="utf-8")
    with pytest.raises(sw.Flow5Error):
        sw.run(plane_xml=plane, inputs=INPUTS, sr=SR, name="n", dest=tmp_path / "d", work_root=tmp_path / "w",
               only=["nope"], dry_run=True)


def test_find_flow5_uses_the_given_path(tmp_path):
    exe = tmp_path / "flow5.exe"
    exe.write_text("")
    assert sw.find_flow5(str(exe)) == exe
    with pytest.raises(sw.Flow5Error):
        sw.find_flow5(str(tmp_path / "missing.exe"))


def test_format_result_of_a_dry_run():
    assert sw.format_result({"dry_run": True, "script": ["a"]}).startswith("dry run")


def test_find_flow5_on_this_machine():
    try:
        exe = sw.find_flow5()
    except sw.Flow5Error:
        pytest.skip("no flow5 on this machine")
    assert exe.is_file()
