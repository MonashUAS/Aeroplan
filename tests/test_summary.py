"""The one-page aircraft summary (`aeroplan show --md`). Synthetic numbers only."""
from aeroplan import source_tree
from aeroplan.summary import aircraft_markdown


def test_summary_of_an_empty_aircraft_lists_every_section():
    text = aircraft_markdown(source_tree.new("t"))
    for head in ("# ", "## Mass properties", "## Propulsion system", "## Datasets", "## Placeholders"):
        assert head in text
    assert "no mass properties" in text and "0 values are marked placeholder" in text
