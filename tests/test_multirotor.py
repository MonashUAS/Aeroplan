"""The multirotor path: hubs from a CAD arm, the seed, the CSV mass model, the Propalyser rotors, the EMST maths, the body-drag
DAVE-ML, the demo shapes, the consumer check by vehicle kind and the datum rows. Every number here is synthetic.

The EMST functions use numpy only, so these tests import `tools/aerosandbox/asb_worker.py` as a plain module. The tests that run the
worker in the AeroSandbox Python skip without it (`python -m aeroplan setup AeroSandbox`).
"""
import copy
import csv
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from aeroplan import adh_doc, assets, checks, consumers, daveml_adh, daveml_eval, gltf, multirotor, multirotor_aero, source_tree
from aeroplan.datum import datum_checks
from aeroplan.dml_validate import validate_dml
from aeroplan.muas.aircraft import VisualPart
from aeroplan.muas.control_system import ServoOutput
from aeroplan.muas.propulsion import PropellerInstallation
from aeroplan.parts import part_meshes
from aeroplan.spokes import Context, load
from aeroplan.visual import box, cylinder, disc, tube
from sources import make_propalyser_h5

ROOT = Path(__file__).resolve().parents[1]
asb_spoke = load("AeroSandbox")
runner, asb_spec = asb_spoke.runner, asb_spoke.asb_spec
needs_asb = pytest.mark.skipif(not runner.available(), reason="no AeroSandbox Python here: run `python -m aeroplan setup AeroSandbox`")

_s = importlib.util.spec_from_file_location("asb_worker_under_test", runner.WORKER)
worker = importlib.util.module_from_spec(_s)
_s.loader.exec_module(worker)

# --------------------------------------------------------------------------------------------------- test settings
MR = {
    "source": "test settings",
    "arm": {"distance_mm": 1000.0, "angles_deg": {"x": 120.0, "y": 90.0, "z": 30.0},
            "design_from_cad": {"x": "z", "y": "x", "z": "y"}, "position": "rear_left"},
    "rotor": {"diameter_m": 0.4, "disc_thickness_m": 0.002, "disc_alpha": 0.3},
    "body_box": {"size_m": [0.2, 0.2, 0.1], "centre_m": [0.0, 0.0, 0.0]},
    "arm_tube": {"radius_m": 0.01}, "motor_shape": {"radius_m": 0.03, "length_m": 0.04},
    "gear": {"foot_x_m": 0.2, "foot_y_m": 0.2, "leg_length_m": 0.1, "spring_N_per_m": 1000.0,
             "damping_N_per_m_s": 50.0, "spring_source": "test"},
    "initial_altitude_m": 0.0}
ELEC = {k: {"value": v, "placeholder": True, "source": "test stand-in"} for k, v in
        (("rb_ohm", 0.01), ("rw_ohm", 0.004), ("re_ohm", 0.02), ("ia_A", 0.4), ("ip_A", 0.0), ("eta_e", 1.0),
         ("discharge_fraction", 1.0))}
ASB_SETTINGS = {"kind": "multirotor", "multirotor": MR,
                "drag": {"speed_m_s": 10.0, "altitude_m": 0.0, "combine": "max",
                         "hoerner": {"source": "test", "cd_cylinder_crossflow": 1.2, "cd_box_flat_face": 1.05},
                         "k_rotor_drag_kg": 0.0, "k_rotor_drag_source": "test stand-in 0"},
                "electrical": ELEC,
                "analysis": {"climb_rate_m_s": 2.0, "forward_speeds_m_s": [5.0, 10.0], "scan_max_m_s": 10.0,
                             "scan_step_m_s": 5.0, "sensitivity_step": 0.01, "altitude_m": 0.0}}
SPEC_SETTINGS = {"format": "csv", "workbook": "sheet.csv", "total_row": "Total Weight", "configuration": "test",
                 "hubs": ["prop_lift_1", "prop_lift_2", "prop_lift_3", "prop_lift_4"], "origin_m": [0.0, 0.0, 0.0],
                 "mrp": "from_mass", "placement_source": "test rules",
                 "placement": {"Motor": "hub", "Arm": "half_arm"},
                 "sanity": {"file": "estimate.csv", "row": "MTOW", "col": 5},
                 "subassemblies": {"Frame": {"node": "1.2.2", "instance": "airframe"},
                                   "Payload": {"node": "1.2.17", "instance": "payload"}}}
PROP_SETTINGS = {"system": "sys_x", "instance": "prop_lift_1", "rotors": ["prop_lift_1", "prop_lift_2", "prop_lift_3", "prop_lift_4"]}


def write_sheet(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)


SHEET = [["", "", "INSTRUCTIONS with\na new line", "", "", "", ""],
         ["", "", "", "", "", "", ""],
         ["", "Component", "Weight per item (g)", "Quantity (amount or cm)", "Weight (g)", "Source", "Sourced by"],
         ["Frame", "Arm", 100, 4, 400, "Weighed the physical item", "A"],
         ["", "Motor", 200, 4, 800, "Determined from CAD", "A"],
         ["", "Screws", 5, 10, 50, "I made it up", "A"],
         ["", "Unitemised weights", 0, 0, 2000, "Subassembly weight override", ""],
         ["Payload", "Camera", 300, 1, 300, "From a spec sheet", "B"],
         ["", "Unitemised weights", 0, 0, 300, "Subassembly weight override", ""],
         ["Miscellaneous", "", "", "", 0, "", ""],
         ["", "Unitemised weights", 0, 0, 0, "Subassembly weight override", ""],
         ["Total Weight", "", 2300, "/", 1550, "", ""]]


def write_settings(root, spoke, name, data):
    f = Path(root) / "tools" / spoke.lower() / "settings" / f"{name}.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def make_quad(tmp_path, *, sheet=True, propulsion=True, results=True):
    """A quadcopter built with the spokes in the build order, in a scratch root. Returns (acft, ctx function)."""
    acft = source_tree.new("quad", consumers=["review", "archive"])
    ctx = lambda n: Context("quad", tmp_path, n, acft)
    write_settings(tmp_path, "AeroSandbox", "quad", ASB_SETTINGS)
    load("AeroSandbox").ingest(acft.doc, ctx("AeroSandbox"))
    if sheet:
        write_sheet(tmp_path / "sheet.csv", SHEET)
        write_sheet(tmp_path / "estimate.csv", [["", "", "kg", "", "", ""], ["MTOW", "", "kg", "", 2.4, 2.4]])
        write_settings(tmp_path, "SpecSheet", "quad", SPEC_SETTINGS)
        load("SpecSheet").ingest(acft.doc, ctx("SpecSheet"))
    if propulsion:
        (tmp_path / "work" / "propalyser" / "quad").mkdir(parents=True, exist_ok=True)
        make_propalyser_h5(tmp_path / "work" / "propalyser" / "quad" / "sys_x.v2.h5")
        write_settings(tmp_path, "Propalyser", "quad", PROP_SETTINGS)
        load("Propalyser").ingest(acft.doc, ctx("Propalyser"))
    adh_doc.normalize(acft.doc)
    if results:
        spec = asb_spec.multirotor_spec(acft.doc, ASB_SETTINGS, ctx("AeroSandbox"))
        cd = {"CDx": 1.4, "CDy": 2.3, "CDz": 2.7}
        drag = {"speed_m_s": 10.0, "asb_over_hoerner": {"x": 0.4, "y": 1.5, "z": 1.0}, "combine": "max", "CD": cd}
        res = {"multirotor_drag": drag, "inputs": {"s_ref_m2": spec["reference"]["s_m2"], "mass_kg": spec["mass"]["mass_kg"],
                                                    "date": "2026-01-01"}}
        if propulsion:
            spec = asb_spec.multirotor_spec(acft.doc, ASB_SETTINGS, ctx("AeroSandbox"), drag=cd)
            m = worker.emst_model(spec, 1.225)
            res["emst_segments"] = {"segments": [worker.emst_hover(m), worker.emst_climb(m, 2.0), worker.emst_forward(m, 5.0)],
                                    "full_throttle": worker.emst_full_throttle(m)}
            res["emst_endurance"] = worker.emst_scan(m, 10.0, 5.0)
            res["emst_sensitivity"] = worker.emst_sensitivity(m, 6, 0.01)
        out = tmp_path / "work" / "aerosandbox" / "quad" / "asb"
        out.mkdir(parents=True)
        (out / "multirotor_results.json").write_text(json.dumps(res), encoding="utf-8")
        load("AeroSandbox").ingest(acft.doc, ctx("AeroSandbox"))
        adh_doc.normalize(acft.doc)
    acft.prune()
    return acft, ctx


# ------------------------------------------------------------------------------------------------ hubs, spin, seed
def test_arm_vector_follows_the_cad_axes():
    v = multirotor.arm_in_design(MR["arm"])
    # d = 1 m: X_cad = cos(120) = -0.5, Y_cad = cos(90) = 0, Z_cad = cos(30): design x = Z_cad, y = X_cad, z = Y_cad
    assert v == pytest.approx([math.cos(math.radians(30)), -0.5, 0.0], abs=1e-12)


def test_hubs_are_mirror_images_with_the_quad_x_pattern():
    H = multirotor.hubs(MR)
    a, b = math.cos(math.radians(30)), 0.5
    assert H[2]["hub"] == pytest.approx([a, -b, 0.0], abs=1e-12) and H[2]["position"] == "rear_left"
    assert H[1]["hub"] == pytest.approx([-a, b, 0.0], abs=1e-12)
    assert H[3]["hub"] == pytest.approx([-a, -b, 0.0], abs=1e-12) and H[4]["hub"] == pytest.approx([a, b, 0.0], abs=1e-12)
    # ArduPilot Quad X: M1 and M2 turn CCW seen from above, M3 and M4 CW. The stored sense is seen along the thrust (from below)
    assert [H[n]["spin_ardupilot"] for n in (1, 2, 3, 4)] == ["ccw", "ccw", "cw", "cw"]
    assert [H[n]["spin"] for n in (1, 2, 3, 4)] == ["cw", "cw", "ccw", "ccw"]


def test_a_cad_arm_in_the_wrong_quadrant_is_refused():
    st = copy.deepcopy(MR)
    st["arm"]["position"] = "front_left"
    with pytest.raises(ValueError, match="quadrant"):
        multirotor.hubs(st)


def test_spin_from_ardupilot_rejects_other_words():
    assert multirotor.spin_from_ardupilot("ccw") == "cw" and multirotor.spin_from_ardupilot("cw") == "ccw"
    with pytest.raises(ValueError):
        multirotor.spin_from_ardupilot("left")


def test_the_seed_writes_valid_adh_items(tmp_path):
    acft, _ = make_quad(tmp_path, sheet=False, propulsion=False, results=False)
    doc = acft.doc
    adh_doc.validate_document(doc)
    ref = adh_doc.node(doc, "1.2")["muas"]["reference"]
    assert ref["kind"] == "multirotor" and ref["design_frame"] == "x_aft_y_right_z_up_m_bodyOrigin"
    assert ref["s_ref"]["value"] == pytest.approx(0.2 * 0.1) and ref["b_ref"]["value"] == pytest.approx(1.0)
    assert ref["c_ref"]["value"] == pytest.approx(2 * math.cos(math.radians(30)))
    rot = {adh_doc.find(doc, f"prop_lift_{n}")["muas"]["propeller"]["motor"]: adh_doc.find(doc, f"prop_lift_{n}")["muas"]["propeller"]
           for n in (1, 2, 3, 4)}
    assert sorted(rot) == [1, 2, 3, 4] and all(r["role"] == "lift" and r["thrust_axis"] == [0.0, 0.0, 1.0] for r in rot.values())
    ap = adh_doc.node(doc, "1.2.5.10")["muas"]["autopilot"]
    assert ap["firmware"] == "ArduCopter"
    assert [(o["channel"], o["function"], o["targets"]) for o in ap["outputs"]] == [(n, f"motor{n}", [f"prop_lift_{n}"]) for n in (1, 2, 3, 4)]
    assert all("sign" not in o for o in ap["outputs"])
    contacts = adh_doc.node(doc, "1.2.2")["muas"]["ground_contacts"]
    assert len(contacts) == 4 and all(c["position"]["xyz"][2] == pytest.approx(-0.05 - 0.1) for c in contacts)


def test_the_seed_keeps_what_other_spokes_wrote(tmp_path):
    acft, ctx = make_quad(tmp_path, sheet=False, propulsion=True, results=False)
    first = copy.deepcopy(adh_doc.find(acft.doc, "prop_lift_3")["muas"]["propeller"])
    assert first["system"] == "sys_x"
    load("AeroSandbox").ingest(acft.doc, ctx("AeroSandbox"))                       # build again
    assert adh_doc.find(acft.doc, "prop_lift_3")["muas"]["propeller"]["system"] == "sys_x"
    assert adh_doc.find(acft.doc, "prop_lift_1")["muas"].get("propulsion_system")
    outs = adh_doc.node(acft.doc, "1.2.5.10")["muas"]["autopilot"]["outputs"]
    assert all(o["pwm_min_us"] == 1000 and o["pwm_max_us"] == 2000 for o in outs)   # the ESC end points survive


def test_a_lift_rotor_needs_a_motor_number_and_a_motor_output_has_no_sign():
    base = {"role": "lift", "hub": {"xyz": [0, 0, 0]}, "thrust_axis": [0, 0, 1], "spin": "cw", "diameter": {"value": 0.4, "units": "m"}}
    with pytest.raises(ValueError, match="motor number"):
        PropellerInstallation.model_validate(base)
    PropellerInstallation.model_validate({**base, "motor": 1})
    out = {"channel": 1, "function": "motor1", "targets": ["a"], "source": "t"}
    assert ServoOutput.model_validate(out).ardupilot_function == 33
    assert ServoOutput.model_validate({**out, "function": "motor4"}).ardupilot_function == 36
    with pytest.raises(ValueError, match="no sign"):
        ServoOutput.model_validate({**out, "sign": 1})
    with pytest.raises(ValueError, match="exactly one rotor"):
        ServoOutput.model_validate({**out, "targets": ["a", "b"]})


# ---------------------------------------------------------------------------------------------- the CSV mass model
def test_csv_mass_rollup_against_a_hand_calculation(tmp_path):
    """Hubs (+-a, +-b, h) = (0.5, 0.8, 0.1)-style: motors 0.2 kg at the hubs, arms 0.1 kg half way, the rest at the origin."""
    acft, _ = make_quad(tmp_path, propulsion=False, results=False)
    a, b, h = math.cos(math.radians(30)), 0.5, 0.0
    # the hand calculation: 4 motors of 0.2 kg at (+-a, +-b, h), 4 arms of 0.1 kg at half that, 1.1 kg at the origin
    mm, ma, m0 = 0.2, 0.1, 0.8 + 0.3
    M = 4 * mm + 4 * ma + m0
    assert M == pytest.approx(2.3)
    mp = adh_doc.node(acft.doc, "1.2")["muas"]["mass_properties"]
    assert mp["mass"]["value"] == pytest.approx(2.3, abs=1e-12)
    assert mp["cg"]["xyz"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)                 # h = 0 and symmetric hubs
    ixx = 4 * mm * b ** 2 + 4 * ma * (b / 2) ** 2
    iyy = 4 * mm * a ** 2 + 4 * ma * (a / 2) ** 2
    izz = 4 * mm * (a ** 2 + b ** 2) + 4 * ma * ((a / 2) ** 2 + (b / 2) ** 2)
    I = mp["inertia"]
    assert (I["ixx"], I["iyy"], I["izz"]) == pytest.approx((ixx, iyy, izz), rel=1e-12)
    assert izz == pytest.approx(ixx + iyy)                                              # a flat body: Izz = Ixx + Iyy
    assert (I["ixy"], I["ixz"], I["iyz"]) == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
    ref = adh_doc.node(acft.doc, "1.2")["muas"]["reference"]
    assert ref["mrp"]["point"]["xyz"] == mp["cg"]["xyz"] and ref["nominal_cg"]["xyz"] == mp["cg"]["xyz"]
    # the subassemblies add to the air vehicle (the sheet total) and the 26... point masses are tagged by motor
    pms = adh_doc.node(acft.doc, "1.2")["muas"]["point_masses"]
    assert sum(p["mass"]["value"] for p in pms) == pytest.approx(2.3) and len(pms) == 4 + 4 + 2
    assert {p["tag"] for p in pms} >= {"MOTOR-M1", "MOTOR-M4", "ARM-M2", "FRAME-REST", "PAYLOAD-REST"}
    assert all(p["placeholder"] for p in pms if p["tag"].endswith("REST"))


def test_csv_mass_with_a_height_gives_the_cg_and_the_products():
    """Two hubs, asymmetric: Ixy and the CG by hand. Motors of 1 kg at (0.5, 0.2, 0) and (-0.1, 0.4, 0), 1 kg at the origin."""
    from aeroplan import mass_model

    pms = [{"mass_kg": 1.0, "xyz": [0.5, 0.2, 0.0]}, {"mass_kg": 1.0, "xyz": [-0.1, 0.4, 0.0]}, {"mass_kg": 1.0, "xyz": [0, 0, 0]}]
    r = mass_model.rollup(pms)
    assert r["cg"] == pytest.approx([0.4 / 3, 0.2, 0.0])
    # sum m (x - xc)(y - yc): 0 + (-0.1 - 0.13333)(0.4 - 0.2) + (-0.13333)(-0.2) = -0.0466667 + 0.0266667
    assert r["inertia"]["ixy"] == pytest.approx(-0.02)
    assert r["inertia"]["izz"] == pytest.approx((0.5 - 0.4 / 3) ** 2 + 0.0 + (-0.1 - 0.4 / 3) ** 2 + 0.2 ** 2 + (0.4 / 3) ** 2 + 0.2 ** 2)


def test_csv_sheet_reader(tmp_path):
    sheet = load("SpecSheet")
    write_sheet(tmp_path / "s.csv", SHEET)
    d = sheet.read_workbook(tmp_path / "s.csv", {"format": "csv", "total_row": "Total Weight"})
    assert d["total_g"] == 2300 and d["groups"]["Frame"]["total_g"] == 2000 and d["groups"]["Miscellaneous"]["total_g"] == 0
    arm = d["groups"]["Frame"]["parts"][0]
    assert (arm["name"], arm["each_g"], arm["qty"], arm["mass_g"]) == ("Arm", 100, 4, 400)
    assert d["groups"]["Frame"]["parts"][2]["placeholder"] is True               # "I made it up"


def test_csv_totals_that_do_not_add_up_are_refused(tmp_path):
    rows = [r[:] for r in SHEET]
    rows[-1][2] = 2400
    write_sheet(tmp_path / "s.csv", rows)
    with pytest.raises(ValueError, match="add to"):
        load("SpecSheet").read_workbook(tmp_path / "s.csv", {"format": "csv", "total_row": "Total Weight"})


def test_csv_without_the_total_row_is_refused(tmp_path):
    write_sheet(tmp_path / "s.csv", SHEET[:-1])
    with pytest.raises(ValueError, match="Total Weight"):
        load("SpecSheet").read_workbook(tmp_path / "s.csv", {"format": "csv", "total_row": "Total Weight"})


def test_csv_placement_needs_one_item_for_each_hub(tmp_path):
    sheet = load("SpecSheet")
    write_sheet(tmp_path / "s.csv", SHEET)
    data = sheet.read_workbook(tmp_path / "s.csv", {"format": "csv", "total_row": "Total Weight"})
    hubs = [{"motor": n, "instance": f"r{n}", "xyz": [n, 0, 0]} for n in (1, 2, 3)]
    with pytest.raises(ValueError, match="number of hubs"):
        sheet.build_point_masses_csv(data, SPEC_SETTINGS, hubs)
    bad = dict(SPEC_SETTINGS, placement={"Nonsense": "hub"})
    with pytest.raises(ValueError, match="no row"):
        sheet.build_point_masses_csv(data, bad, hubs)
    with pytest.raises(ValueError, match="use hub or half_arm"):
        sheet.build_point_masses_csv(data, dict(SPEC_SETTINGS, placement={"Arm": "origin"}), hubs)


def test_csv_mode_notes_the_estimate_sheet_as_a_sanity_check(tmp_path):
    acft, _ = make_quad(tmp_path, propulsion=False, results=False)
    air = adh_doc.node(acft.doc, "1.2")["muas"]
    roles = [assets.entry(acft.doc, s["asset"])["role"] for s in air["sources"] if s["tool"] == "SpecSheet"]
    assert any("sanity check only" in r for r in roles) and any("weight log" in r for r in roles)
    out = load("SpecSheet").ingest(copy.deepcopy(acft.doc), Context("quad", tmp_path, "SpecSheet", acft))
    assert any("sanity check only" in c and "an estimate sheet, not truth" in c and "-0.1000 kg" in c for c in out)


def test_the_hubs_must_exist_before_the_sheet_is_read(tmp_path):
    acft = source_tree.new("quad")
    write_sheet(tmp_path / "sheet.csv", SHEET)
    write_settings(tmp_path, "SpecSheet", "quad", SPEC_SETTINGS)
    with pytest.raises(ValueError, match="AeroSandbox seed"):
        load("SpecSheet").ingest(acft.doc, Context("quad", tmp_path, "SpecSheet", acft))


# ----------------------------------------------------------------------------------------------------- Propalyser
def test_propalyser_names_the_system_on_every_rotor(tmp_path):
    acft, _ = make_quad(tmp_path, sheet=False, results=False)
    systems = {adh_doc.find(acft.doc, f"prop_lift_{n}")["muas"]["propeller"]["system"] for n in (1, 2, 3, 4)}
    assert systems == {"sys_x"}
    owners = [i for _, i, _ in adh_doc.iter_nodes(acft.doc) if (i.get("muas") or {}).get("propulsion_system")]
    assert [o["muas"]["instance"] for o in owners] == ["prop_lift_1"]            # stored once
    ds = [e for e in assets.register(acft.doc, create=False) if e.get("dataset_role") == "propulsion"]
    assert len(ds) == 1


def test_propalyser_skips_with_a_note_without_the_file(tmp_path, capsys):
    acft = source_tree.new("quad")
    write_settings(tmp_path, "Propalyser", "quad", PROP_SETTINGS)
    assert load("Propalyser").ingest(acft.doc, Context("quad", tmp_path, "Propalyser", acft)) is None
    assert "is not here: spoke skipped" in capsys.readouterr().out


def test_propalyser_rotor_that_does_not_exist_is_refused(tmp_path):
    acft = source_tree.new("quad")
    (tmp_path / "work" / "propalyser" / "quad").mkdir(parents=True)
    make_propalyser_h5(tmp_path / "work" / "propalyser" / "quad" / "sys_x.v2.h5")
    write_settings(tmp_path, "Propalyser", "quad", PROP_SETTINGS)
    with pytest.raises(ValueError, match="no muas.propeller"):
        load("Propalyser").ingest(acft.doc, Context("quad", tmp_path, "Propalyser", acft))


# ----------------------------------------------------------------------------------- ArduPilot (flight events and flight files)
def test_ardupilot_flight_stub_waits_for_the_log(tmp_path, capsys):
    acft = source_tree.new("quad")
    st = {"releases": [], "flights": [{"event_id": "f1", "wait_for_log": True, "date": "FILL_IN", "log": "x.BIN",
                                        "firmware": "FILL_IN", "aircraft_version": "FILL_IN", "mass_kg": "document",
                                        "cg_m": "document", "source": "FILL_IN"}]}
    write_settings(tmp_path, "ArduPilot", "quad", st)
    ap = load("ArduPilot")
    assert ap.ingest(acft.doc, Context("quad", tmp_path, "ArduPilot", acft)) is None
    assert "flight skipped" in capsys.readouterr().out
    st["flights"][0].update(wait_for_log=False, firmware="r1")
    st["releases"] = [{"release_id": "r1", "firmware": "ArduCopter", "version": "4.5.0", "source": "test"}]
    write_settings(tmp_path, "ArduPilot", "quad", st)
    with pytest.raises(ValueError, match="is not in"):
        ap.ingest(acft.doc, Context("quad", tmp_path, "ArduPilot", acft))


def test_ardupilot_flight_takes_the_mass_model_of_the_document(tmp_path):
    acft, ctx = make_quad(tmp_path, propulsion=False, results=False)
    (tmp_path / "work" / "ardupilot" / "quad").mkdir(parents=True)
    (tmp_path / "work" / "ardupilot" / "quad" / "f1.BIN").write_bytes(b"synthetic log")
    st = {"releases": [{"release_id": "r1", "firmware": "ArduCopter", "version": "4.5.0", "source": "test"}],
          "flights": [{"event_id": "f1", "wait_for_log": True, "date": "2026-02-03", "log": "f1.BIN", "firmware": "r1",
                       "aircraft_version": "0.1.0", "mass_kg": "document", "cg_m": "document", "segments": [], "source": "test"}]}
    write_settings(tmp_path, "ArduPilot", "quad", st)
    out = load("ArduPilot").ingest(acft.doc, ctx("ArduPilot"))
    ev = adh_doc.node(acft.doc, "1.8.1.4")["muas"]["flight_tests"][0]
    assert ev["mass"]["value"] == pytest.approx(2.3) and out


def test_ardupilot_optional_parm_is_skipped_with_a_note(tmp_path, capsys):
    acft = source_tree.new("quad")
    write_settings(tmp_path, "ArduPilot", "quad", {"flight_files": {"optional": True, "firmware": "ArduCopter", "parameters": "q.parm"}})
    mp = load("ArduPilot")
    assert mp.ingest(acft.doc, Context("quad", tmp_path, "ArduPilot", acft)) is None
    assert "parameters skipped" in capsys.readouterr().out
    write_settings(tmp_path, "ArduPilot", "quad", {"flight_files": {"firmware": "ArduCopter", "parameters": "q.parm"}})
    with pytest.raises(Exception, match="not in"):
        mp.ingest(acft.doc, Context("quad", tmp_path, "ArduPilot", acft))


# ---------------------------------------------------------------------------------------------------------- EMST
FOM, CT0, DIAM, RHO = 0.7, 0.1, 0.5, 1.2


def emst_model(**over):
    cp0 = CT0 ** 1.5 * math.sqrt(2.0 / math.pi) / FOM          # FoM = CT^1.5 sqrt(2/pi) / CP  (momentum theory)
    m = {"rho": RHO, "n_rotors": 4, "diameter_m": DIAM, "mass_kg": 8.0, "tab": {"J": [0.0, 1.0], "CT": [CT0, CT0], "CP": [cp0, cp0]},
         "motor": {"kv_rad_s_V": 15.0, "i0_A": 1.0, "kappa": 1.0, "r_tot_ohm": 0.05, "q0_Nm": 0.0}, "v_nominal_V": 40.0,
         "capacity_As": 10 * 3600.0,
         "electrical": {"rb_ohm": 0.0, "rw_ohm": 0.0, "re_ohm": 0.0, "ia_A": 0.0, "ip_A": 0.0, "eta_e": 1.0, "discharge_fraction": 1.0},
         "drag": {"S_ref_m2": 0.06, "CDx": 0.5, "CDy": 1.0, "CDz": 1.0, "k_rotor_drag_kg": 0.0}, "throttle_map": None, "p_max_W": None}
    m.update(over)
    return m


def test_emst_hover_power_is_the_momentum_theory_power_over_the_figure_of_merit():
    m = emst_model()
    h = worker.emst_hover(m)
    W, A = 8.0 * worker.G0, math.pi * DIAM ** 2 / 4.0
    p_ideal = 4.0 * (W / 4.0) ** 1.5 / math.sqrt(2.0 * RHO * A)
    assert h["thrust_total_N"] == pytest.approx(W) and h["p_shaft_W"] == pytest.approx(p_ideal / FOM, rel=1e-12)
    n = math.sqrt(W / 4.0 / (CT0 * RHO * DIAM ** 4))                        # T = CT rho n^2 D^4
    assert h["rev_s"] == pytest.approx(n, rel=1e-9) and h["rpm"] == pytest.approx(60.0 * n, rel=1e-9)


def test_emst_electrical_chain_against_the_hand_formulas():
    m = emst_model()
    h = worker.emst_hover(m)
    q = h["torque_Nm"]
    i_m = 1.0 + q * 15.0                                                   # I0 + Q Kv
    v_term = 2 * math.pi * h["rev_s"] / 15.0 + 0.05 * i_m                  # w / (kappa Kv) + R I
    assert h["i_motor_A"] == pytest.approx(i_m) and h["v_term_V"] == pytest.approx(v_term)
    assert h["duty"] == pytest.approx(v_term / 40.0)                       # no resistance on the bus: d = V_term / V_bus
    assert h["i_total_A"] == pytest.approx(4 * h["duty"] * i_m)            # eq. (11) and (12) with Ia = Ip = 0 and etaE = 1
    assert h["endurance_min"] == pytest.approx(10 * 3600.0 / h["i_total_A"] / 60.0)


def test_emst_bus_resistance_and_the_paper_equation_9():
    """With Rb, Rw: d V_bus = V_term and V_bus = V0 - (Rb + Rw) Id (eq. 9 with the bus current)."""
    m = emst_model()
    m["electrical"].update(rb_ohm=0.02, rw_ohm=0.01, ia_A=1.0)
    h = worker.emst_hover(m)
    v0 = 40.0 - 0.02 * 1.0
    assert h["v_bus_V"] == pytest.approx(v0 - 0.03 * h["i_drive_A"]) and h["duty"] * h["v_bus_V"] == pytest.approx(h["v_term_V"])
    assert h["i_total_A"] == pytest.approx(h["i_drive_A"] + 1.0) and h["i_drive_A"] == pytest.approx(4 * h["duty"] * h["i_motor_A"])
    assert h["p_battery_W"] == pytest.approx(40.0 * h["i_total_A"])


def test_emst_climb_needs_more_thrust_and_power_than_hover():
    m = emst_model()
    c = worker.emst_climb(m, 2.0)
    h = worker.emst_hover(m)
    drag = 0.5 * RHO * 0.06 * 1.0 * 2.0 ** 2
    assert c["thrust_total_N"] == pytest.approx(h["thrust_total_N"] + drag) and c["axial_inflow_m_s"] == 2.0
    assert c["p_shaft_W"] > h["p_shaft_W"] and c["rpm"] > h["rpm"]


def test_emst_forward_flight_tilt_loop_balances_the_forces():
    m = emst_model()
    f = worker.emst_forward(m, 10.0)
    th, T, W = math.radians(f["tilt_deg"]), f["thrust_total_N"], 8.0 * worker.G0
    u, w = 10.0 * math.cos(th), -10.0 * math.sin(th)
    fx, _, fz = worker.body_force(u, 0.0, w, 4 * f["rev_s"], m)
    assert T * math.sin(th) + fx * math.cos(th) - fz * math.sin(th) == pytest.approx(0.0, abs=1e-8)       # horizontal
    assert -T * math.cos(th) + fx * math.sin(th) + fz * math.cos(th) + W == pytest.approx(0.0, abs=1e-8)  # vertical
    assert f["tilt_deg"] > 0 and f["axial_inflow_m_s"] == pytest.approx(10.0 * math.sin(th))
    assert worker.emst_forward(m, 0.0)["name"] == "hover"


def test_emst_rotor_drag_term_tilts_the_vehicle_more():
    m0, m1 = emst_model(), emst_model()
    m1["drag"]["k_rotor_drag_kg"] = 0.02
    assert worker.emst_forward(m1, 10.0)["tilt_deg"] > worker.emst_forward(m0, 10.0)["tilt_deg"]


def test_emst_full_throttle_is_duty_one_and_gives_a_thrust_to_weight():
    m = emst_model()
    f = worker.emst_full_throttle(m)
    assert f["duty_check"] == pytest.approx(1.0, abs=1e-9) and f["thrust_to_weight"] > 1.0
    assert f["thrust_total_N"] == pytest.approx(4 * CT0 * RHO * f["rev_s"] ** 2 * DIAM ** 4)


def test_emst_refuses_a_thrust_the_table_cannot_give():
    m = emst_model()
    with pytest.raises(ValueError, match="no thrust"):
        worker.solve_speed(1e6, 0.0, m)


def test_emst_throttle_command_comes_from_the_static_map():
    m = emst_model(throttle_map={"esc_command_norm": [0.0, 0.5, 1.0], "power_fraction": [0.0, 0.25, 1.0]}, p_max_W=2000.0)
    assert worker.throttle_command(500.0, m) == pytest.approx(0.5)
    assert worker.emst_hover(m)["esc_command_equiv"] is not None and worker.throttle_command(1.0, emst_model()) is None


def test_emst_scan_and_sensitivity_signs():
    m = emst_model()
    sc = worker.emst_scan(m, 10.0, 5.0)
    assert [r["speed_m_s"] for r in sc["rows"]] == [0.0, 5.0, 10.0] and sc["best_range"]["speed_m_s"] > 0
    se = worker.emst_sensitivity(m, 6, 0.01)["parameters"]
    assert se["mass_kg"]["d_endurance_min_per_unit"] < 0                    # more mass, less endurance
    assert se["diameter_m"]["d_endurance_min_per_unit"] > 0                 # a larger rotor is more efficient
    assert set(se) == {"kv_rpm_per_V", "diameter_m", "mass_kg", "capacity_As"}


def fake_live(m, ct_factor=1.0, cp_factor=1.0):
    """A live rotor function (n, v_ax) that copies the constant table of emst_model(), scaled. It stands for the BEMT."""
    def fn(n, v_ax):
        ct, cp = worker.rotor_coeffs(m["tab"], v_ax / (n * m["diameter_m"]))
        ct, cp = ct * ct_factor, cp * cp_factor
        p = cp * m["rho"] * n ** 3 * m["diameter_m"] ** 5
        return {"thrust_N": ct * m["rho"] * n ** 2 * m["diameter_m"] ** 4, "torque_Nm": p / (2.0 * math.pi * n),
                "p_shaft_W": p, "J": v_ax / (n * m["diameter_m"]), "CT": ct, "CP": cp}
    return fn


def test_emst_live_model_equal_to_the_table_gives_the_table_result():
    m = emst_model()
    live = worker.live_segment("hover", 0.0, m["mass_kg"] * worker.G0, [fake_live(m)] * 4, m)
    ref = worker.emst_hover(m)
    for k in ("rpm", "p_shaft_each_W", "p_battery_W", "i_total_A", "endurance_min", "duty"):
        assert live[k] == pytest.approx(ref[k], rel=1e-6)
    assert len(live["rotors"]) == 4 and all(r["thrust_N"] == pytest.approx(m["mass_kg"] * worker.G0 / 4, rel=1e-6) for r in live["rotors"])


def test_emst_live_model_with_less_thrust_turns_faster_and_uses_more_power():
    m = emst_model()
    ref = worker.emst_hover(m)
    live = worker.live_segment("hover", 0.0, m["mass_kg"] * worker.G0, [fake_live(m, ct_factor=0.9)] * 4, m)
    assert live["rpm"] == pytest.approx(ref["rpm"] / math.sqrt(0.9), rel=1e-5)         # T ~ CT n^2 at the same weight
    assert live["p_shaft_each_W"] > ref["p_shaft_each_W"] and live["p_battery_W"] > ref["p_battery_W"]
    assert live["endurance_min"] < ref["endurance_min"]


def test_emst_live_climb_carries_the_body_drag_and_refuses_a_wrong_rotor_count():
    m = emst_model()
    c = worker.live_segment("climb", 2.0, m["mass_kg"] * worker.G0 + worker.body_force(0.0, 0.0, -2.0, 0.0, m)[2], [fake_live(m)] * 4, m)
    assert c["thrust_total_N"] > m["mass_kg"] * worker.G0 and c["axial_inflow_m_s"] == 2.0
    with pytest.raises(ValueError, match="live rotor models"):
        worker.live_segment("hover", 0.0, 10.0, [fake_live(m)] * 3, m)


def test_emst_live_secant_refuses_a_thrust_that_it_cannot_reach():
    m = emst_model()
    dead = lambda n, v: {"thrust_N": 1.0, "torque_Nm": 0.1, "p_shaft_W": 1.0, "J": 0.0, "CT": 0.0, "CP": 0.0}
    with pytest.raises(ValueError, match="live propeller model"):
        worker.solve_speed(20.0, 0.0, {**m, "live": dead})


def _has_proptimiser():
    return runner.available() and "no proptimiser" not in runner.run({"job": "version"})["version"]


needs_prop = pytest.mark.skipif(not _has_proptimiser(), reason="no Proptimiser in the AeroSandbox Python: "
                                "run `python -m aeroplan setup AeroSandbox --proptimiser <checkout>`")


@needs_prop
def test_the_emst_live_job_runs_the_bemt_for_each_rotor(tmp_path):
    home = tmp_path / "home"
    runner.run({"job": "synthetic_design", "home": str(home), "name": "synthetic", "V_x": 0.0, "chord_m": 0.04, "beta_deg": 18.0})
    m = emst_model(diameter_m=0.55, mass_kg=6.0)   # the synthetic blade has R_tip 0.275 m
    spec = {"kind": "multirotor", "rotors": [{}, {}], "mass": {"mass_kg": 6.0}, "electrical": dict(ELEC_VALUES),
            "analysis": {"climb_rate_m_s": 1.0, "altitude_m": 0.0},
            "drag": m["drag"],
            "propulsion": {"diameter_m": 0.55, "p_max_W": None, "motor": {k: m["motor"][k] for k in ("kv_rad_s_V", "i0_A", "kappa", "r_tot_ohm")},
                           "battery": {"v_nominal_V": 22.2, "cells_s": 6, "capacity_As": 18000.0},
                           "tables": m["tab"], "throttle_map": None},
            "live": {"home": str(home), "designs": ["synthetic"]}}
    r = runner.run({"job": "emst_live", "spec": spec})["emst_live"]
    h = r["designs"]["synthetic"]["hover"]
    weight = 6.0 * worker.G0
    assert h["thrust_total_N"] == pytest.approx(weight, rel=1e-9) and len(h["rotors"]) == 2
    assert all(x["thrust_N"] == pytest.approx(weight / 2, rel=1e-5) for x in h["rotors"])
    assert h["p_shaft_each_W"] > 0.0 and h["p_battery_W"] > h["p_shaft_each_W"] * 2
    assert r["designs"]["synthetic"]["climb"]["thrust_total_N"] > weight


ELEC_VALUES = {k: v["value"] for k, v in ELEC.items()}


def test_the_report_and_the_sizing_outputs_list_the_live_propeller():
    m = emst_model()
    seg = worker.live_segment("hover", 0.0, m["mass_kg"] * worker.G0, [fake_live(m)] * 4, m)
    clim = worker.live_segment("climb", 2.0, m["mass_kg"] * worker.G0, [fake_live(m)] * 4, m)
    lv = {"rho_kg_m3": RHO, "n_rotors": 4, "table": {"hover": worker.emst_hover(m), "climb": worker.emst_climb(m, 2.0)},
          "designs": {"fit_c": {"hover": seg, "climb": clim}}}
    out = asb_spoke._emst_outputs({"emst_live": lv})
    names = {o["name"] for o in out}
    assert "hover_live_fit_c_rpm" in names and "climb_live_fit_c_p_battery_W" in names
    text = asb_spec.multirotor_report(
        {}, {"multirotor_drag": {"speed_m_s": 1.0, "rho_kg_m3": 1.2, "S_ref_m2": 0.1, "CdA_asb_m2": dict(x=1, y=1, z=1),
                                 "hoerner_CdA_m2": dict(x=1, y=1, z=1), "asb_over_hoerner": dict(x=1, y=1, z=1),
                                 "asymmetry": dict(x=0, y=0, z=0), "CdA_m2": dict(x=1, y=1, z=1),
                                 "CD": dict(CDx=1, CDy=1, CDz=1), "combine": "max"},
             "emst_live": lv, "inputs": {"proptimiser_files_sha256": {"fit_c.yaml": "ab" * 32}}}, [])
    assert "Live propeller" in text and "| maker table | hover |" in text and "| fit_c | climb |" in text and "ab" * 32 in text


def test_isa_density_at_sea_level_and_height():
    assert worker.isa_density(0.0) == pytest.approx(1.225, rel=1e-3) and worker.isa_density(1000.0) < worker.isa_density(0.0)


# ---------------------------------------------------------------------------------------------------- body drag file
def drag_coefs():
    src = {k: ("test", True) for k in multirotor_aero.CONSTANTS}
    return multirotor_aero.coefficients(0.06, {"CDx": 1.4, "CDy": 2.3, "CDz": 2.7}, 0.01, src)


def test_body_drag_dml_passes_the_dtd_and_the_check_cases():
    xml = multirotor_aero.to_daveml(drag_coefs(), name="t", author="a", org="o", created="2026-01-01", description="d")
    assert validate_dml(xml) == []
    d = daveml_adh.from_xml(xml)
    shots = daveml_eval.run_check_data(d)
    assert len(shots) == len(multirotor_aero.CHECK_POINTS) and all(s.passed for s in shots)
    assert daveml_adh.compare(xml, daveml_adh.to_xml(d)) == []              # lossless round trip


def test_body_drag_forces_oppose_the_velocity_and_match_the_formula():
    d = daveml_adh.from_xml(multirotor_aero.to_daveml(drag_coefs(), name="t", author="a", org="o", created="2026-01-01", description="d"))
    model = daveml_eval.Model(d)
    x = {"u": 6.0, "v": -5.0, "w": 2.5, "n_sum": 120.0, "rho": 1.2}
    out = model.evaluate(x)
    q = 0.5 * 1.2 * 0.06
    assert out["Fx"] == pytest.approx(-q * 1.4 * 36.0 - 0.01 * 120.0 * 6.0)
    assert out["Fy"] == pytest.approx(q * 2.3 * 25.0 + 0.01 * 120.0 * 5.0)       # v < 0: the force is positive
    assert out["Fz"] == pytest.approx(-q * 2.7 * 6.25)
    rest = model.evaluate({"u": 0.0, "v": 0.0, "w": 0.0, "n_sum": 0.0, "rho": 1.225})
    assert rest["Fx"] == rest["Fy"] == rest["Fz"] == 0.0


def test_body_drag_has_no_moments_and_names_the_aerolink_variables():
    d = daveml_adh.from_xml(multirotor_aero.to_daveml(drag_coefs(), name="t", author="a", org="o", created="2026-01-01", description="d"))
    ids = {v["var_id"] for v in d["variable_def"]}
    assert ids == {"u", "v", "w", "n_sum", "rho", "S_ref", "CDx", "CDy", "CDz", "k_rotor_drag", "Fx", "Fy", "Fz"}
    outputs = {v["var_id"] for v in d["variable_def"] if "is_output" in v}
    assert outputs == {"Fx", "Fy", "Fz"}


def test_body_drag_needs_a_source_for_every_constant():
    with pytest.raises(ValueError, match="no source"):
        multirotor_aero.coefficients(0.06, {"CDx": 1, "CDy": 1, "CDz": 1}, 0.0, {"S_ref": ("t", True)})


# ----------------------------------------------------------------------------------------------- demo shapes, glTF
def signed_volume(tri):
    t = np.asarray(tri, float)
    return float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6.0)


def test_box_has_twelve_outward_triangles_and_the_right_volume():
    t = box([1.0, 2.0, 3.0], [0.2, 0.4, 0.6])
    assert t.shape == (12, 3, 3) and signed_volume(t) == pytest.approx(0.2 * 0.4 * 0.6)
    p = t.reshape(-1, 3)
    assert p.min(axis=0) == pytest.approx([0.9, 1.8, 2.7]) and p.max(axis=0) == pytest.approx([1.1, 2.2, 3.3])
    with pytest.raises(ValueError):
        box([0, 0, 0], [0.1, 0.0, 0.1])


def test_tube_cylinder_and_disc_volumes():
    n = 16
    a = 0.5 * n * math.sin(2 * math.pi / n)                                   # polygon area / r^2
    assert signed_volume(tube([0, 0, 0], [0, 0, 2.0], 0.1, sides=n)) == pytest.approx(a * 0.01 * 2.0)
    c = cylinder([1, 1, 1], [0, 0, 1], 0.5, 0.2, sides=24)
    assert signed_volume(c) == pytest.approx(0.5 * 24 * math.sin(2 * math.pi / 24) * 0.04 * 0.5)
    assert c.reshape(-1, 3).min(axis=0)[2] == pytest.approx(0.75) and c.reshape(-1, 3).max(axis=0)[2] == pytest.approx(1.25)
    d = disc([0, 0, 1], [0, 0, 1], 0.25, 0.002)
    z = d.reshape(-1, 3)[:, 2]
    assert z.max() - z.min() == pytest.approx(0.002) and np.hypot(*d.reshape(-1, 3)[:, :2].T).max() == pytest.approx(0.25)
    with pytest.raises(ValueError):
        cylinder([0, 0, 0], [0, 0, 1], 0.0, 0.1)


def test_visual_part_shapes_are_checked():
    ok = {"part": "p", "generator": "box", "shape": {"centre": [0, 0, 0], "size": [1, 1, 1]}, "source": "t"}
    VisualPart.model_validate(ok)
    with pytest.raises(ValueError, match="needs `shape`"):
        VisualPart.model_validate({"part": "p", "generator": "disc", "source": "t"})
    with pytest.raises(ValueError, match="needs exactly"):
        VisualPart.model_validate({**ok, "shape": {"centre": [0, 0, 0]}})
    with pytest.raises(ValueError, match="three numbers"):
        VisualPart.model_validate({**ok, "shape": {"centre": [0, 0], "size": [1, 1, 1]}})
    VisualPart.model_validate({"part": "d", "generator": "disc", "source": "t",
                               "shape": {"centre": [0, 0, 0], "axis": [0, 0, 1], "radius_m": 0.1, "thickness_m": 0.001, "alpha": 0.3}})


def test_the_seeded_aircraft_makes_all_its_view_parts(tmp_path):
    acft, _ = make_quad(tmp_path, sheet=False, propulsion=False, results=False)
    ps = part_meshes(acft.doc, ROOT)
    assert sorted(ps.parts) == ["arm_1", "arm_2", "arm_3", "arm_4", "body", "motor_1", "motor_2", "motor_3", "motor_4",
                                "rotor_1", "rotor_2", "rotor_3", "rotor_4"]
    assert all(ps.parts[f"rotor_{n}"].alpha == 0.3 and ps.parts[f"rotor_{n}"].instance == f"prop_lift_{n}" for n in (1, 2, 3, 4))
    assert ps.parts["body"].instance == "airframe" and ps.parts["body"].alpha is None


def test_gltf_writes_a_blend_material_for_a_part_with_alpha():
    tri = box([0, 0, 0], [1, 1, 1])
    data = gltf.write_glb([("rotor_1", tri, {"item": "x", "alpha": 0.4}), ("body", tri, {"item": "y"})], aircraft="t")
    assert data == gltf.write_glb([("body", tri, {"item": "y"}), ("rotor_1", tri, {"item": "x", "alpha": 0.4})], aircraft="t")
    jl = int.from_bytes(data[12:16], "little")
    doc = json.loads(data[20:20 + jl])
    assert len(doc["materials"]) == 1 and doc["materials"][0]["alphaMode"] == "BLEND"
    assert doc["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"][3] == 0.4
    assert [("material" in m["primitives"][0]) for m in doc["meshes"]] == [False, True]      # body, rotor_1 (sorted by name)
    _, parts = gltf.read_glb(data)
    assert parts["rotor_1"][1]["alpha"] == 0.4 and parts["rotor_1"][0].shape == (12, 3, 3)
    with pytest.raises(gltf.GltfError):
        gltf.write_glb([("p", tri, {"alpha": 1.5})], aircraft="t")


# ------------------------------------------------------------------------------------ consumers and datum, by kind
def test_a_complete_quad_has_everything_aerolink_needs(tmp_path):
    acft, _ = make_quad(tmp_path)
    assert consumers.vehicle_kind(acft.doc) == "multirotor"
    assert consumers.missing_for_flight(acft.doc) == []
    adh_doc.validate_document(acft.doc)


def test_the_consumer_check_lists_what_a_quad_lacks(tmp_path):
    acft, _ = make_quad(tmp_path, sheet=False, propulsion=False, results=False)
    miss = " | ".join(consumers.missing_for_flight(acft.doc))
    for word in ("mass_properties", "propulsion_system", "dataset aero", "dataset propulsion", "no ESC end points"):
        assert word in miss
    assert "control_surface" not in miss and "four control surfaces" not in miss         # a multirotor has no surfaces


def test_the_consumer_check_follows_the_vehicle_kind(tmp_path):
    from test_specsheet import make_full_doc

    fixed = make_full_doc()
    assert consumers.vehicle_kind(fixed) == "fixed_wing"
    assert any("propeller node muas.propeller" in m for m in consumers.missing_for_flight(fixed))
    assert set(consumers.FLIGHT_ITEMS_BY_KIND) == {"fixed_wing", "multirotor"} and "control_surface" not in consumers.FLIGHT_ITEMS_MULTIROTOR


@pytest.mark.parametrize("edit, word", [
    (lambda d: adh_doc.find(d, "prop_lift_2")["muas"]["propeller"].update(motor=1), "motor 1 is used by two"),
    (lambda d: adh_doc.find(d, "prop_lift_2")["muas"]["propeller"].update(system="other"), "is not a muas.propulsion_system"),
    (lambda d: adh_doc.find(d, "prop_lift_2")["muas"]["propeller"].update(thrust_axis=[1.0, 0.0, 0.0]), "must be [0, 0, 1]"),
    (lambda d: adh_doc.node(d, "1.2.5.10")["muas"]["autopilot"]["outputs"][0].pop("pwm_max_us"), "no ESC end points"),
    (lambda d: adh_doc.node(d, "1.2.5.10")["muas"]["autopilot"]["outputs"][0].update(targets=["prop_lift_3"]), "the rotor with motor 1"),
    (lambda d: adh_doc.node(d, "1.2.5.10")["muas"]["autopilot"]["outputs"].pop(), "no output motor4"),
    (lambda d: adh_doc.node(d, "1.2.2")["muas"].update(ground_contacts=adh_doc.node(d, "1.2.2")["muas"]["ground_contacts"][:2]), "at least 3"),
    (lambda d: adh_doc.find(d, "prop_lift_1")["muas"].update(control_surface={"x": 1}), "no control surfaces"),
])
def test_the_multirotor_check_names_each_fault(tmp_path, edit, word):
    acft, _ = make_quad(tmp_path)
    doc = copy.deepcopy(acft.doc)
    edit(doc)
    assert any(word in m for m in consumers.multirotor_problems(doc)), consumers.multirotor_problems(doc)


def test_the_mrp_must_be_within_one_millimetre_of_the_cg(tmp_path):
    acft, _ = make_quad(tmp_path)
    doc = copy.deepcopy(acft.doc)
    mrp = adh_doc.node(doc, "1.2")["muas"]["reference"]["mrp"]["point"]["xyz"]
    mrp[2] += 0.002
    assert any("muas.reference mrp" in m and "SpecSheet" in m for m in consumers.missing_for_flight(doc))
    rep = datum_checks(doc, ROOT)
    assert not rep.ok and any(c.name.startswith("MRP against the mass CG") and c.status == "fail" for c in rep.checks)


def test_the_datum_rows_of_a_quad(tmp_path):
    acft, _ = make_quad(tmp_path)
    rep = datum_checks(acft.doc, ROOT)
    assert rep.ok
    rows = {c.name: c for c in rep.checks}
    assert rows["hub symmetry: mirror y (largest gap to a hub)"].value == pytest.approx(0.0, abs=1e-12)
    # hubs 1.0 m apart in y, 1.7320508 m in x, disc diameter 0.4 m: the smallest gap is 1.0 - 0.4
    assert rows["rotor tip clearance, smallest gap between two discs"].value == pytest.approx(0.6)
    assert rows["rotor tip clearance, smallest gap between two discs"].status == "pass"
    assert not any("wing" in n or "propeller diameter" in n or "S_ref" in n for n in rows)      # fixed-wing rows are left out


def test_the_datum_check_fails_for_asymmetric_hubs_and_overlapping_discs(tmp_path):
    acft, _ = make_quad(tmp_path)
    doc = copy.deepcopy(acft.doc)
    adh_doc.find(doc, "prop_lift_4")["muas"]["propeller"]["hub"]["xyz"][0] += 0.01
    rep = datum_checks(doc, ROOT)
    assert any(c.name.startswith("hub symmetry") and c.status == "fail" for c in rep.checks)
    doc = copy.deepcopy(acft.doc)
    for n in (1, 2, 3, 4):
        adh_doc.find(doc, f"prop_lift_{n}")["muas"]["propeller"]["diameter"]["value"] = 1.2
    rep = datum_checks(doc, ROOT)
    row = next(c for c in rep.checks if c.name.startswith("rotor tip clearance, smallest"))
    assert row.status == "fail" and row.value < 0


# ----------------------------------------------------------------------------------- the whole synthetic build
def test_the_synthetic_quad_passes_every_check_and_packs_for_aerolink(tmp_path):
    from aeroplan.package import open_package, pack

    acft, _ = make_quad(tmp_path)
    acft.info["consumers"] = ["aerolink", "review", "archive"]
    acft.doc["muas"]["build"] = {"aeroplan_commit": "test", "aeroplan_dirty": False, "built": "2026-01-01", "author": "Test Person",
                                 "version": "0.1.0", "spokes": {}, "placeholder_items": []}
    rep = checks.run(acft, ROOT)
    assert rep.passed, rep.text()
    assert "aero.quad: checkData, 6 static shots, 18 outputs within tol" in "\n".join(l.split("  ", 1)[-1] for l in rep.lines)
    out = pack(acft, "aerolink", ROOT, tmp_path / "dist")
    pkg = open_package(out)
    assert pkg.manifest["profile"] == "aerolink" and any(f["path"] == "preview/aircraft.glb" for f in pkg.manifest["files"])
    _, parts = gltf.read_glb(pkg.read("preview/aircraft.glb") if hasattr(pkg, "read") else __import__("zipfile").ZipFile(out).read("preview/aircraft.glb"))
    assert "rotor_1" in parts and parts["rotor_1"][1]["item"] == "prop_lift_1"


def test_the_sizing_record_holds_the_emst_outputs_and_the_placeholder_inputs(tmp_path):
    acft, _ = make_quad(tmp_path)
    perf = adh_doc.node(acft.doc, "1.2")["performance"][0]
    assert perf["name"] == "sizing"
    ex = perf["tools"][0]["data_exchange"]
    outs = {o["name"]: o for o in ex["outputs"]}
    assert {"hover_rpm", "climb_p_battery_W", "forward_5_m_s_tilt_deg", "thrust_to_weight", "best_range_speed_m_s"} <= set(outs)
    assert outs["hover_tilt_deg"]["value"] == 0.0 and outs["hover_endurance_min"]["units"] == "min"
    assert {i["name"]: i["placeholder"] for i in ex["inputs"]}["rb"] is True


def test_the_aero_dataset_constants_carry_their_source_and_placeholder_flag(tmp_path):
    acft, _ = make_quad(tmp_path)
    air = adh_doc.node(acft.doc, "1.2")["muas"]
    d = acft.datasets[assets.item_dataset(adh_doc.node(acft.doc, "1.2"), "aero")["ref"]]
    cd = next(v for v in d["variable_def"] if v["var_id"] == "CDx")
    assert float(cd["initial_value"]) == pytest.approx(1.4) and "placeholder: true" in cd["description"]["value"] and "combine max" in cd["description"]["value"]
    e = next(e for e in assets.register(acft.doc, create=False) if e.get("dataset_role") == "aero")
    assert e["dataset"]["placeholder"] is True and e["dataset"]["analysis_mass_model"]["mass"]["value"] == pytest.approx(2.3)
    assert air["reference"]["s_ref"]["value"] == pytest.approx(0.02)


def test_stale_results_for_another_reference_area_are_refused(tmp_path):
    acft, ctx = make_quad(tmp_path)
    f = tmp_path / "work" / "aerosandbox" / "quad" / "asb" / "multirotor_results.json"
    res = json.loads(f.read_text(encoding="utf-8"))
    res["inputs"]["s_ref_m2"] = 0.5
    f.write_text(json.dumps(res), encoding="utf-8")
    with pytest.raises(ValueError, match="generate AeroSandbox quad"):
        load("AeroSandbox").ingest(acft.doc, ctx("AeroSandbox"))


def test_without_results_the_seed_says_what_to_run(tmp_path):
    acft = source_tree.new("quad")
    write_settings(tmp_path, "AeroSandbox", "quad", ASB_SETTINGS)
    out = load("AeroSandbox").ingest(acft.doc, Context("quad", tmp_path, "AeroSandbox", acft))
    assert any("aeroplan generate AeroSandbox quad" in c for c in out)


# ------------------------------------------------------------------------------------------------ worker needed
@needs_asb
def test_the_multirotor_drag_job_gives_finite_coefficients_near_the_hand_check(tmp_path):
    acft, ctx = make_quad(tmp_path, propulsion=False, results=False)
    spec = asb_spec.multirotor_spec(acft.doc, ASB_SETTINGS, ctx("AeroSandbox"))
    d = runner.run({"job": "multirotor_drag", "spec": spec})["multirotor_drag"]
    assert all(math.isfinite(v) and v > 0 for v in d["CD"].values())
    assert d["CdA_m2"]["x"] == pytest.approx(max(d["CdA_asb_m2"]["x"], d["hoerner_CdA_m2"]["x"]))        # combine: max
    # flow along z of a flat box: Hoerner 1.05 on the top face plus the tubes; AeroBuildup is within a factor 2 of the hand check
    assert 0.5 < d["asb_over_hoerner"]["z"] < 2.0
    assert max(d["asymmetry"].values()) < 0.05
    assert d["hoerner_CdA_m2"]["z"] >= 1.05 * 0.2 * 0.2


@needs_asb
def test_the_emst_jobs_in_the_worker_python_equal_the_numpy_functions(tmp_path):
    acft, ctx = make_quad(tmp_path)
    spec = asb_spec.multirotor_spec(acft.doc, ASB_SETTINGS, ctx("AeroSandbox"), drag={"CDx": 1.4, "CDy": 2.3, "CDz": 2.7})
    r = runner.run({"job": "emst_segments", "spec": spec, "rho_kg_m3": 1.225})["emst_segments"]
    m = worker.emst_model(spec, 1.225)
    assert r["segments"][0]["p_battery_W"] == pytest.approx(worker.emst_hover(m)["p_battery_W"], rel=1e-9)
    assert [s["name"] for s in r["segments"]] == ["hover", "climb", "forward", "forward"]
    assert runner.run({"job": "emst_endurance", "spec": spec, "rho_kg_m3": 1.225})["emst_endurance"]["rows"]
    assert runner.run({"job": "emst_sensitivity", "spec": spec, "rho_kg_m3": 1.225})["emst_sensitivity"]["parameters"]["mass_kg"]
