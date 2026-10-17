import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "aerosandbox"))
import jung2021 as j  # noqa: E402


def test_blades_load_and_si_plausible():
    b = j.load_blades()
    assert {"KPROP_22", "Tmotor_18", "Tmotor_29", "Tmotor_40"} <= set(b)
    for v in b.values():
        assert 0.3 < v["D_m"] < 1.1
        assert v["c_m"].max() < 0.15 and v["c_m"].min() > 0
        assert v["beta_rad"].max() < 0.8 and v["beta_rad"].min() > 0
        assert np.all(np.diff(v["r_over_R"]) > 0) and v["r_over_R"].max() <= 1.0


def test_fit():
    assert abs(j.c_max_fit(0.6604) - 0.0640) < 1e-4


def test_compare_self_curve_is_zero():
    b = j.load_blades()["Tmotor_29"]
    out = j.compare(b["r_over_R"], b["c_m"], b["beta_rad"], b["D_m"])
    assert all(abs(r[3]) < 1e-9 and abs(r[6]) < 1e-9 for r in out["rows"])
