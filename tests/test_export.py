"""Contract C additions: the control-system, ground and requirement schema, the aero build-up, the visual parts and the
datum rules. Every number here is a synthetic test value, not aircraft data.

The full Currawong build runs only when the environment variable AEROPLAN_AIRCRAFT_DIR names a fleet-data aircraft
folder (this repo holds no path to another repo).
"""
import math
import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from aeroplan.adapters.flow5_geometry import Section, Wing, read_t7_scalars
from aeroplan.aero_buildup import AeroBuildUp, Coefficient, _cl_table, evaluate, to_daveml
from aeroplan.datum import prop_spin
from aeroplan.dml_validate import validate_dml
from aeroplan.muas.control_system import Actuator, Autopilot, ServoOutput
from aeroplan.muas.ground import GroundContact
from aeroplan.muas.node import validate_node
from aeroplan.muas.requirement import AnalysisPoints, RequirementExt, Target, analysis_requirement, target_requirement
from aeroplan import visual as vis

SRC = {"source": "test value"}


# ---------------------------------------------------------------------------------------------------------- schema
def test_a_surface_output_needs_a_sign_and_a_throttle_has_none():
    ServoOutput(channel=1, function="aileron", targets=["aileron_l"], sign=-1, **SRC)
    with pytest.raises(ValidationError, match="sign"):
        ServoOutput(channel=1, function="aileron", targets=["aileron_l"], **SRC)
    with pytest.raises(ValidationError, match="throttle"):
        ServoOutput(channel=3, function="throttle", targets=["prop"], sign=1, **SRC)
    with pytest.raises(ValidationError, match="pwm"):
        ServoOutput(channel=3, function="throttle", targets=["prop"], pwm_min_us=1900, pwm_max_us=1100, **SRC)
    assert ServoOutput(channel=4, function="rudder", targets=["rudder"], sign=1, **SRC).ardupilot_function == 21


def test_an_autopilot_refuses_a_channel_twice():
    out = {"function": "elevator", "targets": ["elevator"], "sign": 1, **SRC}
    with pytest.raises(ValidationError, match="twice"):
        Autopilot(firmware="ArduPlane", outputs=[{"channel": 2, **out}, {"channel": 2, **out}])


def test_an_actuator_needs_a_control_surface_on_the_same_node():
    act = Actuator(tau_s=0.04, rate_limit_rad_s=5.0, **SRC).model_dump(mode="json")
    node = {"wbs_no": "1.2.2.4", "name": "Empennage", "description": "test",
            "muas": {"ext_version": "0.1.0", "instance": "elevator", "actuator": act}}
    with pytest.raises(ValueError, match="control_surface"):
        validate_node(node)
    node["muas"]["control_surface"] = {"parent": "htail", "eta_span": [0.0, 1.0], "hinge_x_over_c": 0.7,
                                       "limit_min_rad": -0.3, "limit_max_rad": 0.3, "positive_sign": "JSBSim",
                                       "s119_name": "elevatorDeflection"}
    validate_node(node)


def test_ground_contacts_need_unique_upper_case_names():
    c = {"type": "BOGEY", "position": {"xyz": [0.0, 0.0, -0.3]}, "spring_N_per_m": 1000.0, "damping_N_per_m_s": 50.0, **SRC}
    with pytest.raises(ValidationError):
        GroundContact(name="nose", **c)
    node = {"wbs_no": "1.2.2", "name": "Airframe", "description": "test",
            "muas": {"ext_version": "0.1.0", "instance": "airframe", "ground_contacts": [{"name": "NOSE", **c}] * 2}}
    with pytest.raises(ValueError, match="twice"):
        validate_node(node)


def test_a_requirement_carries_exactly_one_extension_and_upstream_adh_accepts_it():
    t = Target(key="short_period_zeta_min", value=0.3, bound="min", units="nd", **SRC)
    req = target_requirement(t, "handling", "test")
    assert req["category"] == "handling" and req["muas"]["target"]["key"] == "short_period_zeta_min"
    a = analysis_requirement(AnalysisPoints(speeds_mps=[10.0, 12.0], **SRC))
    node = {"wbs_no": "1.2", "name": "AirVehicle", "description": "test", "requirements": [req, a],
            "muas": {"ext_version": "0.1.0", "instance": "test"}}
    validate_node(node)
    with pytest.raises(ValidationError, match="exactly one"):
        RequirementExt.model_validate({})
    with pytest.raises(ValidationError, match="rising"):
        AnalysisPoints(speeds_mps=[12.0, 10.0], **SRC)


# ---------------------------------------------------------------------------------------------------------- flow5 and aero
T7 = """plane
t7

               α                 β           VInf(m/s)
           4.0                  0           12.0

               CL        CD_inviscid         CD_viscous        Cm_inviscid         Cm_viscous
         0.8          0.03                  0                  0                  0

         mass(kg)           CoG.x(m)           CoG.y(m)           CoG.z(m)               8.0           0.1                  0        -0.01

              CXa                CZa                Cma                CZq                Cmq
           0.5           -4.7           -1.3           -5.5           -17.0

              Cyb                Clb                Cnb
        -0.2          -0.07          0.07

Main Wing - flap moments (N.m)
           Flap_1
       -0.03
"""


def test_the_t7_reader_takes_label_rows_and_the_welded_mass_line(tmp_path):
    f = tmp_path / "t7.txt"
    f.write_text(T7, encoding="utf-8")
    s = read_t7_scalars(f)
    assert s["alpha"] == 4.0 and s["VInf"] == 12.0 and s["CoG_x"] == 0.1 and s["mass"] == 8.0
    assert s["Cma"] == -1.3 and s["Cnb"] == 0.07 and "Flap_1" not in s


def _buildup() -> AeroBuildUp:
    vals = {"CL0": 0.44, "CLa": 4.7, "CLq": 5.5, "CLde": 0.3, "CD0": 0.016, "K": 0.046, "CDde": 0.013, "CYb": -0.2,
            "CYp": -0.03, "CYr": 0.19, "CYdr": 0.16, "Clb": -0.07, "Clp": -0.39, "Clr": 0.06, "Clda": 0.15, "Cldr": 0.004,
            "Cm0": 0.11, "Cma": -1.35, "Cmq": -17.0, "Cmde": -1.2, "Cnb": 0.07, "Cnp": -0.02, "Cnr": -0.075,
            "Cnda": -0.019, "Cndr": -0.068}
    co = {k: Coefficient(v, "nd" if k in ("CL0", "CD0", "K", "Cm0") else "1_per_rad", "test value") for k, v in vals.items()}
    return AeroBuildUp(co, _cl_table(0.44, 4.7, 1.3, -0.6), "test", {"alpha_rad": 0.07}, [])


def test_the_cl_table_is_linear_inside_the_stall_limits():
    t = np.array(_cl_table(0.44, 4.7, 1.3, -0.6))
    assert np.all(np.diff(t[:, 0]) > 0)
    lo, hi = int(np.argmin(t[:, 1])), int(np.argmax(t[:, 1]))          # the stall points CL_min and CL_max
    assert hi == lo + 1 and t[lo, 1] == -0.6 and t[hi, 1] == 1.3
    assert np.allclose(t[[lo, hi], 1], 0.44 + 4.7 * t[[lo, hi], 0])


def test_the_aero_dml_is_valid_daveml_and_its_check_cases_follow_the_build_up():
    b = _buildup()
    data = to_daveml(b, name="test", author="Test Person", org="test", created="2026-01-01", description="test")
    assert validate_dml(data) == []
    ns = {"d": "http://daveml.org/2010/DAVEML"}
    root = ET.fromstring(data)
    shots = root.findall("d:checkData/d:staticShot", ns)
    assert len(shots) == 4
    for shot in shots:
        x = {s.find("d:varID", ns).text: float(s.find("d:signalValue", ns).text) for s in shot.findall("d:checkInputs/d:signal", ns)}
        y = {s.find("d:varID", ns).text: float(s.find("d:signalValue", ns).text) for s in shot.findall("d:checkOutputs/d:signal", ns)}
        assert y == pytest.approx(evaluate(b, x))


def test_the_aero_dml_refuses_a_missing_coefficient():
    b = _buildup()
    del b.coefs["Cnr"]
    with pytest.raises(ValueError, match="Cnr"):
        to_daveml(b, name="t", author="a", org="o", created="2026-01-01", description="d")


# ---------------------------------------------------------------------------------------------------------- visual and datum
def _blade_prop(cw: bool) -> np.ndarray:
    """Two flat blades along +z and -z, 8 in pitch, leading edge forward (-x). Clockwise seen from behind if cw."""
    tri = []
    for r in np.linspace(0.05, 0.25, 21):
        beta = math.atan(0.2032 / (2 * math.pi * r))
        for blade in (1, -1):
            for t in np.linspace(-0.02, 0.02, 5):           # chord points: t > 0 is the trailing edge side
                # the leading edge leads in the turn direction: +y at the top blade for cw
                y = -t * math.cos(beta) * blade * (1 if cw else -1)
                x = t * math.sin(beta)
                p = np.array([x, y, blade * r])
                tri.append([p, p + [0, 0, 1e-4], p + [1e-4, 0, 0]])
    return np.array(tri)


def test_the_spin_follows_the_blade_pitch():
    assert prop_spin(_blade_prop(cw=True), np.zeros(3)) == "cw"
    assert prop_spin(_blade_prop(cw=False), np.zeros(3)) == "ccw"


def test_the_stl_writer_and_reader_round_trip_and_the_axes_map():
    tri = vis.tube([0, 0, 0], [1, 0, 0], 0.05)
    back = vis.read_stl(vis.write_stl(tri, "test"), "t.stl")
    assert np.allclose(back, tri, atol=1e-6)
    assert np.allclose(vis.to_design(np.array([[[1000.0, 0, 0]] * 3]), "mm", {"axes": ["-z", "-x", "y"]})[0, 0], [0, -1, 0])


def test_a_fin_cut_at_a_hinge_line_stays_ahead_of_it():
    foil = np.array([[1.0, 0.0], [0.5, 0.06], [0.0, 0.0], [0.5, -0.06], [1.0, 0.0]])
    fin = Wing("Fin", "FIN", (1.0, 0.0, 0.0), -90.0, 0.0, True, False,
               (Section(0.0, 0.3, 0.0, 0.0, 0.0, "f"), Section(0.4, 0.2, 0.05, 0.0, 0.0, "f")))
    tri = vis.lifting_surface(fin, {"f": foil}, x_over_c_max=lambda y, le_x, chord: (1.2 - le_x) / chord)
    p = tri.reshape(-1, 3)
    assert p[:, 0].max() == pytest.approx(1.2, abs=1e-9)
    assert p[:, 2].min() == pytest.approx(0.0) and p[:, 2].max() == pytest.approx(0.4)      # Rx = -90 stands it up


def test_the_front_edge_hinge_points_along_y_or_up():
    box = vis.tube([0.0, -0.5, 0.0], [0.0, 0.5, 0.0], 0.01)
    a, b = vis.front_edge_axis(box, vertical=False)
    assert b[1] > a[1]
    fin = vis.tube([0.0, 0.0, 0.0], [0.0, 0.0, 0.4], 0.01)
    a, b = vis.front_edge_axis(fin, vertical=True)
    assert b[2] > a[2]


# ---------------------------------------------------------------------------------------------------------- full build
AIRCRAFT = os.environ.get("AEROPLAN_AIRCRAFT_DIR")


@pytest.mark.skipif(not AIRCRAFT, reason="set AEROPLAN_AIRCRAFT_DIR to a fleet-data aircraft folder")
def test_the_currawong_package_builds_and_every_datum_check_passes(tmp_path):
    from aeroplan.export_aircraft import build_aircraft_package
    from aeroplan.package import Source, verify_package

    m, rep = build_aircraft_package(Path(AIRCRAFT), tmp_path / "pkg", author="Test Person", org="test", version="0.0.0",
                                    source=Source(repo="aeroplan", commit="test"), created="2026-01-01")
    assert rep.ok and verify_package(tmp_path / "pkg").sha256 == m.sha256
    paths = {f.path for f in m.files}
    assert {"dml/aero.dml", "mass/mass_items.json", "visual/parts.json", "visual/parts/fin.stl"} <= paths
    shutil.rmtree(tmp_path / "pkg")
