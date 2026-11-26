"""Every committed aircraft source tree (aircraft/<name>/) passes every check of `aeroplan check`.

The test types no aircraft number: it runs the checks on the committed data (ADH tree, dataset hashes, DAVE-ML DTD
and checkData, datums, the consumers of muas.package). A check that needs a raw file (CAD, DAVE-ML source) is left
out when the file is not on the machine (a fresh clone), so the test runs the same on CI.
"""
import pytest

from aeroplan import REPO_ROOT as ROOT
from aeroplan import checks, source_tree

TREES = source_tree.list_aircraft(ROOT)


@pytest.mark.parametrize("folder", TREES, ids=[p.name for p in TREES])
def test_aircraft_source_tree(folder):
    acft = source_tree.read(folder)
    rep = checks.run(acft, ROOT)
    assert rep.passed, rep.text()
    assert (acft.doc.get("muas") or {}).get("build"), "the aircraft has no build record"


@pytest.mark.parametrize("folder", TREES, ids=[p.name for p in TREES])
def test_aircraft_packs_and_unpacks(folder, tmp_path):
    from aeroplan.package import PackageError, open_package, pack, unpack

    acft = source_tree.read(folder)
    for profile in acft.info["consumers"]:
        try:
            out = pack(acft, profile, ROOT, tmp_path / "dist")
        except PackageError as err:
            if "is not on this machine" in str(err):      # archive: a raw file of a fresh clone is not here
                continue
            raise
        assert open_package(out).manifest["profile"] == profile
        unpack(out, tmp_path / profile / acft.name, ROOT)
        back = source_tree.read(tmp_path / profile / acft.name)
        assert back.doc == acft.doc and back.datasets == acft.datasets


def test_the_redback_ardupilot_settings_have_no_fill_in_and_the_flight_names_a_release():
    """The committed settings hold the facts of the log (no FILL_IN). The firmware of the flight is a release of the file."""
    import yaml

    text = (ROOT / "aeroplan" / "ardupilot" / "settings" / "redback.yaml").read_text(encoding="utf-8")
    st = yaml.safe_load(text)
    assert "FILL_IN" not in text
    releases = {r["release_id"]: r for r in st["releases"]}
    for f in st["flights"]:
        assert f["firmware"] in releases and not f.get("wait_for_log")
        assert releases[f["firmware"]]["git_hash"] and releases[f["firmware"]]["board"]
