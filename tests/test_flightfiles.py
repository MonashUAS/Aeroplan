"""The flight files (parameters, waypoints, geofence) in the aircraft: parse, store, pack, export. Synthetic numbers only."""
import pytest
import yaml

from aeroplan import adh_doc, consumers, flightfiles as ff, package, source_tree
from aeroplan.spokes import Context, load

WPL = ("QGC WPL 110\n"
       "0\t1\t0\t16\t0\t0\t0\t0\t10.00000000\t20.00000000\t5.000000\t1\n"
       "1\t0\t3\t22\t12\t0\t0\t0\t10.00000000\t20.00000000\t30.000000\t1\n"
       "2\t0\t3\t16\t0\t0\t0\t0\t10.00100000\t20.00100000\t40.500000\t1\n")
POLY = "# polygon\n10.0 20.0\n10.0 20.01\n10.01 20.01\n10.0 20.0\n"


def _parm(n=1400):
    """A parameter list as large as the full list of ArduPlane."""
    return "".join(f"PARAM_{i:04d},{i * 0.25}\n" for i in range(n))


def test_parm_round_trip():
    p = ff.parse_parm("# c\nA,1\nB 2.5\n", "t")
    assert p == {"A": 1.0, "B": 2.5}
    assert ff.parse_parm(ff.format_parm(p)) == p
    with pytest.raises(ff.FlightFileError, match="not NAME,VALUE"):
        ff.parse_parm("A,1,2")
    with pytest.raises(ff.FlightFileError, match="twice"):
        ff.parse_parm("A,1\nA,2")


def test_wpl_round_trip_is_exact():
    wp = ff.parse_wpl(WPL)
    assert [i["seq"] for i in wp["items"]] == [0, 1, 2] and wp["items"][1]["command"] == 22
    assert ff.format_wpl(wp) == WPL
    with pytest.raises(ff.FlightFileError, match="not a QGC WPL"):
        ff.parse_wpl("x\n")
    with pytest.raises(ff.FlightFileError, match="12"):
        ff.parse_wpl("QGC WPL 110\n0\t1\n")


def test_fence_polygon_is_closed_and_checked():
    pts = ff.parse_poly(POLY)
    assert len(pts) == 3
    with pytest.raises(ff.FlightFileError, match="three points"):
        ff.parse_poly("1 2\n3 4\n")
    with pytest.raises(ff.FlightFileError, match="inclusion"):
        ff.make_geofence([{"inclusion": False, "points": pts}])


def test_fence_parameter_warnings():
    fence = ff.make_geofence([{"inclusion": True, "points": ff.parse_poly(POLY)}])
    assert len(ff.fence_param_warnings(fence, {})) == 2
    assert ff.fence_param_warnings(fence, {"FENCE_ENABLE": 1.0, "FENCE_TYPE": 6.0}) == []
    assert ff.fence_param_warnings(None, {}) == []


def _ingest(tmp_path, settings):
    acft = source_tree.new("t")
    ctx = Context("t", tmp_path, "MissionPlanner", acft)
    ctx.work.mkdir(parents=True)
    (ctx.work / "t.parm").write_text(_parm() + "FENCE_ENABLE,1\nFENCE_TYPE,6\n")
    (ctx.work / "t.waypoints").write_text(WPL)
    (ctx.work / "fence.poly").write_text(POLY)
    ctx.settings_file.parent.mkdir(parents=True)
    ctx.settings_file.write_text(yaml.safe_dump(settings))
    return acft, ctx


SETTINGS = {"firmware": "ArduPlane 0.0.1", "parameters": "t.parm", "waypoints": "t.waypoints",
            "geofence": {"source": "synthetic", "polygons": [{"file": "fence.poly", "kind": "inclusion"}],
                         "circles": [{"lat": 10.0, "lon": 20.0, "radius_m": 50.0, "kind": "exclusion"}],
                         "return_point": {"lat": 10.0, "lon": 20.0}}}


def test_spoke_stores_the_three_files(tmp_path):
    acft, ctx = _ingest(tmp_path, SETTINGS)
    changes = load("MissionPlanner").ingest(acft.doc, ctx)
    assert changes == ["parameters: 1402 from t.parm", "waypoints: 2 items and home from t.waypoints",
                       "geofence: 1 polygons, 1 circles"]
    adh_doc.validate_document(acft.doc)
    ap = adh_doc.node(acft.doc, "1.2.5.10")
    roles = {d["role"] for d in ap["muas"]["datasets"]}
    assert roles == {"parameters", "waypoints", "geofence"}


def test_spoke_without_settings_is_skipped(tmp_path):
    ctx = Context("none", tmp_path, "MissionPlanner", source_tree.new("none"))
    assert load("MissionPlanner").ingest({}, ctx) is None


def test_spoke_warns_when_the_fence_is_off(tmp_path):
    acft, ctx = _ingest(tmp_path, SETTINGS)
    (ctx.work / "t.parm").write_text("A,1\n")
    changes = load("MissionPlanner").ingest(acft.doc, ctx)
    assert sum(c.startswith("geofence: FENCE_") for c in changes) == 2


def test_spoke_refuses_a_fence_without_source(tmp_path):
    acft, ctx = _ingest(tmp_path, {"geofence": {"polygons": [{"file": "fence.poly", "kind": "inclusion"}]}})
    with pytest.raises(ValueError, match="source"):
        load("MissionPlanner").ingest(acft.doc, ctx)


def test_archive_package_holds_the_files_exactly(tmp_path):
    """The dataset hash survives the HDF5 round trip (a full-size parameter list, waypoints, a fence)."""
    acft, ctx = _ingest(tmp_path, SETTINGS)
    load("MissionPlanner").ingest(acft.doc, ctx)
    acft.info["consumers"] = ["review", "archive"]
    out = package.pack(acft, "archive", tmp_path, tmp_path / "dist")
    pkg = package.open_package(out)
    by_role = {d["role"]: d["ref"] for d in adh_doc.node(pkg.doc, "1.2.5.10")["muas"]["datasets"]}
    assert pkg.dataset(by_role["parameters"])["PARAM_0007"] == 1.75
    assert ff.format_wpl(pkg.dataset(by_role["waypoints"])) == WPL
    fence = pkg.dataset(by_role["geofence"])
    assert fence == acft.datasets[by_role["geofence"].partition("#")[0]]
    assert fence["circles"][0]["inclusion"] is False


def test_only_the_aircraft_parameters_go_in_the_aerolink_profile(tmp_path):
    acft, ctx = _ingest(tmp_path, SETTINGS)
    load("MissionPlanner").ingest(acft.doc, ctx)
    from aeroplan import assets

    tiers = {e["name"]: consumers.tier("aerolink", e) for e in assets.register(acft.doc, create=False)
             if e["kind"] == "dataset"}
    assert tiers == {"autopilot.parameters": "embedded", "autopilot.waypoints": "embedded",
                     "autopilot.geofence": "embedded"}
    other = dict(assets.register(acft.doc, create=False)[0], name="parameters.f1")
    assert consumers.tier("aerolink", other) == "linked"


def test_export_writes_the_mission_planner_files(tmp_path):
    acft, ctx = _ingest(tmp_path, SETTINGS)
    load("MissionPlanner").ingest(acft.doc, ctx)
    paths = load("MissionPlanner").export(acft.doc, ctx, tmp_path / "out")
    assert sorted(p.name for p in paths) == ["t.parm", "t.waypoints", "t_fence_1_inclusion.poly"]
    assert (tmp_path / "out" / "t.waypoints").read_text() == WPL
    assert ff.parse_parm((tmp_path / "out" / "t.parm").read_text())["PARAM_0007"] == 1.75
