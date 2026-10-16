"""The Prototype spoke: published specs -> sizing targets, and the propulsion sizing from the MTOW. Synthetic data."""
import json
import math

import pytest
import yaml

from aeroplan import adh_doc, propulsion_sizing, source_tree
from aeroplan.spokes import Context, load
from test_openvsp import make_doc

spoke = load("Prototype")

SIZING = {"confirmed": False, "n_lift": 4, "hover_tw": 2.0, "disc_loading_n_m2": 150.0, "figure_of_merit": 0.65,
          "eta_lift_chain": 0.8, "cruise_speed_m_s": 22.0, "lift_to_drag": 10.0, "eta_prop_cruise": 0.7,
          "eta_cruise_chain": 0.82, "hover_time_s": 120.0, "cruise_time_s": 2400.0, "reserve_fraction": 0.25,
          "depth_of_discharge": 0.8, "battery_wh_per_kg": 180.0}
SETTINGS = {"base_url": "https://example.test/api/v1", "project": "p",
            "specs": {"mtow": {"key": "mtow", "bound": "max", "units": "kg"}}, "mtow_spec": "mtow",
            "propulsion_sizing": SIZING}


def answer(value=12.0, units="kg", status="published"):
    latest = {"version": 3, "status": status, "value": value, "publishedAt": "2026-10-16T01:00:00Z"}
    return {"ok": True, "data": [{"slug": "mtow", "name": "Maximum take-off mass", "kind": "mass", "units": units,
                                  "valueType": "number", "latest": latest},
                                 {"slug": "other", "name": "No version yet", "kind": "x", "units": "m",
                                  "valueType": "number", "latest": None}]}


def ctx(tmp_path, settings=None, body=None):
    doc = make_doc()
    c = Context("t", tmp_path, "Prototype", source_tree.Aircraft("t", doc))
    c.settings_file.parent.mkdir(parents=True)
    c.settings_file.write_text(yaml.safe_dump(SETTINGS if settings is None else settings))
    if body is not False:
        c.work.mkdir(parents=True)
        (c.work / "specs.json").write_text(json.dumps(answer() if body is None else body))
    return c


def targets(item):
    return {r["muas"]["target"]["key"]: r["muas"]["target"] for r in item.get("requirements") or []}


# ------------------------------------------------------------------------------------------------ the method
def test_sizing_matches_a_hand_calculation():
    i = propulsion_sizing.inputs_from(SIZING, 12.0)
    r = propulsion_sizing.size(i)
    w = 12.0 * propulsion_sizing.G
    area = w / 150.0 / 4
    assert r["lift_motor_thrust_hover_n"] == pytest.approx(w / 4)
    assert r["lift_rotor_diameter_m"] == pytest.approx(2 * math.sqrt(area / math.pi))
    p_hover = (w / 4) ** 1.5 / math.sqrt(2 * 1.225 * area) / 0.65 / 0.8
    assert r["lift_motor_power_hover_w"] == pytest.approx(p_hover)
    assert r["lift_motor_power_peak_w"] == pytest.approx(p_hover * 2 ** 1.5)
    assert r["cruise_thrust_n"] == pytest.approx(w / 10)
    assert r["cruise_power_w"] == pytest.approx(w / 10 * 22 / (0.7 * 0.82))
    e = (p_hover * 4 * 120 + r["cruise_power_w"] * 2400) / 3600
    assert r["battery_energy_wh"] == pytest.approx(e * 1.25 / 0.8)
    assert r["battery_mass_fraction"] == pytest.approx(r["battery_mass_kg"] / 12.0)


def test_sizing_grows_with_mtow():
    lo = propulsion_sizing.size(propulsion_sizing.inputs_from(SIZING, 10.0))
    hi = propulsion_sizing.size(propulsion_sizing.inputs_from(SIZING, 14.0))
    assert all(hi[k] > lo[k] for k in ("lift_motor_thrust_peak_n", "lift_motor_power_peak_w", "cruise_power_w",
                                      "battery_energy_wh"))


@pytest.mark.parametrize("change", [{"n_lift": 0}, {"hover_tw": 0.9}, {"figure_of_merit": 1.2}, {"disc_loading_n_m2": 0}])
def test_sizing_refuses_bad_inputs(change):
    with pytest.raises(ValueError):
        propulsion_sizing.size(propulsion_sizing.inputs_from({**SIZING, **change}, 12.0))


def test_sizing_settings_have_no_hidden_default():
    with pytest.raises(ValueError, match="miss: hover_tw"):
        propulsion_sizing.inputs_from({k: v for k, v in SIZING.items() if k != "hover_tw"}, 12.0)
    with pytest.raises(ValueError, match="unknown keys: typo"):
        propulsion_sizing.inputs_from({**SIZING, "typo": 1}, 12.0)


# ------------------------------------------------------------------------------------------------ the spoke
def test_no_input_file_skips(tmp_path):
    c = ctx(tmp_path, body=False)
    assert spoke.ingest(c.acft.doc, c) is None


def test_ingest_writes_spec_and_propulsion_targets(tmp_path):
    c = ctx(tmp_path)
    lines = spoke.ingest(c.acft.doc, c)
    assert "propulsion sizing from MTOW 12 kg (placeholder" in lines[1]
    air = targets(adh_doc.node(c.acft.doc, "1.2"))
    assert air["mtow"]["value"] == 12.0 and air["mtow"]["bound"] == "max"
    assert air["mtow"]["source"].startswith("Prototype spec mtow version 3")
    prop = targets(adh_doc.node(c.acft.doc, "1.2.3"))
    assert set(prop) == {"lift_motor_thrust_peak", "lift_rotor_diameter", "lift_motor_power_peak", "hover_power_total",
                         "cruise_thrust", "cruise_power", "battery_energy", "battery_mass"}
    assert all(t["placeholder"] for t in prop.values())
    assert prop["battery_energy"]["units"] == "W*h"
    assert any(s["tool"] == "Prototype" for s in adh_doc.node(c.acft.doc, "1.2")["muas"]["sources"])
    adh_doc.normalize(c.acft.doc)
    adh_doc.validate_document(c.acft.doc)


def test_confirmed_assumptions_clear_the_placeholder_flag(tmp_path):
    s = {**SETTINGS, "propulsion_sizing": {**SIZING, "confirmed": True}}
    c = ctx(tmp_path, settings=s)
    spoke.ingest(c.acft.doc, c)
    assert not any(t["placeholder"] for t in targets(adh_doc.node(c.acft.doc, "1.2.3")).values())


def test_mtow_in_grams_is_converted(tmp_path):
    c = ctx(tmp_path, body=answer(value=12000, units="g"))
    spoke.ingest(c.acft.doc, c)
    assert targets(adh_doc.node(c.acft.doc, "1.2"))["mtow"]["value"] == pytest.approx(12.0)


def test_new_mtow_replaces_the_old_targets_and_keeps_foreign_requirements(tmp_path):
    c = ctx(tmp_path)
    air = adh_doc.node(c.acft.doc, "1.2")
    air["requirements"] = [{"name": "mine", "description": "d", "category": "sizing", "priority": "medium",
                            "verification_method": "analysis", "status": "draft", "acceptance_criteria": "x",
                            "muas": {"target": {"key": "mine", "value": 1.0, "bound": "min", "units": "nd",
                                                "source": "a person"}}}]
    spoke.ingest(c.acft.doc, c)
    first = targets(adh_doc.node(c.acft.doc, "1.2.3"))["battery_energy"]["value"]
    (c.work / "specs.json").write_text(json.dumps(answer(value=15.0)))
    spoke.ingest(c.acft.doc, c)
    prop_reqs = adh_doc.node(c.acft.doc, "1.2.3")["requirements"]
    assert len(prop_reqs) == 8
    assert targets(adh_doc.node(c.acft.doc, "1.2.3"))["battery_energy"]["value"] > first
    air_t = targets(adh_doc.node(c.acft.doc, "1.2"))
    assert air_t["mtow"]["value"] == 15.0 and "mine" in air_t and len(adh_doc.node(c.acft.doc, "1.2")["requirements"]) == 2


def test_unpublished_spec_is_refused(tmp_path):
    body = answer()
    body["data"][0]["latest"] = None
    c = ctx(tmp_path, body=body)
    with pytest.raises(ValueError, match="not published in Prototype: mtow"):
        spoke.ingest(c.acft.doc, c)


def test_unit_that_cannot_convert_is_refused(tmp_path):
    c = ctx(tmp_path, body=answer(units="m"))
    with pytest.raises(ValueError, match="cannot convert"):
        spoke.ingest(c.acft.doc, c)


def test_text_value_is_refused(tmp_path):
    c = ctx(tmp_path, body=answer(value="12 kg"))
    with pytest.raises(ValueError, match="not a number"):
        spoke.ingest(c.acft.doc, c)


def test_mtow_spec_must_be_mapped(tmp_path):
    c = ctx(tmp_path, settings={**SETTINGS, "mtow_spec": "nope"})
    with pytest.raises(ValueError, match="mtow_spec 'nope' is not in specs"):
        spoke.ingest(c.acft.doc, c)


def test_without_propulsion_settings_only_the_spec_targets_are_written(tmp_path):
    c = ctx(tmp_path, settings={k: v for k, v in SETTINGS.items() if k != "propulsion_sizing"})
    assert len(spoke.ingest(c.acft.doc, c)) == 1
    assert not adh_doc.has_node(c.acft.doc, "1.2.3") or "requirements" not in adh_doc.node(c.acft.doc, "1.2.3")


def test_download_needs_a_token_and_https(tmp_path, monkeypatch):
    c = ctx(tmp_path)
    monkeypatch.delenv("PROTOTYPE_TOKEN", raising=False)
    with pytest.raises(ValueError, match="PROTOTYPE_TOKEN"):
        spoke.generate(c.acft.doc, c)
    monkeypatch.setenv("PROTOTYPE_TOKEN", "ptk_live_test")
    c.settings_file.write_text(yaml.safe_dump({**SETTINGS, "base_url": "http://example.test/api/v1"}))
    with pytest.raises(ValueError, match="https"):
        spoke.generate(c.acft.doc, c)


def test_download_works_for_an_aircraft_with_no_source_tree(monkeypatch):
    from aeroplan import build

    monkeypatch.delenv("PROTOTYPE_TOKEN", raising=False)
    with pytest.raises(ValueError, match="PROTOTYPE_TOKEN"):            # reaches the spoke, no source tree error
        build.generate("Prototype", "no_such_aircraft_for_test")
