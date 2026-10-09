"""Shared fixtures. Every number here is a synthetic test value, not aircraft data."""
from datetime import datetime

import pytest


@pytest.fixture
def prov():
    return {"tool": "test", "tool_version": "0", "author": "test", "created": datetime(2026, 1, 1).isoformat()}


@pytest.fixture
def unc_normal():
    return {
        "status": "quantitative", "scope": "result", "basis": "synthetic test value",
        "effect": "additive", "distribution": "normal", "sigma": 0.05, "method": "engineering",
    }
