"""Check of a propeller blade against Jung et al. 2021 (Unmanned Systems 9(4) 321-332, DOI 10.1142/S2301385021500163).

Pure numpy and matplotlib. The data are in data/jung2021_blades.csv and data/jung2021_fit.json (SI units).
"""
import csv
import json
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent / "data"


def load_blades(path=None):
    """Return {blade: {D_m, r_over_R, c_m, beta_rad, digitised}} as numpy arrays."""
    path = Path(path) if path else DATA / "jung2021_blades.csv"
    with open(path, newline="") as f:
        rows = list(csv.DictReader(r for r in f if not r.startswith("#")))
    out = {}
    for row in rows:
        b = out.setdefault(row["blade"], {"D_m": float(row["D_m"]), "r_over_R": [], "c_m": [], "beta_rad": [],
                                          "digitised": row["digitised"].strip().lower() == "true"})
        b["r_over_R"].append(float(row["r_over_R"]))
        b["c_m"].append(float(row["c_m"]))
        b["beta_rad"].append(float(row["beta_rad"]))
    for b in out.values():
        for k in ("r_over_R", "c_m", "beta_rad"):
            b[k] = np.array(b[k])
    return out


def c_max_fit(D_m, path=None):
    """Maximum chord in m from the Fig. 10 regression."""
    p = json.loads(Path(path or DATA / "jung2021_fit.json").read_text())["c_max_fit"]
    return p["slope"] * D_m + p["intercept_m"]


def _curves(blades, name):
    b = blades[name]
    return b["r_over_R"], b["c_m"] / (b["D_m"] / 2.0), b["beta_rad"]


def compare(r_over_R, c_m, beta_rad, D_m, reference="Tmotor_29", at=(0.25, 0.5, 0.75, 0.95), blades=None):
    """Differences of a blade against a Jung curve (interpolated in r/R) and the c_max fit.

    Returns a dict: c_max_m, c_max_fit_m, c_max_ratio, and rows of (r/R, c/R, c/R ref, d(c/R), beta deg, beta ref deg, d beta deg).
    """
    blades = blades or load_blades()
    r = np.asarray(r_over_R, float)
    cR = np.asarray(c_m, float) / (D_m / 2.0)
    br, cr, bt = _curves(blades, reference)
    rows = []
    for x in at:
        c0 = float(np.interp(x, r, cR))
        b0 = float(np.degrees(np.interp(x, r, beta_rad)))
        c1 = float(np.interp(x, br, cr))
        b1 = float(np.degrees(np.interp(x, br, bt)))
        rows.append((x, c0, c1, c0 - c1, b0, b1, b0 - b1))
    cm = float(np.max(c_m))
    fit = float(c_max_fit(D_m))
    return {"c_max_m": cm, "c_max_fit_m": fit, "c_max_ratio": cm / fit, "r_at_c_max": float(r[int(np.argmax(c_m))]),
            "reference": reference, "rows": rows}


def plot_compare(ax_chord, ax_twist, r_over_R, c_m, beta_rad, D_m, label="blade", blades=None):
    """Draw c/R and twist (deg) of a blade over the Jung T-motor points."""
    blades = blades or load_blades()
    for name, mk in (("Tmotor_18", "s"), ("Tmotor_29", "o"), ("Tmotor_40", "^")):
        br, cr, bt = _curves(blades, name)
        ax_chord.plot(br, cr, mk, mfc="none", label=name.replace("_", " ") + " (Jung)")
        ax_twist.plot(br, np.degrees(bt), mk, mfc="none", label=name.replace("_", " ") + " (Jung)")
    ax_chord.plot(r_over_R, np.asarray(c_m) / (D_m / 2.0), "k-", label=label)
    ax_twist.plot(r_over_R, np.degrees(beta_rad), "k-", label=label)
    ax_chord.set_xlabel("r/R"); ax_chord.set_ylabel("c/R"); ax_chord.legend(fontsize=7)
    ax_twist.set_xlabel("r/R"); ax_twist.set_ylabel("twist (deg)")
