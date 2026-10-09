import json

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from aeroplan.adapters.flow5 import PolarError, control_range, parse_polar_text
from aeroplan.muas.uncertainty import ScalarResult, Uncertainty

from sources import polar_text


# --- flow5 polar parser ---
def test_polar_welded_first_row_is_found():
    p = parse_polar_text(polar_text("alpha", n=3))
    assert p.data.shape == (3, 10) and p.columns[:4] == ["Ctrl", "alpha", "beta", "phi"] and p.speed == 10.0


def test_polar_partial_file_refused():
    with pytest.raises(PolarError, match="declared"):
        parse_polar_text(polar_text("alpha", n=3, drop_declared=5))


def test_control_range_equal_or_reversed():
    p = parse_polar_text(polar_text("elevator", t6=True))
    assert control_range(p) == (-10.0, 10.0, True)


def test_control_range_conflict_refused():
    text = polar_text("elevator", t6=True).replace("10.000, -10.000", "5.000, -5.000")
    with pytest.raises(PolarError, match="neither equal nor reversed"):
        control_range(parse_polar_text(text))


# --- flow5 adapter ---
def test_interval_needs_coverage_and_has_no_adh_form():
    base = dict(status="quantitative", scope="derived", basis="b", effect="absolute", distribution="interval",
                method="monte_carlo", lower=0.1, upper=0.2)
    with pytest.raises(ValidationError):
        Uncertainty(**base)
    u = Uncertainty(**base, coverage=0.95)
    with pytest.raises(ValueError, match="no ADH"):
        u.to_adh()


def test_scalar_result_order():
    with pytest.raises(ValidationError):
        ScalarResult(median=3, lower=1, upper=2, coverage=0.95)


def test_unknown_provenance_date_is_allowed():
    from aeroplan.muas.provenance import Provenance

    assert Provenance(tool="t", tool_version="v", author="unknown").created is None
