import pytest
from pydantic import ValidationError

from aeroplan.muas.mission import Mission, mission_requirement
from aeroplan.muas.node import validate_node


def _m(**kw):
    d = dict(name="circuit_x", params={"WP_RADIUS": 35}, items=[
        {"type": "takeoff", "pitch_deg": 12, "alt_agl_m": 50},
        {"type": "waypoint", "label": "a", "ahead_m": 300, "right_m": 0, "alt_agl_m": 80},
        {"type": "waypoint", "ahead_m": 0, "right_m": 250, "alt_agl_m": 80},
        {"type": "jump", "to": "a", "repeat": 1},
        {"type": "land", "ahead_m": -60, "right_m": 0}])
    d.update(kw)
    return Mission(**d)


def test_mission_ok_and_is_an_adh_requirement():
    req = mission_requirement(_m())
    assert req["category"] == "mission" and req["muas"]["mission"]["items"][-1]["type"] == "land"
    node = {"wbs_no": "1.2", "name": "AirVehicle", "requirements": [req],
            "muas": {"ext_version": "0.1.0", "instance": "x"}}
    validate_node(node)


def test_mission_must_end_with_land():
    with pytest.raises(ValidationError, match="ends with land"):
        _m(items=[{"type": "takeoff", "pitch_deg": 12, "alt_agl_m": 50},
                  {"type": "waypoint", "ahead_m": 1, "right_m": 0, "alt_agl_m": 50}])


def test_jump_needs_an_earlier_label():
    with pytest.raises(ValidationError, match="jump target"):
        _m(items=[{"type": "takeoff", "pitch_deg": 12, "alt_agl_m": 50},
                  {"type": "jump", "to": "nowhere", "repeat": 1},
                  {"type": "land", "ahead_m": 0, "right_m": 0}])


def test_unknown_item_type_rejected():
    with pytest.raises(ValidationError):
        _m(items=[{"type": "takeoff", "pitch_deg": 12, "alt_agl_m": 50}, {"type": "rtl"},
                  {"type": "land", "ahead_m": 0, "right_m": 0}])
