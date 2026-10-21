"""The CREO spoke: the tube bodies of the settings (the tail boom) -> ADH subcomponents. Every number is synthetic."""
import numpy as np
import pytest

from aeroplan import adh_doc
from aeroplan.frame import planform_le_x
from aeroplan.geometry import body_frames, planform_wing
from aeroplan.spokes import load
from aeroplan.visual import PIVOT
from test_openvsp import make_doc

creo = load("CREO")
BOOM = {"tail_boom": {"node": "1.2.2.4", "name": "Tail boom", "radius_m": 0.02, "from_instance": "fuselage",
                      "to_instance": "htail", "source": "test value", "placeholder": True}}


def test_the_tube_runs_from_the_aft_end_of_the_body_to_the_tail_quarter_chord():
    doc = make_doc()
    assert creo.write_tubes(doc, BOOM)
    boom = adh_doc.find(doc, "tail_boom")
    assert boom in adh_doc.node(doc, "1.2.2.4")["subcomponents"] and "wbs_no" not in boom
    frames = body_frames(boom["geometry"]["body"])
    aft = body_frames(adh_doc.find(doc, "fuselage")["geometry"]["body"])[-1]
    wing = planform_wing(adh_doc.find(doc, "htail")["muas"]["planform"])
    s0 = wing.sections[0]
    assert frames[0][0, 0] == pytest.approx(aft[0, 0])
    assert frames[-1][0, 0] == pytest.approx(planform_le_x(wing.position[0], s0.x_offset) - PIVOT * s0.chord)
    assert frames[-1][0, 2] == pytest.approx(wing.position[2])
    # closed ends, the full radius between them, the same point count in every frame (a loft needs it)
    assert np.ptp(frames[0], axis=0).max() == 0.0 and np.ptp(frames[-1], axis=0).max() == 0.0
    for f in frames[1:-1]:
        assert np.abs(f[:, 1]).max() == pytest.approx(0.02) and np.ptp(f[:, 2]) == pytest.approx(0.04)
    assert len({len(f) for f in frames}) == 1
    tube = boom["muas"]["tube"]
    assert tube["placeholder"] is True and tube["radius"] == {"value": 0.02, "units": "m"}
    adh_doc.normalize(doc)
    adh_doc.validate_document(doc)


def test_a_second_run_with_the_same_settings_changes_nothing():
    doc = make_doc()
    creo.write_tubes(doc, BOOM)
    assert creo.write_tubes(doc, BOOM) == []
    assert len([s for s in adh_doc.node(doc, "1.2.2.4")["subcomponents"] if s["muas"]["instance"] == "tail_boom"]) == 1


def test_a_tube_needs_a_body_at_its_start():
    with pytest.raises(ValueError, match="no ADH body"):
        creo.write_tubes(make_doc(), {"b": dict(BOOM["tail_boom"], from_instance="htail")})


def test_a_tube_with_explicit_ends_and_a_bore_is_written_as_given():
    """The tail boom of the settings: two points (FRD, forward end first), an outer and an inner radius."""
    spec = {"name": "Tail boom", "node": "1.2.2.4", "radius_m": 0.0127, "inner_radius_m": 0.0117,
            "p0_m": [-0.2, 0.0, 0.02], "p1_m": [-1.5, 0.0, 0.02], "source": "test value"}
    doc = make_doc()
    assert creo.write_tubes(doc, {"tail_boom": spec})
    boom = adh_doc.find(doc, "tail_boom")
    tube = boom["muas"]["tube"]
    assert tube["p0"] == [-0.2, 0.0, 0.02] and tube["p1"] == [-1.5, 0.0, 0.02]
    assert tube["radius"]["value"] == 0.0127 and tube["inner_radius"]["value"] == 0.0117
    assert "from_instance" not in tube and tube["placeholder"] is False
    frames = body_frames(boom["geometry"]["body"])
    assert frames[0][0, 0] == pytest.approx(-0.2) and frames[-1][0, 0] == pytest.approx(-1.5)
    assert creo.write_tubes(doc, {"tail_boom": spec}) == []                 # a second run changes nothing
    adh_doc.normalize(doc)
    adh_doc.validate_document(doc)
    with pytest.raises(ValueError, match="aft of the start"):
        creo.write_tubes(make_doc(), {"b": dict(spec, p0_m=[-1.5, 0.0, 0.02], p1_m=[-0.2, 0.0, 0.02])})
