"""The FRD design frame (ADR 0025): the flip between x aft, z up and FRD. Synthetic numbers only."""
import numpy as np
import pytest

from aeroplan import frame
from aeroplan.visual import to_design


def _doc():
    return {
        "name": "t", "wbs_no": "1.2",
        "muas": {
            "ext_version": "0.4.0",
            "reference": {"design_frame": "x_aft_y_right_z_up_m_flow5Origin",
                          "nominal_cg": {"frame": "design", "xyz": [0.5, 0.1, -0.2], "units": "m"}},
            "mass_properties": {"inertia": {"axes": "parallel_to_design", "ixx": 1.0, "ixy": 0.3, "ixz": 0.2, "iyz": -0.4}},
            "propeller": {"thrust_axis": [-1, 0, 0], "hub": {"frame": "design", "xyz": [-0.6, 0, 0.0], "units": "m"}},
            "skin": {"transform": {"axes": ["-z", "-x", "y"], "origin_m": [0.1, 0.0, 0.3]},
                     "body_fit": {"cut": {"x_m": [-0.13, 0.45], "y_max_m": 0.12}}},
            "visual": {"hinge": [[0.1, -0.5, 0.0], [0.1, 0.5, 0.0]]},
        },
        "geometry": {
            "body": {"reference_axis": {"points": [{"x": 0.0, "y": 0.0, "z": 0.1}, {"x": 1.0, "y": 0.0, "z": 0.2}]}},
            "lifting_surface": {"airfoil_sections": [{"spline": {"points": [{"x": 0.5, "y": 0.0, "z": 0.05}]}}]},
        },
    }


def test_point_vector_inertia():
    assert frame.flip_point([1.0, 2.0, 3.0]) == [-1.0, 2.0, -3.0]
    assert frame.flip_point([0.0, 2.0, 0.0]) == [0.0, 2.0, 0.0]
    assert str(frame.flip_point([0.0, 0.0, 0.0])[0]) == "0.0"
    assert frame.flip_inertia(0.3, 0.2, -0.4) == (-0.3, 0.2, 0.4)
    assert frame.flip_axes(["-z", "-x", "y"]) == ["z", "-x", "-y"]
    assert frame.flip_axes(["z", "x", "-y"]) == ["-z", "x", "y"]


def test_flip_doc_values_and_involution():
    d = _doc()
    f = frame.flip_doc(d)
    m = f["muas"]
    assert m["reference"]["nominal_cg"]["xyz"] == [-0.5, 0.1, 0.2]
    assert m["propeller"]["thrust_axis"] == [1, 0, 0]
    assert m["propeller"]["hub"]["xyz"] == [0.6, 0, 0.0]
    assert m["mass_properties"]["inertia"] == {"axes": "parallel_to_design", "ixx": 1.0, "ixy": -0.3, "ixz": 0.2, "iyz": 0.4}
    assert m["skin"]["body_fit"]["cut"]["x_m"] == [-0.45, 0.13]
    assert m["visual"]["hinge"] == [[-0.1, -0.5, 0.0], [-0.1, 0.5, 0.0]]
    assert f["geometry"]["body"]["reference_axis"]["points"] == [{"x": 0.0, "y": 0.0, "z": -0.1}, {"x": -1.0, "y": 0.0, "z": -0.2}]
    # the unit-chord foil sections are not a design-frame value
    assert f["geometry"]["lifting_surface"] == d["geometry"]["lifting_surface"]
    # the input is not changed, and two flips give the input
    assert d == _doc()
    assert frame.flip_doc(f) == d


def test_transform_flip_gives_the_flipped_design_point():
    cad = np.array([[[0.2, 0.5, 0.7], [-0.1, 0.3, 0.4], [0.0, 0.0, 0.1]]])
    t = {"axes": ["-z", "-x", "y"], "origin_m": [0.1, 0.0, 0.3]}
    old = to_design(cad, "m", t)
    new = to_design(cad, "m", frame.flip_doc({"transform": t})["transform"])
    assert np.allclose(new, frame.flip_array(old))


def test_planform_le_x():
    # old frame: position 0.1, x_offset 0.05 aft -> LE at 0.15. FRD: position -0.1 -> LE at -0.15
    assert frame.planform_le_x(-0.1, 0.05) == pytest.approx(-0.15)


def test_migrate_doc_sets_frame_and_refuses_twice():
    out = frame.migrate_doc(_doc())
    assert out["muas"]["reference"]["design_frame"] == "x_fwd_y_right_z_down_m_wingLE"
    assert out["muas"]["ext_version"] == frame.MUAS_SCHEMA_VERSION
    with pytest.raises(ValueError, match="FRD already"):
        frame.migrate_doc(out)
    with pytest.raises(ValueError, match="no design_frame"):
        frame.migrate_doc({"name": "f16", "muas": {}})
