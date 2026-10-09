"""The data files, the asset register, the source tree, the .muas package, the ADH document, the DAVE-ML <-> ADH
form and the spokes. Every number is synthetic."""
import copy
import hashlib
import io
import math
import zipfile

import h5py
import numpy as np
import pytest
from sources import make_propalyser_h5

from aeroplan import adh_doc, assets, daveml_adh, gltf, h5json, package, source_tree
from aeroplan.adapters.flow5_geometry import Section, Wing, read_plane
from aeroplan.aero_buildup import AeroBuildUp, Coefficient, _cl_table, to_daveml
from aeroplan.build import placeholders
from aeroplan.consumers import missing_for_flight
from aeroplan.dml_validate import validate_dml
from aeroplan.geometry import body_adh, body_frames, foils_of, lifting_surface_adh, planform_reference
from aeroplan.spokes import Context, load, set_sources

FOIL = np.array([[1.0, 0.0], [0.5, 0.05], [0.0, 0.0], [0.5, -0.03], [1.0, 0.0]])
META = {"form": "tables", "fidelity": "L0", "model_description": {"generation_tool": "test"}}


# ---------------------------------------------------------------------------------------------------------- data files
def test_h5json_round_trip_keeps_values_types_and_order():
    v = {"b": 1, "a": {"z": "text", "y": [1, 2], "x": [1.5, 2.0], "w": [[0.0, 1.0], [2.0, 3.5]], "v": ["p", "q"],
                       "u": [{"k": 1}, {"j": []}], "pts": [{"x": 1.0, "y": 2.0, "z": 3.0}, {"x": 0.5, "y": 0.0, "z": 1.0}],
                       "t": [], "s": True, "r": "L" * 5000, "q": [True, False],
                       "table": h5json.numbers_text(np.linspace(0.0, 1.0, 40)), "short": "1.0 2.0"}}
    data = h5json.to_bytes(v, attrs={"k": "v"})
    attrs, back = h5json.read_file(data)
    assert back == v and attrs == {"k": "v"}
    assert list(back["a"]) == list(v["a"])
    with h5py.File(io.BytesIO(data), "r") as f:
        assert f["data/a/pts"].attrs["_records"]          # point lists are tables, not one group per point
        assert f["data/a/table"].dtype == np.float64      # a DAVE-ML number text is a float array
    assert h5json.to_bytes(v, attrs={"k": "v"}) == data    # same value, same bytes


def test_h5json_refuses_none_and_a_bad_key():
    with pytest.raises(h5json.H5JsonError):
        h5json.to_bytes({"a": None}, attrs={})
    with pytest.raises(h5json.H5JsonError):
        h5json.to_bytes({"a/b": 1}, attrs={})


# ---------------------------------------------------------------------------------------------------------- assets
def _aircraft(tmp_path):
    """A synthetic aircraft with one raw file and one dataset."""
    acft = source_tree.new("t", consumers=["review", "archive"])
    f = tmp_path / "AeroSandbox" / "work" / "t" / "x.txt"
    f.parent.mkdir(parents=True)
    f.write_text("synthetic")
    air = adh_doc.node(acft.doc, "1.2", create=True)
    adh_doc.muas(air, "t_airvehicle")
    ctx = Context("t", tmp_path, "AeroSandbox", acft)
    ref = ctx.source_ref(f, "test file")
    set_sources(air, "AeroSandbox", [ref])
    ctx.add_dataset(air, "aero.t", {"x": [1.0, 2.0]}, role="test table", dataset_role="aero",
                    derived_from=[ref["asset"]], meta=META)
    return acft


def test_asset_ids_are_content_hashes(tmp_path):
    acft = _aircraft(tmp_path)
    reg = assets.register(acft.doc)
    f = next(e for e in reg if e["kind"] == "file")
    d = next(e for e in reg if e["kind"] == "dataset")
    assert f["id"] == "asset:sha256:" + hashlib.sha256(b"synthetic").hexdigest()
    assert f["locations"] == [{"repo": "AeroSandbox/work/t/x.txt"}]
    assert d["id"] == assets.dataset_id({"x": [1.0, 2.0]}) and d["derived_from"] == [f["id"]]
    assert assets.dataset(acft, d["id"] + "#/x/1") == 2.0
    adh_doc.validate_document(acft.doc)


def test_a_changed_dataset_is_a_new_asset(tmp_path):
    acft = _aircraft(tmp_path)
    air = adh_doc.node(acft.doc, "1.2")
    old = assets.item_dataset(air, "aero")["ref"]
    Context("t", tmp_path, "AeroSandbox", acft).add_dataset(
        air, "aero.t", {"x": [1.0, 3.0]}, role="test table", dataset_role="aero", meta=META)
    new = assets.item_dataset(air, "aero")["ref"]
    assert new != old and old not in acft.datasets
    assert [e["name"] for e in assets.register(acft.doc)].count("aero.t") == 1


def test_fetch_checks_the_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "cache_dir", lambda: tmp_path / "cache")
    acft = _aircraft(tmp_path)
    e = next(e for e in assets.register(acft.doc) if e["kind"] == "file")
    assert assets.fetch(e, tmp_path).read_text() == "synthetic"
    (tmp_path / "AeroSandbox" / "work" / "t" / "x.txt").write_text("changed")
    with pytest.raises(assets.AssetError, match="not on this machine"):
        assets.fetch(e, tmp_path)


def test_stale_derived_asset_gives_a_warning(tmp_path):
    from aeroplan.datum import datum_checks

    acft = _aircraft(tmp_path)
    d = next(e for e in assets.register(acft.doc) if e["kind"] == "dataset")
    d["derived_from"] = ["asset:sha256:" + "0" * 64]
    rep = datum_checks(acft.doc, tmp_path)
    assert rep.ok and any("stale" in c.name for c in rep.checks)


# ---------------------------------------------------------------------------------------------------------- source tree
def test_source_tree_round_trip(tmp_path):
    acft = _aircraft(tmp_path)
    source_tree.write(acft, tmp_path / "tree")
    names = sorted(p.name for p in (tmp_path / "tree" / "adh").iterdir())
    assert names == ["1.0.aircraft_system.json", "1.10.2.data_repository.json", "1.10.data.json",
                     "1.2.air_vehicle.json"]
    back = source_tree.read(tmp_path / "tree")
    assert back.doc == acft.doc and back.datasets == acft.datasets


def test_source_tree_refuses_an_edited_dataset(tmp_path):
    source_tree.write(_aircraft(tmp_path), tmp_path / "tree")
    (tmp_path / "tree" / "datasets" / "aero.t.json").write_text('{"x": [1.0, 9.0]}')
    with pytest.raises(source_tree.SourceTreeError, match="never edited"):
        source_tree.read(tmp_path / "tree")


# ---------------------------------------------------------------------------------------------------------- package
def test_pack_is_deterministic_and_unpacks(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "cache_dir", lambda: tmp_path / "cache")
    acft = _aircraft(tmp_path)
    out = package.pack(acft, "archive", tmp_path, tmp_path / "dist")
    first = out.read_bytes()
    out.unlink()
    assert package.pack(acft, "archive", tmp_path, tmp_path / "dist").read_bytes() == first
    with zipfile.ZipFile(out) as z:
        info = z.infolist()
        assert info[0].filename == "mimetype" and info[0].compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/vnd.muas+zip"
    pkg = package.open_package(out)
    assert pkg.manifest["kind"] == "aircraft" and pkg.manifest["profile"] == "archive"
    assert {e["storage"] for e in assets.register(pkg.doc)} <= {"inline", "embedded"}
    package.unpack(out, tmp_path / "back" / "t", tmp_path)
    back = source_tree.read(tmp_path / "back" / "t")
    assert back.doc == acft.doc and back.datasets == acft.datasets


def test_review_profile_links_the_data(tmp_path):
    acft = _aircraft(tmp_path)
    pkg = package.open_package(package.pack(acft, "review", tmp_path, tmp_path / "dist"))
    assert {e["storage"] for e in assets.register(pkg.doc)} == {"linked"}
    with pytest.raises(package.PackageError, match="linked"):
        pkg.dataset(assets.item_dataset(adh_doc.node(pkg.doc, "1.2"), "aero")["ref"])


def test_tampered_package_is_refused(tmp_path):
    out = package.pack(_aircraft(tmp_path), "review", tmp_path, tmp_path / "dist")
    bad = tmp_path / "bad.muas"
    with zipfile.ZipFile(out) as zin, zipfile.ZipFile(bad, "w") as zout:
        for i in zin.infolist():
            data = zin.read(i.filename)
            if i.filename == "aircraft.adh.json":
                data = data.replace(b"Synthetic", b"synthetic") + b" "
            zout.writestr(i, data)
    with pytest.raises(package.PackageError, match="sha256"):
        package.open_package(bad)


def test_a_package_is_never_overwritten(tmp_path):
    acft = _aircraft(tmp_path)
    package.pack(acft, "review", tmp_path, tmp_path / "dist")
    adh_doc.node(acft.doc, "1.2")["description"] = "changed"
    with pytest.raises(package.PackageError, match="never edited"):
        package.pack(acft, "review", tmp_path, tmp_path / "dist")


def test_profile_refuses_what_the_consumer_lacks(tmp_path):
    acft = _aircraft(tmp_path)
    with pytest.raises(package.PackageError, match="consumers"):
        package.pack(acft, "aerolink", tmp_path, tmp_path / "dist")
    acft.info["consumers"].append("aerolink")
    with pytest.raises(package.PackageError, match="propulsion_system"):
        package.pack(acft, "aerolink", tmp_path, tmp_path / "dist")


def test_gltf_round_trip():
    tri = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.25]]])
    data = gltf.write_glb([("b", tri, {"item": "x"}), ("a", tri + 1.0, {"hinge": [[0, 0, 0], [0, 1, 0]]})],
                          aircraft="t")
    assert data[:4] == b"glTF" and len(data) % 4 == 0
    extras, parts = gltf.read_glb(data)
    assert extras["frame"].startswith("design") and list(parts) == ["a", "b"]
    assert np.allclose(parts["b"][0], tri) and parts["a"][1]["hinge"] == [[0, 0, 0], [0, 1, 0]]


# ---------------------------------------------------------------------------------------------------------- flight
def test_flight_event_and_software_release_sit_on_their_nodes():
    doc = adh_doc.new_document("T", "synthetic")
    sw = adh_doc.node(doc, "1.2.9", create=True)
    adh_doc.muas(sw, "software")["software_releases"] = [
        {"release_id": "fw1", "firmware": "ArduPlane", "version": "0.0.1", "source": "synthetic"}]
    ft = adh_doc.node(doc, "1.8.1.4", create=True)
    event = {"event_id": "f1", "date": "2026-01-01", "aircraft_version": "0.1.0", "mass": {"value": 1.0, "units": "kg"},
             "cg": {"xyz": [0.0, 0.0, 0.0]}, "firmware": "fw1", "log": "asset:sha256:" + "1" * 64,
             "segments": [{"name": "s", "t_start_s": 1.0, "t_end_s": 2.0, "purpose": "system_id"}],
             "source": "synthetic"}
    adh_doc.muas(ft, "flight_tests")["flight_tests"] = [event]
    adh_doc.validate_document(doc)
    event["segments"][0]["t_end_s"] = 0.5
    with pytest.raises(Exception, match="t_end_s"):
        adh_doc.validate_document(doc)


# ---------------------------------------------------------------------------------------------------------- document
def test_wbs_tree_comes_from_upstream():
    t = adh_doc.wbs_tree()
    assert t["1.2.2.3"]["path"] == ("air_vehicle", "airframe", "wing")
    assert t["1.2.2.2"]["name"] == "Fuselage" and t["1.2.2.1"]["name"] != "Fuselage"


def test_document_rules():
    doc = adh_doc.new_document("T", "synthetic")
    wing = adh_doc.node(doc, "1.2.2.3", create=True)
    adh_doc.muas(wing, "wing_main")
    adh_doc.validate_document(doc)
    bad = copy.deepcopy(doc)
    adh_doc.node(bad, "1.2.2.3")["wbs_no"] = "1.2.2.4"
    with pytest.raises(ValueError, match="does not match its place"):
        adh_doc.validate_document(bad)
    bad = copy.deepcopy(doc)
    adh_doc.node(bad, "1.2.2.3")["colour"] = "red"
    with pytest.raises(ValueError, match="unknown keys"):
        adh_doc.validate_document(bad)
    bad = copy.deepcopy(doc)
    adh_doc.put_subcomponent(adh_doc.node(bad, "1.2.2.3"), {"name": "x", "muas": {"ext_version": "0.2.0", "instance": "wing_main"}})
    with pytest.raises(ValueError, match="also used"):
        adh_doc.validate_document(bad)
    with pytest.raises(KeyError):
        adh_doc.node(doc, "9.9", create=True)


def test_flight_readiness_lists_the_missing_items():
    doc = adh_doc.new_document("T", "synthetic")
    missing = missing_for_flight(doc)
    assert any(m.startswith("dataset aero") for m in missing) and any(m.startswith("autopilot") for m in missing)


def test_placeholders_are_listed():
    doc = adh_doc.new_document("T", "synthetic")
    adh_doc.muas(doc, "aircraft_system")["aero_settings"] = {"cl_max": 1.0, "cl_min": -0.5, "source": "test",
                                                             "placeholder": True}
    assert placeholders(doc) == ["aircraft_system.muas.aero_settings"]


# ---------------------------------------------------------------------------------------------------------- DAVE-ML
def _build_up() -> AeroBuildUp:
    names = ["CL0", "CLa", "CLq", "CLde", "CD0", "K", "CDde", "CYb", "CYp", "CYr", "CYdr", "Clb", "Clp", "Clr", "Clda",
             "Cldr", "Cm0", "Cma", "Cmq", "Cmde", "Cnb", "Cnp", "Cnr", "Cnda", "Cndr"]
    co = {k: Coefficient(0.1 * (i + 1), "nd" if k in ("CL0", "CD0", "K", "Cm0") else "1_per_rad", "synthetic")
          for i, k in enumerate(names)}
    co["CLa"] = Coefficient(5.0, "1_per_rad", "synthetic")
    return AeroBuildUp(co, _cl_table(0.1, 5.0, 1.2, -0.5), "synthetic", {"alpha_rad": 0.05}, [])


def test_daveml_round_trip_through_the_adh_form():
    xml = to_daveml(_build_up(), name="t", author="a", org="o", created="2026-01-01", description="synthetic")
    adh = daveml_adh.from_xml(xml)
    back = daveml_adh.to_xml(adh)
    assert daveml_adh.canonical(back) == daveml_adh.canonical(xml)
    assert validate_dml(back) == []
    assert adh["variable_def"][0]["is_input"] is True


def test_daveml_adh_form_survives_the_data_file():
    xml = to_daveml(_build_up(), name="t", author="a", org="o", created="2026-01-01", description="synthetic")
    adh = assets.clean(daveml_adh.from_xml(xml))
    back = h5json.read_file(h5json.to_bytes(adh, attrs={}))[1]
    assert assets.dataset_id(back) == assets.dataset_id(adh)
    assert daveml_adh.canonical(daveml_adh.to_xml(back)) == daveml_adh.canonical(xml)


# ---------------------------------------------------------------------------------------------------------- geometry
def _wing():
    return Wing("W", "MAINWING", (0.1, 0.0, 0.0), 0.0, 0.0, True, True,
                (Section(0.0, 0.4, 0.0, 2.0, 1.0, "F"), Section(1.0, 0.2, 0.1, 2.0, -1.0, "F")))


def test_planform_reference_of_a_trapezoid():
    pf = {"sections": [{"y": 0.0, "chord": 0.4}, {"y": 1.0, "chord": 0.2}]}
    r = planform_reference(pf)
    assert r["area_m2"] == pytest.approx(0.6) and r["span_m"] == 2.0
    assert r["mac_m"] == pytest.approx(2 / 0.6 * (0.16 + 0.08 + 0.04) / 3)


def test_lifting_surface_and_foils_round_trip():
    ls = lifting_surface_adh(_wing(), {"F": FOIL})
    item = {"geometry": {"lifting_surface": ls},
            "muas": {"instance": "w", "planform": {"sections": [{"foil": "F"}, {"foil": "F"}]}}}
    assert np.allclose(foils_of(item)["F"], FOIL)
    le = ls["leading_edge_spline"]["points"]
    assert le[0]["x"] == pytest.approx(0.1, abs=1e-4) and math.isclose(le[1]["y"], 1.0)


def test_body_round_trip():
    frames = [np.array([[0.0, 0.0, 0.0]] * 4), np.array([[0.5, 0.0, 0.1], [0.5, 0.1, 0.0], [0.5, 0.05, -0.08],
                                                          [0.5, 0.0, -0.1]]), np.array([[1.0, 0.0, 0.0]] * 4)]
    back = body_frames(body_adh(frames))
    assert all(np.allclose(a, b) for a, b in zip(frames, back))


# ---------------------------------------------------------------------------------------------------------- spokes
def test_aerosandbox_parse_and_unit_checks():
    sb = load("AeroSandbox")
    text = "Wing area: 1.0\nWing span: 3.0\nAspect ratio: 9.0\nm_wing: 1.0\nm_misc: 2.0\nm_total: 3.0\n" \
           "C_D: 0.05\nC_D_i: 0.01\nC_D_o: 0.04\nC_L: 0.5\nGlide ratio: 10.0\n"
    v = sb.parse(text)
    assert v["Wing span"] == 3.0
    assert len(sb.consistency(v)) == 4
    with pytest.raises(ValueError, match="aspect ratio"):
        sb.consistency(dict(v, **{"Aspect ratio": 5.0}))
    with pytest.raises(ValueError, match="Name: number"):
        sb.parse("no colon here")


def test_propalyser_reads_contract_b(tmp_path):
    p = tmp_path / "sys_x.v2.h5"
    make_propalyser_h5(p)
    d = load("Propalyser").read_system(p)
    assert d["system_id"] == "sys_x" and d["blades"] == 2 and d["placeholder"] is True
    assert d["throttle_map"]["columns"]["esc_command_norm"] == [0.0, 0.5, 1.0]
    make_propalyser_h5(tmp_path / "v1.h5", version=1)
    with pytest.raises(ValueError, match="version"):
        load("Propalyser").read_system(tmp_path / "v1.h5")
    make_propalyser_h5(tmp_path / "bad.h5", bad_units=True)
    with pytest.raises(ValueError, match="pint"):
        load("Propalyser").read_system(tmp_path / "bad.h5")


def test_flow5_plane_xml_round_trip(tmp_path):
    import importlib

    load("flow5")
    px = importlib.import_module("aeroplan_spokes.flow5.plane_xml")
    read_body_and_masses, write_plane = px.read_body_and_masses, px.write_plane
    pf = {"surface_name": "W", "kind": "MAINWING", "position": {"xyz": [0.1, 0.0, 0.0]}, "rx_deg": 0.0, "ry_deg": 0.0,
          "symmetric": True, "two_sided": True,
          "sections": [{"y": 0.0, "chord": 0.4, "x_offset": 0.0, "dihedral_deg": 2.0, "twist_deg": 1.0, "foil": "F"},
                       {"y": 1.0, "chord": 0.2, "x_offset": 0.1, "dihedral_deg": 2.0, "twist_deg": -1.0, "foil": "F"}]}
    frames = [np.array([[0.0, 0.0, 0.0]] * 3), np.array([[0.5, 0.0, 0.1], [0.5, 0.1, 0.0], [0.5, 0.0, -0.1]])]
    masses = [{"tag": "BAT", "mass_kg": 1.0, "xyz": [0.1, 0.0, 0.0]}]
    path = tmp_path / "p.xml"
    write_plane(path, "p", [pf], {"frames": frames, "position": [0.0, 0.0, 0.0]}, masses, {})
    w = read_plane(path).wings[0]
    assert [s.chord for s in w.sections] == [0.4, 0.2] and w.position == (0.1, 0.0, 0.0)
    f2, _, m2, _ = read_body_and_masses(path)
    assert np.allclose(f2[1], frames[1]) and m2 == masses


def test_spoke_without_input_is_skipped(tmp_path):
    ctx = Context("nothing_here", tmp_path, "AeroSandbox", source_tree.new("nothing_here"))
    assert load("AeroSandbox").ingest({}, ctx) is None


def test_source_ref_registers_the_file(tmp_path):
    acft = source_tree.new("a")
    f = tmp_path / "AeroSandbox" / "work" / "a" / "x.txt"
    f.parent.mkdir(parents=True)
    f.write_text("x")
    ref = Context("a", tmp_path, "AeroSandbox", acft).source_ref(f, "test")
    e = assets.entry(acft.doc, ref["asset"])
    assert e["locations"] == [{"repo": "AeroSandbox/work/a/x.txt"}] and e["tool"] == "AeroSandbox"


def test_ardupilot_records_a_flight(tmp_path):
    import yaml

    acft = source_tree.new("t")
    ctx = Context("t", tmp_path, "ArduPilot", acft)
    ctx.work.mkdir(parents=True)
    (ctx.work / "f1.bin").write_bytes(b"synthetic log")
    (ctx.work / "f1.param").write_text("# synthetic\nARSPD_FBW_MIN,12\nTRIM_ARSPD_CM 1500\n")
    ctx.settings_file.parent.mkdir(parents=True)
    ctx.settings_file.write_text(yaml.safe_dump({
        "releases": [{"release_id": "fw1", "firmware": "ArduPlane", "version": "0.0.1", "source": "synthetic"}],
        "flights": [{"event_id": "f1", "date": "2026-01-01", "log": "f1.bin", "params": "f1.param", "firmware": "fw1",
                     "aircraft_version": "0.1.0", "mass_kg": 1.0, "cg_m": [0.0, 0.0, 0.0], "source": "synthetic",
                     "segments": [{"name": "doublet", "t_start_s": 1.0, "t_end_s": 2.0, "purpose": "system_id"}]}]}))
    assert load("ArduPilot").ingest(acft.doc, ctx) == ["software releases: fw1", "flight f1: 1 segments"]
    adh_doc.validate_document(acft.doc)
    ev = adh_doc.node(acft.doc, "1.8.1.4")["muas"]["flight_tests"][0]
    assert assets.dataset(acft, ev["parameters"]) == {"ARSPD_FBW_MIN": 12.0, "TRIM_ARSPD_CM": 1500.0}
    assert assets.entry(acft.doc, ev["log"])["kind"] == "file"
    out = package.pack(acft, "review", tmp_path, tmp_path / "dist")
    assert package.open_package(out).manifest["kind"] == "aircraft"
