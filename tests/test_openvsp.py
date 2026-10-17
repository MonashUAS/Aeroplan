"""The OpenVSP spoke: the ADH geometry -> OpenVSP -> the ADH geometry with no shape loss. Every number is synthetic.

The tests that run OpenVSP need the OpenVSP Python of this machine (`python -m aeroplan setup OpenVSP`). Without it
they skip (CI has no OpenVSP). The other tests run everywhere.
"""
import copy
import math
import shutil

import numpy as np
import pytest
import yaml

from aeroplan import adh_doc, assets, datum, source_tree
from aeroplan.geometry import (body_adh, body_frames, distance_to_mesh, foils_of, lifting_surface_adh, planform_wing,
                               section_points)
from aeroplan.parts import _hinge_point
from aeroplan.spokes import Context, load
from aeroplan.step_mesh import StepMeshError, read_step_faceted

vsp = load("OpenVSP")
runner = vsp.runner
needs_openvsp = pytest.mark.skipif(not runner.available(),
                                   reason="no OpenVSP Python here: run `python -m aeroplan setup OpenVSP`")
SHAPE = 1e-6       # m: the largest gap from the ADH shape to the OpenVSP surface in these synthetic cases
EXACT = 1e-9       # m and deg: the parameter round trip


def naca(m=0.02, p=0.4, t=0.10, n=61, te=0.0):
    """A 4-digit foil in Selig order, with the points (0, 0) and the trailing edge in it."""
    b = np.linspace(0.0, np.pi, n)
    x = (1 - np.cos(b)) / 2
    yt = 5 * t * (0.2969 * np.sqrt(x) - 0.126 * x - 0.3516 * x ** 2 + 0.2843 * x ** 3 - 0.1015 * x ** 4) + te * x
    yc = np.where(x < p, m / p ** 2 * (2 * p * x - x ** 2), m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * x - x ** 2))
    return np.vstack([np.column_stack([x, yc + yt])[::-1], np.column_stack([x, yc - yt])[1:]])


FOILS = {"root": naca(), "tip": naca(m=0.0, t=0.09, n=41, te=0.002)}


def planform(name, kind, xyz, sections, rx=0.0, ry=0.0, two_sided=True):
    return {"surface_name": name, "kind": kind, "position": {"frame": "design", "xyz": xyz, "units": "m"},
            "rx_deg": rx, "ry_deg": ry, "symmetric": True, "two_sided": two_sided, "sections": sections,
            "source": "synthetic", "placeholder": False}


WING = planform("Main Wing", "MAINWING", [0.1, 0.0, 0.02], [
    {"y": 0.0, "chord": 0.40, "x_offset": 0.0, "dihedral_deg": 3.0, "twist_deg": 2.0, "foil": "root"},
    {"y": 0.8, "chord": 0.32, "x_offset": 0.03, "dihedral_deg": 6.0, "twist_deg": 0.5, "foil": "root"},
    {"y": 1.4, "chord": 0.20, "x_offset": 0.09, "dihedral_deg": 6.0, "twist_deg": -1.0, "foil": "tip"}], ry=1.5)
HTAIL = planform("Elevator", "ELEVATOR", [1.3, 0.0, 0.05], [
    {"y": 0.0, "chord": 0.22, "x_offset": 0.0, "dihedral_deg": 0.0, "twist_deg": 0.0, "foil": "tip"},
    {"y": 0.35, "chord": 0.17, "x_offset": 0.04, "dihedral_deg": 0.0, "twist_deg": 0.0, "foil": "tip"}], ry=-2.0)
FIN = planform("Fin", "FIN", [1.3, 0.0, 0.08], [
    {"y": 0.0, "chord": 0.25, "x_offset": 0.0, "dihedral_deg": 0.0, "twist_deg": 0.0, "foil": "tip"},
    {"y": 0.40, "chord": 0.18, "x_offset": 0.06, "dihedral_deg": 0.0, "twist_deg": 0.0, "foil": "tip"}],
    rx=-90.0, two_sided=False)


def frames():
    """A body of 9 frames: a point nose, 7 frames of 13 right-half points (top to bottom), a point tail."""
    out = [np.array([[-0.5, 0.0, 0.0]] * 13)]
    for x, r, zc in ((-0.45, 0.04, 0.0), (-0.3, 0.08, 0.005), (-0.1, 0.1, 0.01), (0.1, 0.1, 0.01), (0.3, 0.08, 0.0),
                     (0.5, 0.05, -0.01), (0.7, 0.03, -0.01)):
        a = np.linspace(0.0, np.pi, 13)
        out.append(np.column_stack([np.full(13, x), r * np.sin(a) * (1 + 0.1 * np.sin(2 * a)), zc + 1.2 * r * np.cos(a)]))
    out.append(np.array([[0.8, 0.0, -0.01]] * 13))
    return out


def surface_item(pf, instance, name):
    foils = {s["foil"]: FOILS[s["foil"]] for s in pf["sections"]}
    return {"name": name, "geometry": {"lifting_surface": lifting_surface_adh(planform_wing(pf), foils)},
            "muas": {"ext_version": adh_doc.MUAS_SCHEMA_VERSION, "instance": instance, "planform": copy.deepcopy(pf)}}


def control(instance, parent, eta, hinge, side):
    return {"name": instance, "muas": {"ext_version": adh_doc.MUAS_SCHEMA_VERSION, "instance": instance,
                                       "control_surface": {"parent": parent, "eta_span": eta, "hinge_x_over_c": hinge,
                                                           "limit_min_rad": -0.3, "limit_max_rad": 0.3,
                                                           "positive_sign": "JSBSim", "s119_name": "x", "side": side}}}


def make_doc():
    doc = adh_doc.new_document("T", "synthetic")
    adh_doc.muas(adh_doc.node(doc, "1.2", create=True), "t_airvehicle")
    wing = adh_doc.node(doc, "1.2.2.3", create=True)
    wing.update(surface_item(WING, "wing_main", "Wing"))
    ail = adh_doc.node(doc, "1.2.2.3.3", create=True)
    adh_doc.muas(ail, "ailerons")
    for inst, side in (("aileron_l", "left"), ("aileron_r", "right")):
        adh_doc.put_subcomponent(ail, control(inst, "wing_main", [0.55, 0.9], 0.75, side))
    stab = adh_doc.node(doc, "1.2.2.4.1", create=True)
    adh_doc.muas(stab, "stabilizer")
    ht = adh_doc.put_subcomponent(stab, surface_item(HTAIL, "htail", "Horizontal tail"))
    adh_doc.put_subcomponent(ht, control("elevator", "htail", [0.0, 1.0], 0.7, "both"))
    fin = adh_doc.put_subcomponent(stab, surface_item(FIN, "fin", "Fin"))
    adh_doc.put_subcomponent(fin, control("rudder", "fin", [0.1, 1.0], 0.65, "both"))
    fus = adh_doc.node(doc, "1.2.2.2", create=True)
    adh_doc.muas(fus, "fuselage")
    fus["geometry"] = {"body": body_adh(frames())}
    adh_doc.validate_document(doc)
    return doc


def context(tmp_path, doc=None):
    ctx = Context("t", tmp_path, "OpenVSP", source_tree.Aircraft("t", doc if doc is not None else make_doc()))
    ctx.settings_file.parent.mkdir(parents=True)
    ctx.settings_file.write_text(yaml.safe_dump({"vsp_version": "3.54.0", "model": "t.vsp3",
                                                 "wings": ["wing_main", "htail", "fin"], "body": "fuselage"}))
    return ctx


# --------------------------------------------------------------------------------------------- no OpenVSP needed
def test_eta_conversion_between_projected_and_panel_span():
    secs = WING["sections"]
    for eta in (0.0, 0.3, 0.55, 0.9, 1.0):
        assert vsp.eta_from_vsp(secs, vsp.eta_to_vsp(secs, eta)) == pytest.approx(eta, abs=1e-12)
    # 0.8 m of 1.4 m projected; the outer panel has more dihedral, so its share of the panel span is larger
    assert vsp.eta_to_vsp(secs, 0.8 / 1.4) < 0.8 / 1.4
    flat = [dict(s, dihedral_deg=4.0) for s in secs]
    assert vsp.eta_to_vsp(flat, 0.37) == pytest.approx(0.37, abs=1e-12)


def test_spec_groups_a_left_right_pair():
    spec = vsp.spec_from_doc(make_doc(), {"wings": ["wing_main", "htail", "fin"], "body": "fuselage"})
    w = {x["instance"]: x for x in spec["wings"]}
    assert [c["name"] for c in w["wing_main"]["controls"]] == ["aileron_l+aileron_r"]
    assert [c["name"] for c in w["htail"]["controls"]] == ["elevator"]
    assert w["fin"]["mirror"] is False and w["wing_main"]["mirror"] is True
    assert len(spec["body"]["frames"]) == 9


def two_body_doc():
    """The synthetic document with a second body: a round tube behind the fuselage, as a subcomponent of the empennage."""
    doc = make_doc()
    emp = adh_doc.node(doc, "1.2.2.4", create=True)
    adh_doc.muas(emp, "empennage")
    boom = [np.array([[0.8, 0.0, -0.01]] * 13)]
    for x in (0.85, 1.2, 1.55):
        a = np.linspace(0.0, np.pi, 13)
        boom.append(np.column_stack([np.full(13, x), 0.02 * np.sin(a), -0.01 + 0.02 * np.cos(a)]))
    boom.append(np.array([[1.6, 0.0, -0.01]] * 13))
    adh_doc.put_subcomponent(emp, {"name": "Tail boom", "geometry": {"body": body_adh(boom)},
                                   "muas": {"ext_version": adh_doc.MUAS_SCHEMA_VERSION, "instance": "tail_boom"}})
    adh_doc.validate_document(doc)
    return doc, boom


def test_spec_holds_a_list_of_bodies_and_the_old_key():
    doc, boom = two_body_doc()
    spec = vsp.spec_from_doc(doc, {"wings": ["wing_main"], "bodies": ["fuselage", "tail_boom"]})
    assert [b["instance"] for b in spec["bodies"]] == ["fuselage", "tail_boom"]
    assert len(spec["bodies"][1]["frames"]) == len(boom)
    assert spec["body"]["instance"] == "fuselage"
    old = vsp.spec_from_doc(doc, {"wings": ["wing_main"], "body": "fuselage"})
    assert [b["instance"] for b in old["bodies"]] == ["fuselage"]
    assert vsp.spec_from_doc(doc, {"wings": ["wing_main"]})["bodies"] == []


def test_distance_to_mesh():
    tri = np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]], float)
    d = distance_to_mesh(np.array([[0.2, 0.2, 1.0], [2.0, 0.0, 0.0], [-1.0, -1.0, 0.0]]), tri)
    assert d == pytest.approx([1.0, 1.0, math.sqrt(2.0)])


STEP = """ISO-10303-21;
HEADER;
FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));
ENDSEC;
DATA;
#1=CARTESIAN_POINT('',(0.,0.,0.));
#2=CARTESIAN_POINT('',(1.,0.,0.));
#3=CARTESIAN_POINT('',(0.,1.,0.));
#4=CARTESIAN_POINT('',(0.,0.,1.));
#10=POLY_LOOP('',(#1,#3,#2));
#11=POLY_LOOP('',(#1,#2,#4));
#12=POLY_LOOP('',(#1,#4,#3));
#13=POLY_LOOP('',(#2,#3,#4));
#20=FACE_OUTER_BOUND('',#10,.T.);
#21=FACE_OUTER_BOUND('',#11,.T.);
#22=FACE_OUTER_BOUND('',#12,.T.);
#23=FACE_OUTER_BOUND('',#13,.T.);
#30=PLANE('',#99);
#40=FACE_SURFACE('',(#20),#30,.T.);
#41=FACE_SURFACE('',(#21),#30,.T.);
#42=FACE_SURFACE('',(#22),#30,.T.);
#43=FACE_SURFACE('',(#23),#30,.F.);
#50=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));
#51=(CONVERSION_BASED_UNIT('INCH',#52)LENGTH_UNIT()NAMED_UNIT(#53));
ENDSEC;
END-ISO-10303-21;
"""


def test_step_reader_reads_a_faceted_tetrahedron_in_inches(tmp_path):
    p = tmp_path / "t.stp"
    p.write_text(STEP)
    tri, unit = read_step_faceted(p)
    assert unit == "INCH" and tri.shape == (4, 3, 3)
    assert tri.reshape(-1, 3).max() == pytest.approx(0.0254)
    assert tri[3].tolist() == (np.array([[0, 0, 1], [0, 1, 0], [1, 0, 0]]) * 0.0254).tolist()  # .F. turns the face
    p.write_text(STEP.replace("#30=PLANE('',#99);", "#30=CYLINDRICAL_SURFACE('',#99,1.);"))
    with pytest.raises(StepMeshError, match="not faceted"):
        read_step_faceted(p)


def test_flow5_keeps_the_geometry_of_another_tool():
    same = load("flow5")._same_files
    ref = {"tool": "flow5", "asset": "asset:sha256:" + "a" * 64, "role": "plane"}
    item = {"geometry": {"body": {}}, "muas": {"sources": [ref, dict(ref, tool="OpenVSP", asset="asset:sha256:" + "b" * 64)]}}
    assert same(item, [ref])                                   # the flow5 files are the recorded ones: keep
    assert not same(item, [dict(ref, asset="asset:sha256:" + "c" * 64)])   # a new sweep: flow5 writes
    assert not same({"muas": {"sources": [ref]}}, [ref])       # no geometry yet: flow5 writes


def test_datum_warns_when_the_geometry_is_newer_than_the_aero_model():
    doc = make_doc()
    air = adh_doc.node(doc, "1.2")
    aid = "asset:sha256:" + "a" * 64
    assets.register(doc).append({"id": aid, "kind": "dataset", "name": "aero.t", "role": "aero model", "tool": "flow5",
                                 "media_type": "application/json", "size": 2, "built_against": "t@0.1.0"})
    assets.set_item_dataset(air, "aero", aid)
    rep = datum.DatumReport()
    datum._geometry_age(rep, doc, air)
    assert rep.checks == []
    adh_doc.find(doc, "htail")["muas"]["geometry_tool"] = "OpenVSP"
    datum._geometry_age(rep, doc, air)
    assert [c.status for c in rep.checks] == ["warn"] and "t@0.1.0" in rep.checks[0].source and rep.ok


# ----------------------------------------------------------------------------------------------- OpenVSP needed
@needs_openvsp
def test_openvsp_version():
    assert runner.run({"job": "version"})["version"].startswith("OpenVSP 3.54")


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    if not runner.available():
        pytest.skip("no OpenVSP Python")
    doc = make_doc()
    spec = vsp.spec_from_doc(doc, {"wings": ["wing_main", "htail", "fin"], "body": "fuselage"})
    path = tmp_path_factory.mktemp("vsp") / "t.vsp3"
    runner.run({"job": "write", "spec": spec, "path": str(path)})
    return doc, spec, path


@needs_openvsp
def test_parameter_round_trip_is_exact(written):
    _, spec, path = written
    back = runner.run({"job": "read", "path": str(path)})["spec"]
    assert back["other"] == []
    by = {w["instance"]: w for w in back["wings"]}
    for w in spec["wings"]:
        b = by[w["instance"]]
        assert b["mirror"] == w["mirror"]
        for k in ("rx_deg", "ry_deg"):
            assert b[k] == pytest.approx(w[k], abs=EXACT)
        assert np.allclose(b["position"], w["position"], rtol=0, atol=EXACT)
        for i, (sa, sb) in enumerate(zip(w["sections"], b["sections"])):
            for k in ("y", "chord", "x_offset", "twist_deg") + (("dihedral_deg",) if i < len(w["sections"]) - 1 else ()):
                assert sb[k] == pytest.approx(sa[k], abs=EXACT), (w["instance"], i, k)
            fa, fb = np.array(w["foils"][sa["foil"]]), np.array(b["foils"][sb["foil"]])
            assert fa.shape == fb.shape and np.abs(fa - fb).max() <= 1e-15
        assert len(b["controls"]) == len(w["controls"])
        for ca, cb in zip(w["controls"], b["controls"]):
            assert cb["name"] == ca["name"]
            assert np.allclose(cb["eta"], ca["eta"], rtol=0, atol=1e-12)
            assert cb["hinge_x_over_c"] == pytest.approx(ca["hinge_x_over_c"], abs=1e-12)
    fa, fb = np.array(spec["body"]["frames"]), np.array(back["body"]["frames"])
    assert fa.shape == fb.shape and np.abs(fa - fb).max() <= EXACT


@needs_openvsp
def test_the_openvsp_surface_holds_the_adh_shape(written):
    doc, spec, path = written
    wings = {w["instance"]: (adh_doc.find(doc, w["instance"])["muas"]["planform"],
                             {k: np.asarray(v) for k, v in w["foils"].items()}) for w in spec["wings"]}
    gaps = vsp.shape_gaps(path, wings, ("fuselage", frames()))
    assert set(gaps) == {"wing_main", "htail", "fin", "fuselage"}
    assert max(gaps.values()) <= SHAPE, gaps
    # the ADH leading and trailing edge splines are on the surface too
    sets = []
    for inst in ("wing_main", "htail", "fin"):
        ls = adh_doc.find(doc, inst)["geometry"]["lifting_surface"]
        pts = [[p["x"], p["y"], p["z"]] for k in ("leading_edge_spline", "trailing_edge_spline") for p in ls[k]["points"]]
        sets.append({"geom": inst, "points": pts})
    d = runner.run({"job": "project", "path": str(path), "sets": sets})["distances"]
    assert max(max(v) for v in d) <= SHAPE


@needs_openvsp
def test_area_span_and_control_surface_stations_agree(written):
    doc, _, path = written
    vals = runner.run({"job": "get", "path": str(path), "get": [
        {"geom": "wing_main", "parm": "TotalArea", "group": "WingGeom"},
        {"geom": "wing_main", "parm": "TotalProjectedSpan", "group": "WingGeom"}]})["values"]
    secs = WING["sections"]
    true_area = 2 * sum((b["y"] - a["y"]) / math.cos(math.radians(a["dihedral_deg"])) * (a["chord"] + b["chord"]) / 2
                        for a, b in zip(secs, secs[1:]))
    assert vals[0] == pytest.approx(true_area, rel=1e-9)
    assert vals[1] == pytest.approx(2 * secs[-1]["y"], abs=EXACT)
    # each aileron end: OpenVSP eta -> u. The leading edge there lies at the ADH span station. The OpenVSP point at
    # 0.75 of the chord line (leading edge to trailing edge, w = 0.5 and 0) lies on the straight line between the
    # hinge points of the two sections next to it: OpenVSP joins the sections with straight lines. (The hinge rule of
    # aeroplan.parts interpolates the chord and the twist. Between the sections that gives a second-order difference:
    # 0.28 mm in this wing. At a section the two rules agree.)
    wing = planform_wing(WING)
    ys = [sec["y"] for sec in secs]
    for eta in (0.55, 0.9):
        u = runner.run({"job": "eta_to_u", "path": str(path), "geom": "wing_main",
                        "eta": [vsp.eta_to_vsp(secs, eta)]})["u"][0]
        le, te = runner.run({"job": "probe", "path": str(path), "geom": "wing_main", "u": [u, u],
                             "w": [0.5, 0.0]})["points"]
        assert le[1] == pytest.approx(eta * secs[-1]["y"], abs=1e-9)
        hinge = np.array(le) + 0.75 * (np.array(te) - np.array(le))
        y = eta * secs[-1]["y"]
        k = int(np.searchsorted(ys, y)) - 1
        t = (y - ys[k]) / (ys[k + 1] - ys[k])
        ruled = (1 - t) * _hinge_point(wing, 0.75, ys[k]) + t * _hinge_point(wing, 0.75, ys[k + 1])
        assert np.abs(hinge - ruled).max() <= SHAPE


@needs_openvsp
def test_ingest_of_an_unchanged_model_changes_no_geometry(written, tmp_path):
    doc, _, path = written
    ctx = context(tmp_path, doc)
    ctx.work.mkdir(parents=True)
    shutil.copy(path, ctx.work / "t.vsp3")
    before = copy.deepcopy(doc)
    changes = vsp.ingest(doc, ctx)
    assert len(changes) == 1 and "no geometry change" in changes[0]
    for inst in ("wing_main", "htail", "fin", "fuselage", "aileron_l", "rudder"):
        a, b = adh_doc.find(before, inst), adh_doc.find(doc, inst)
        assert a == b, inst
    assert [r["tool"] for r in adh_doc.node(doc, "1.2")["muas"]["sources"]] == ["OpenVSP"]
    assert vsp.ingest(doc, ctx) == []          # the same file again: the worker does not run


@needs_openvsp
def test_ingest_of_an_edit_writes_only_the_changed_value(written, tmp_path):
    doc, _, path = written
    doc = copy.deepcopy(doc)
    ctx = context(tmp_path, doc)
    ctx.work.mkdir(parents=True)
    runner.run({"job": "edit", "path": str(path), "out": str(ctx.work / "t.vsp3"), "set": [
        {"geom": "htail", "parm": "Tip_Chord", "group": "XSec_1", "value": 0.15}]})
    before = copy.deepcopy(doc)
    changes = vsp.ingest(doc, ctx)
    assert changes == ["htail: section 1 chord 0.17 -> 0.15 m"]
    ht = adh_doc.find(doc, "htail")
    assert ht["muas"]["planform"]["sections"][1]["chord"] == pytest.approx(0.15, abs=EXACT)
    assert ht["muas"]["geometry_tool"] == "OpenVSP"
    assert ht["muas"]["sources"][0]["tool"] == "OpenVSP"
    assert ht["geometry"]["lifting_surface"] == lifting_surface_adh(planform_wing(ht["muas"]["planform"]),
                                                                     foils_of(ht))
    for inst in ("wing_main", "fin", "fuselage", "elevator"):
        assert adh_doc.find(before, inst) == adh_doc.find(doc, inst), inst
    adh_doc.validate_document(doc)


@needs_openvsp
def test_ingest_of_a_moved_aileron_writes_both_sides(written, tmp_path):
    doc, _, path = written
    doc = copy.deepcopy(doc)
    ctx = context(tmp_path, doc)
    ctx.work.mkdir(parents=True)
    secs = WING["sections"]
    runner.run({"job": "edit", "path": str(path), "out": str(ctx.work / "t.vsp3"), "set": [
        {"geom": "wing_main", "parm": "EtaStart", "group": "SS_Control", "value": vsp.eta_to_vsp(secs, 0.5),
         "subsurf": "aileron_l+aileron_r"}]})
    changes = vsp.ingest(doc, ctx)
    assert [c.split(":")[0] for c in changes] == ["aileron_l", "aileron_r"]
    for inst in ("aileron_l", "aileron_r"):
        assert adh_doc.find(doc, inst)["muas"]["control_surface"]["eta_span"] == pytest.approx([0.5, 0.9], abs=1e-9)


@needs_openvsp
def test_ingest_refuses_a_shape_the_adh_form_cannot_hold(written, tmp_path):
    doc, _, path = written
    ctx = context(tmp_path, doc)
    ctx.work.mkdir(parents=True)
    runner.run({"job": "edit", "path": str(path), "out": str(ctx.work / "t.vsp3"), "set": [
        {"geom": "wing_main", "parm": "Twist_Location", "group": "XSec_1", "value": 0.5}]})
    with pytest.raises(runner.OpenVSPError, match="Twist_Location"):
        vsp.ingest(copy.deepcopy(doc), ctx)


# ------------------------------------------------------------------------------------------------------- analysis
def _rows(col_values, key, alphas=None, betas=None):
    n = len(col_values)
    return {"rows": [{"AoA": (alphas or [0.0] * n)[i], "Beta": (betas or [0.0] * n)[i], key: col_values[i]} for i in range(n)]}


def test_summary_recovers_known_slopes_and_the_neutral_point():
    k = math.pi / 180.0
    a = [-4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0]
    cla, cma, cl0, cm0 = 5.0, -0.6, 0.1, 0.02          # per rad
    alpha = {"rows": [{"AoA": x, "Beta": 0.0, "CLtot": cl0 + cla * x * k, "CMytot": cm0 + cma * x * k, "CDtot": 0.02}
                      for x in a]}
    b = [-6.0, -3.0, 0.0, 3.0, 6.0]
    beta = {"rows": [{"AoA": 3.0, "Beta": x, "CStot": -0.3 * x * k, "CMxtot": 0.1 * x * k, "CMztot": -0.07 * x * k}
                     for x in b]}
    s = vsp.summarize(alpha, beta, alpha_trim=2.0, x_ref=0.1, c_ref=0.3)
    assert s["CLa"] == pytest.approx(cla) and s["Cma"] == pytest.approx(cma)
    assert s["CL0"] == pytest.approx(cl0) and s["Cm0"] == pytest.approx(cm0)
    assert s["NP_x"] == pytest.approx(0.1 - 0.3 * cma / cla)
    assert (s["Cyb"], s["Clb"], s["Cnb"]) == pytest.approx((-0.3, -0.1, 0.07))
    assert s["alpha_window_deg"] == [-2.0, 6.0]


def test_summary_drops_a_slope_with_fewer_than_three_points():
    alpha = {"rows": [{"AoA": 0.0, "Beta": 0.0, "CLtot": 0.1, "CMytot": 0.0, "CDtot": 0.0},
                      {"AoA": 2.0, "Beta": 0.0, "CLtot": float("nan"), "CMytot": 0.0, "CDtot": 0.0},
                      {"AoA": 4.0, "Beta": 0.0, "CLtot": 0.3, "CMytot": 0.0, "CDtot": 0.0}]}
    beta = {"rows": [{"AoA": 0.0, "Beta": 0.0, "CStot": 0.0, "CMxtot": 0.0, "CMztot": 0.0}]}
    assert "CLa" not in vsp.summarize(alpha, beta, alpha_trim=2.0, x_ref=0.0, c_ref=0.3)


def test_range_gives_the_number_of_points():
    assert vsp._range([-4, 12, 2]) == [-4.0, 12.0, 9]
    assert vsp._range([-8, 8, 4]) == [-8.0, 8.0, 5]


@needs_openvsp
def test_compgeom_gives_area_and_volume(written):
    _, spec, path = written
    sets = {"wings": ["wing_main", "htail", "fin"], "body": ["fuselage"]}
    r = runner.run({"job": "compgeom", "path": str(path), "sets": sets, "set": "body"})
    assert r["total_theo_volume_m3"] > 0 and r["total_wet_area_m2"] > 0
    from aeroplan.geometry import body_mesh
    from aeroplan.skin_body import mesh_volume

    vol = mesh_volume(body_mesh({"cross_sections": [
        {"upper_curve": {"points": [dict(zip("xyz", p)) for p in f[: int(np.argmax(f[:, 1])) + 1]]},
         "lower_curve": {"points": [dict(zip("xyz", p)) for p in f[int(np.argmax(f[:, 1])):]]}} for f in
        [np.asarray(f) for f in spec["body"]["frames"]]]}))
    assert r["total_theo_volume_m3"] == pytest.approx(vol, rel=0.08)


@needs_openvsp
def test_vspaero_vlm_lift_rises_with_alpha(written, tmp_path):
    _, _, path = written
    sets = {"wings": ["wing_main", "htail", "fin"]}
    case = {"sref": 1.0, "bref": 2.8, "cref": 0.3, "xcg": 0.2, "ycg": 0.0, "zcg": 0.0, "mach": 0.04, "vinf": 14.0,
            "rho": 1.225, "alpha": [0.0, 4.0, 3], "beta": [0.0, 0.0, 1], "wake_iter": 3, "fixed_wake": True, "ncpu": 2}
    r = runner.run({"job": "vspaero", "path": str(path), "dir": str(tmp_path), "name": "t", "sets": sets, "thin": "wings",
                    "thick": None, "case": case}, timeout=600)
    cl = [row["CLtot"] for row in r["rows"]]
    assert len(cl) == 3 and all(np.isfinite(cl)) and cl[0] < cl[1] < cl[2]


@needs_openvsp
def test_two_bodies_round_trip_with_no_gap(tmp_path):
    doc, boom = two_body_doc()
    spec = vsp.spec_from_doc(doc, {"wings": ["wing_main", "htail", "fin"], "bodies": ["fuselage", "tail_boom"]})
    path = tmp_path / "t2.vsp3"
    runner.run({"job": "write", "spec": spec, "path": str(path)})
    back = runner.run({"job": "read", "path": str(path)})["spec"]
    assert back["other"] == []
    assert sorted(b["instance"] for b in back["bodies"]) == ["fuselage", "tail_boom"]
    by = {b["instance"]: b for b in back["bodies"]}
    for b in spec["bodies"]:
        fa, fb = np.array(b["frames"]), np.array(by[b["instance"]]["frames"])
        assert fa.shape == fb.shape and np.abs(fa - fb).max() <= EXACT
    gaps = vsp.shape_gaps(path, {}, [(b["instance"], [np.asarray(f) for f in b["frames"]]) for b in spec["bodies"]])
    assert set(gaps) == {"fuselage", "tail_boom"} and max(gaps.values()) <= SHAPE, gaps


@needs_openvsp
def test_parts_are_cylinders_on_their_axis(tmp_path):
    """A boom along x and a rotor disc with a tilted axis: the surface points lie on the cylinder, the model reads back."""
    c, ax, rad, thick = np.array([0.3, 0.5, 0.1]), np.array([0.0, 0.2, 0.98]), 0.3, 0.01
    ax = ax / np.linalg.norm(ax)
    spec = {"wings": [], "bodies": [], "reference_meshes": [], "parts": [
        {"name": "boom_x", "p0": [0.0, -0.5, 0.1], "axis": [1.0, 0.0, 0.0], "length": 1.0, "radius": 0.02},
        {"name": "disc", "p0": (c - 0.5 * thick * ax).tolist(), "axis": ax.tolist(), "length": thick, "radius": rad}]}
    path = tmp_path / "parts.vsp3"
    runner.run({"job": "write", "spec": spec, "path": str(path)})
    back = runner.run({"job": "read", "path": str(path)})["spec"]
    assert sorted(p["name"] for p in back["parts"]) == ["boom_x", "disc"] and back["other"] == [] and back["bodies"] == []
    u, w = np.meshgrid(np.linspace(0.05, 0.95, 9), np.linspace(0.0, 1.0, 13))
    for name, centre, axis, length, r in (("boom_x (part)", [0.5, -0.5, 0.1], [1, 0, 0], 1.0, 0.02), ("disc (part)", c, ax, thick, rad)):
        pts = np.array(runner.run({"job": "probe", "path": str(path), "geom": name, "u": u.ravel().tolist(),
                                   "w": w.ravel().tolist()})["points"]) - np.asarray(centre)
        along = pts @ np.asarray(axis, float)
        radial = np.linalg.norm(pts - np.outer(along, axis), axis=1)
        assert np.abs(along).max() <= 0.5 * length + 1e-6 and radial.max() <= r + 1e-4 and radial.max() >= 0.9 * r


# ------------------------------------------------------------------------------------------------ actuator disks
def test_disk_coefficients_invert_to_thrust_and_power():
    ct, cp = vsp.disk_coefficients(30.0, 250.0, 2800.0, 0.66, 1.225)
    n = 2800.0 / 60.0
    assert ct * 1.225 * n ** 2 * 0.66 ** 4 == pytest.approx(30.0, rel=1e-12)
    assert cp * 1.225 * n ** 3 * 0.66 ** 5 == pytest.approx(250.0, rel=1e-12)


def fake_rotor_doc(monkeypatch, outputs):
    """A document stand-in: two rotors (one cw, one ccw, thrust up) and the sizing outputs of node 1.2."""
    def prop(spin, x, y):
        return {"muas": {"propeller": {"hub": {"xyz": [x, y, 0.1]}, "thrust_axis": [0.0, 0.0, 1.0],
                                       "diameter": {"value": 0.5}, "spin": spin}}}
    items = {"r_a": prop("cw", 0.0, 0.4), "r_b": prop("ccw", 0.6, -0.4)}
    air = {"performance": [{"tools": [{"data_exchange": {"outputs": [{"name": k, "value": v} for k, v in outputs.items()]}}]}]}
    monkeypatch.setattr(vsp.adh_doc, "find", lambda doc, inst: items[inst])
    monkeypatch.setattr(vsp.adh_doc, "node", lambda doc, wbs: air)
    return {}


def test_disk_states_take_the_sizing_outputs_and_the_spin_sign(monkeypatch):
    out = {"h_f_rpm": 3000.0, "h_f_thrust": 20.0, "h_f_shaft_power": 200.0,
           "h_r_rpm": 2000.0, "h_r_thrust": 10.0, "h_r_shaft_power": 90.0}
    doc = fake_rotor_doc(monkeypatch, out)
    st = {"disk_states": {"hover": {"r_a": "h_f", "r_b": "h_r"}, "cruise": {"r_a": "c"}}}
    states, missing = vsp.disk_states(doc, st, 1.2)
    assert missing == {"cruise": ["c_rpm", "c_thrust", "c_shaft_power"]} and set(states) == {"hover"}
    a, b = states["hover"]["r_a"], states["hover"]["r_b"]
    assert a["rpm"] == -3000.0 and b["rpm"] == 2000.0                    # cw: against the slipstream axis, ccw: with it
    assert a["ct"] == pytest.approx(vsp.disk_coefficients(20.0, 200.0, 3000.0, 0.5, 1.2)[0]) and b["thrust_N"] == 10.0
    g = vsp.rotor_geoms(doc, ["r_a"])[0]
    assert g["axis"] == [-0.0, -0.0, -1.0] and g["p0"] == [0.0, 0.4, 0.1] and g["diameter"] == 0.5   # slipstream down


@needs_openvsp
def test_actuator_disk_runs_in_vspaero(tmp_path):
    """A disk ahead of a wing: VSPAERO has the disk at its hub with its CT, the slipstream adds lift, more thrust adds more,
    and the spin sign turns the roll moment."""
    doc = make_doc()
    spec = vsp.spec_from_doc(doc, {"wings": ["wing_main"]})
    x0 = spec["wings"][0]["position"][0]
    spec["rotors"] = [{"instance": "disk", "p0": [x0 - 0.3, 0.3, 0.0], "axis": [1.0, 0.0, 0.0], "diameter": 0.3}]
    path = tmp_path / "disk.vsp3"
    runner.run({"job": "write", "spec": spec, "path": str(path)})
    back = runner.run({"job": "read", "path": str(path)})["spec"]
    assert [r["instance"] for r in back["rotors"]] == ["disk"] and back["other"] == []
    case = {"sref": 1.0, "bref": 2.0, "cref": 0.3, "xcg": x0, "ycg": 0.0, "zcg": 0.0, "mach": 0.04, "vinf": 14.0, "rho": 1.225,
            "wake_iter": 3, "fixed_wake": True, "ncpu": 2, "alpha": [4.0, 4.0, 1], "beta": [0.0, 0.0, 1]}

    def run(name, rotors):
        res = runner.run({"job": "vspaero", "path": str(path), "dir": str(tmp_path / name), "name": name,
                          "sets": {"w": ["wing_main"]}, "thin": "w", "thick": None, "case": {**case, "rotors": rotors}}, timeout=600)
        return res["rows"][0], res["rotors"]
    none, used0 = run("none", {})
    low, used1 = run("low", {"disk": {"rpm": 3000.0, "ct": 0.05, "cp": 0.04}})
    high, _ = run("high", {"disk": {"rpm": 3000.0, "ct": 0.15, "cp": 0.12}})
    neg, _ = run("neg", {"disk": {"rpm": -3000.0, "ct": 0.15, "cp": 0.12}})
    assert used0 == [] and len(used1) == 1
    assert used1[0]["xyz"] == pytest.approx([x0 - 0.3, 0.3, 0.0], abs=1e-9) and used1[0]["ct"] == pytest.approx(0.05)
    assert used1[0]["radius"] == pytest.approx(0.15) and used1[0]["normal"] == pytest.approx([1.0, 0.0, 0.0])
    assert none["CLtot"] < low["CLtot"] < high["CLtot"]
    # the swirl turns the roll moment with the sign of the rpm (positive rpm: lower CMx, measured 2026-10-18); the lift changes by a few per cent
    assert high["CMxtot"] < neg["CMxtot"] and high["CLtot"] == pytest.approx(neg["CLtot"], rel=0.1)
