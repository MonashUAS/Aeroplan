"""Validation of the AeroSandbox derivatives (FixedWingModel.stability, aeroplan/aerosandbox/model.py) against published data.

Two airplanes with published geometry and published derivatives. Every published number has its source in this file.
The specs hold only published numbers and measurements of published drawings. Each estimate is marked `ESTIMATE`.
The airplanes are manned light aircraft. No low-Reynolds UAV was found with BOTH a published tail geometry AND a table of
derivatives (the Ultra Stick / FASER papers give the wing only, and the derivatives only as plots or as dimensional matrices).

SOURCES (the files were read in full for the tables used)
  TEPER   G. L. Teper, "Aircraft Stability and Control Data", NASA CR-96008 (STI TR-176-1), April 1969, Section X Navion,
          Figure X-1 and Tables X-A, X-B, X-C (pages 100 and 101). Stability axes. A handbook compilation. The page does not
          state if the numbers come from flight, tunnel or estimate. Treat them as "handbook". https://ntrs.nasa.gov/citations/19690022405
  SM71    E. Seckel and J. J. Morris, "The Stability Derivatives of the Navion Aircraft Estimated by Various Methods and Derived
          from Flight Test Data", FAA-RD-71-6, Princeton University, January 1971. Table I (dimensions), Tables II and III
          (derivatives), Condition I. The "Flight Test" column is matched to flight transients (analog computer) with the
          accuracy that the report gives. The "Wind Tunnel" column is the full-scale Langley tunnel test (Princeton AMS Report
          922, 1970), with the propeller on. Read from the Scribd copy of the report (the DTIC copy gave HTTP 403).
          A cell that the report marks with an asterisk is not an independent flight result.
  TN5857  J. P. Shivers, M. P. Fink and G. M. Ware, "Full-Scale Wind-Tunnel Investigation of the Static Longitudinal and Lateral
          Characteristics of a Light Single-Engine Low-Wing Airplane" (the Navion), NASA TN D-5857, June 1970. Figure 2 (three view,
          principal dimensions) and the text on page 3. https://ntrs.nasa.gov/citations/19700022370
  SC79    W. T. Suit and R. L. Cannaday, "Comparison of Stability and Control Parameters for a Light, Single-Engine, High-Winged
          Aircraft Using Different Flight Test and Parameter Estimation Techniques", NASA TM-80163, September 1979. Table I,
          Figure 2 (three view), Table IV (longitudinal, 54.2 m/s, maximum likelihood) and Table X (lateral, maximum likelihood
          fitted to CL 0.3). Flight-test measurements. Body axes. The paper does not name the type. The three view is a
          Cessna-172-class airplane. https://ntrs.nasa.gov/citations/19800001985
  RITCHIE R. W. Ritchie, "Comparative Evaluation of Computational Techniques for Estimating UAV Aerodynamic, Stability and
          Control Derivatives", MS thesis, University of Minnesota, May 2013 (Chapter 4, Tables 4.3, 4.19 and 4.25). Used only
          for the accuracy of a vortex lattice on a 1.9 m UAV in a wind tunnel (FASER, Reynolds number 2e5): the lift slope
          of the vortex lattice was 12 to 13 percent below the tunnel value (Delta K1 0.119 to 0.135).

CONVENTIONS OF THE SOURCES (and the conversion to the convention of the model)
  The model gives per radian, stability axes at the trim alpha, moments about the CG of the spec, body rates p b/2V, q c/2V,
  r b/2V, de positive trailing edge down, da positive rolls right (each-side deflection), dr positive trailing edge left.
  TEPER: stability axes, per radian. Positive aileron gives positive rolling moment and positive rudder gives nose left,
    so Cn_dr is negative. Same signs as the model. The reference span of the aileron angle (each side or total) is not stated.
  SM71: stability axes, per radian. "Aileron deflection each side" (list of symbols). Rudder and elevator as TEPER.
    The static stability parameter of the flight column is Cm_a + CL_a Cm_q / (4 mu) with 4 mu = 4 m / (rho S c).
    The test uses 4 mu = 2 CL V^2 / (g c) (the published CL, V, c), which needs no mass and no density.
  SC79: BODY axes. CL_a is taken as -Cz_a (the error is below 1 percent at the small CD and alpha of the test). Aileron: the
    sign of "left minus right deflection" cannot be fixed from the text, so no aileron value is tested. The tail is
    all-moving (stabilator): the model uses a control surface with a hinge at 2 percent chord. Cm_q of the paper is
    identified with Cm_adot FIXED at -4.0 (Table IV note). So Cm_q of the paper is only valid together with that value.
    Cn_p and Cl_r are not tested: the difference between body and stability axes is about 30 percent of Cn_p at alpha 2 deg.

BASIS OF EACH PUBLISHED NUMBER (BASIS)
  "flight"   identified from flight transients.      "tunnel"    measured in a full-scale wind tunnel.
  "handbook" compiled data of unstated basis (TEPER).

TOLERANCE BANDS (BANDS). Written BEFORE the first run of the model against these data. They are not changed after a run.
  The check passes when |model - published| <= max(rel |published|, abs).
  Basis:
   - SM71 states that the textbook and DATCOM estimates for the Navion are "accurate to within the order of 20 percent with a few
     exceptions" and lists the spread: Cn_b 0.033 to 0.109 (flight 0.086), Cn_r -0.065 to -0.141 (flight -0.088), Cl_b -0.062 to
     -0.103 (flight -0.067), Cl_p -0.30 to -0.46 (flight -0.46), CY_b -0.20 to -0.77 (flight -0.61). A vortex lattice is not a
     DATCOM estimate, but it has no data on the fuselage, the interference or the sidewash, so the same spread is the fair
     expectation for the derivatives that the fin and the body decide.
   - SM71 conclusion 2: the textbook Cm_a differs from the flight value by 2 to 12 percent of the MAC in CG position. So the
     band of Cm_a is 6 percent MAC of CL_a: abs 0.06 CL_a (about 0.27 per rad).
   - RITCHIE: the vortex lattice lift slope was 12 to 13 percent low for a small UAV. So 15 percent for CL_a.
   - The control derivatives have no published accuracy for a vortex lattice. The bands are an engineering judgement: the
     camber bend of the lattice has no boundary layer or gap loss, so 25 to 30 percent. They are the weakest bands here.
  Absolute floors keep a small derivative from giving a band of zero width.
"""
import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path

try:
    import pytest
except ImportError:                                    # the AeroSandbox Python has no pytest
    pytest = None

from aeroplan.constants import FOOT_M, G0

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "aeroplan" / "aerosandbox"
HAS_ASB = importlib.util.find_spec("aerosandbox") is not None
CHECKS = {}
METHODS = ("combined", "aerobuildup")
#: (label, method, vortex lattice panels). "combined" at the default panels of the model and at 20 x 10: AeroSandbox 4.2.9 gives a
#: wrong lift (CL slope of 20 to 600) for a cambered wing with dihedral at some panel counts, among them the default 16 x 12.
VARIANTS = (("combined", "combined", None), ("combined_20x10", "combined", (20, 10)),
            ("combined_10x6", "combined", (10, 6)), ("aerobuildup", "aerobuildup", None))


def check(fn):
    CHECKS[fn.__name__] = fn
    return fn


# ============================================================================================================== bands
#: derivative -> (relative band, absolute floor). `None` as the floor of Cma means 0.06 CL_a of the published value.
BANDS = {
    "CLa": (0.15, 0.30),
    "Cma": (0.30, None),
    "Cmq": (0.35, 2.0),
    "CLde": (0.25, 0.05),
    "Cmde": (0.25, 0.25),
    "CYb": (0.40, 0.20),
    "Clb": (0.35, 0.02),
    "Clp": (0.20, 0.05),
    "Clr": (0.40, 0.04),
    "Cnb": (0.40, 0.03),
    "Cnp": (0.50, 0.04),
    "Cnr": (0.40, 0.04),
    "Clda": (0.30, 0.03),
    "Cnda": (0.0, 0.01),
    "Cldr": (0.0, 0.01),
    "Cndr": (0.35, 0.02),
    "CYdr": (0.35, 0.03),
    "Asp": (0.30, 0.30),                               # Cma + CLa Cmq / (4 mu), the static stability parameter of SM71
    # CL at the published alpha with the pitching moment trimmed to zero by the elevator (CL + CLde dde, dde = -Cm / Cmde).
    # Band written before the first run: 0.10 in CL = a 1.2 deg error of the zero-lift angle at CL slope 4.4 (the vortex lattice
    # has thin camber lines and no viscous loss, and AeroBuildup takes its sections from NeuralFoil).
    "CLtrim": (0.0, 0.10),
}


def band_of(name: str, pub: float, cla_pub: float) -> float:
    rel, floor = BANDS[name]
    if floor is None:
        floor = 0.06 * abs(cla_pub)
    return max(rel * abs(pub), floor)


# ============================================================================================================ the data
class Case:
    """One reference condition: where it comes from, the flight condition and the published derivatives.
    `pub` maps a derivative to (value, basis, tested)."""

    def __init__(self, key, title, spec_key, cg_pct_mac, v_m_s, h_m, alpha_deg, ref, pub, extra=None):
        self.key, self.title, self.spec_key, self.cg_pct_mac = key, title, spec_key, cg_pct_mac
        self.v_m_s, self.h_m, self.alpha_deg, self.ref, self.pub, self.extra = v_m_s, h_m, alpha_deg, ref, pub, extra or {}


# TEPER Section X, Tables X-A, X-B, X-C. CL 0.41, M 0.158, VT 176 ft/s, h 0, W 2750 lb, CG 29.5 % MAC, alpha0 0.6 deg.
# S 180 ft2 (Table X-A). The figure of the same page says 184 ft2: ESTIMATE (the table is used, it is also the S of TN5857).
TEPER = Case(
    "navion_teper", "Navion, TEPER (handbook), CG 29.5 % MAC", "navion", 29.5, 176.0 * FOOT_M, 0.0, 0.6,
    {"s_ft2": 180.0, "b_ft": 33.4, "c_ft": 5.7},
    {
        "CLtrim": (0.41, "handbook", True),                                    # Table X-B CL at alpha0 0.6 deg (level flight, trimmed)
        "CLa": (4.44, "handbook", True), "CLde": (0.355, "handbook", True), "Cma": (-0.683, "handbook", True),
        "Cmq": (-9.96, "handbook", True),
        "CYb": (-0.564, "handbook", True), "CYdr": (0.157, "handbook", True),
        "Clb": (-0.074, "handbook", True), "Clp": (-0.410, "handbook", True), "Clr": (0.107, "handbook", True),
        "Clda": (0.1342, "handbook", True), "Cldr": (0.0118, "handbook", True),
        "Cnb": (0.0701, "handbook", True), "Cnp": (-0.0575, "handbook", True), "Cnr": (-0.125, "handbook", True),
        "Cnda": (-0.00346, "handbook", True), "Cndr": (-0.0717, "handbook", True),
    })

# SM71 Condition I: flaps 0, 5000 ft density altitude, 240 ft/s TAS, CL 0.28, CG 25 % MAC (the tabulated derivatives).
# S 184 ft2, b 33.4 ft, c 5.7 ft (Table I). The alpha is not published: ESTIMATE from the TEPER trim, alpha = 0.6 deg +
# (0.28 - 0.41) / 4.44 rad = -1.1 deg.
SM71 = Case(
    "navion_sm71", "Navion, SM71 Condition I (flight test and tunnel), CG 25 % MAC", "navion", 25.0, 240.0 * FOOT_M, 5000.0 * FOOT_M, -1.1,
    {"s_ft2": 184.0, "b_ft": 33.4, "c_ft": 5.7},
    {
        "CLa": (4.52, "tunnel", True),                                         # Table III, wind tunnel column (flight: 6.04, with 75 % power)
        "CYb": (-0.61, "flight", True), "Clb": (-0.067, "flight", True), "Clr": (0.069, "flight", True),
        "Clp": (-0.46, "flight", True), "Cnb": (0.086, "flight", True), "Cnr": (-0.088, "flight", True),
        "Cnp": (-0.038, "flight", True),
        "Cmde": (-1.42, "flight", True),                                       # Table III: flight and tunnel give the same value
        "Clda": (0.152, "tunnel", True), "Cnda": (-0.0047, "tunnel", True),     # the flight column takes both from the tunnel
        "Cndr": (-0.075, "flight", True),                                      # the tunnel gives -0.077
        "Asp": (-1.55, "flight", True),                                        # Cm_a + CL_a Cm_q / (4 mu)
    }, extra={"cl_trim": 0.28})

# SC79 Table I, Table IV (54.2 m/s, trim power, maximum likelihood, two runs), Table X (CL 0.3). CG 28.8 % MAC (page 5).
# Test altitude 600 to 1500 m (page 6): 1000 m is an ESTIMATE. The alpha is not published: 2 deg is an ESTIMATE.
SC79 = Case(
    "highwing_sc79", "High-wing four-seat airplane, SC79 (flight test), CG 28.8 % MAC", "highwing", 28.8, 54.2, 1000.0, 2.0,
    {"s_m2": 16.2, "b_m": 11.0, "c_m": 1.49},
    {
        "CLa": (5.2, "flight", True),                                          # -Cz_a: 5.18 and 5.27 (two runs), mean rounded to 0.1
        "Cma": (-0.68, "flight", True), "Cmq": (-15.3, "flight", True),         # Cm_adot fixed at -4.0
        "CLde": (0.40, "flight", True),                                        # -Cz_de: 0.405 and 0.398
        "Cmde": (-1.18, "flight", True),                                       # -1.19 and -1.17 (stabilator)
        "CYb": (-0.59, "flight", False), "Clb": (-0.078, "flight", True), "Clp": (-0.47, "flight", True),
        "Cnb": (0.048, "flight", False), "Cnr": (-0.10, "flight", False),       # fin geometry: see highwing_geometry
        "Clr": (0.07, "flight", False), "Cnp": (-0.05, "flight", False),        # body axes
    })

CASES = (TEPER, SM71, SC79)


# =========================================================================================================== geometry
def _foil(name: str):
    import aerosandbox as asb
    return asb.Airfoil(name).coordinates.tolist()


def _blend(a: str, b: str, f: float, tag: str):
    import aerosandbox as asb
    return asb.Airfoil(a).blend_with_another_airfoil(asb.Airfoil(b), blend_fraction=f).coordinates.tolist(), tag


def _lerp(y, y0, y1, v0, v1):
    return v0 + (v1 - v0) * (y - y0) / (y1 - y0)


def _frames(stations, unit):
    """Fuselage frames: (x, width, height, z centre) -> four points that give the width, the height and the centre."""
    out = []
    for x, w, h, zc in stations:
        x, w, h, zc = (v * unit for v in (x, w, h, zc))
        out.append([[x, 0.5 * w, zc], [x, -0.5 * w, zc], [x, 0.0, zc + 0.5 * h], [x, 0.0, zc - 0.5 * h]])
    return out


def navion_geometry(cg_pct_mac: float):
    """The Navion in the AeroSandbox frame (x aft from the nose, y right, z up, z 0 at the CG height), in metres.

    PUBLISHED (TN5857 Figure 2 and text): b 33.38 ft, S 180 ft2, MAC 5.67 ft, taper 0.53, dihedral 7.5 deg, wing incidence 2 deg
    at the root and twist -3 deg (tip incidence -1 deg, SM71 Table I), airfoils NACA 4415 (root) and NACA 6410 (tip) (the "R" of the
    report is dropped), tip chord 3.90 ft, htail span 13.16 ft, htail area 28.8 + 14.1 ft2, elevator 14.1 ft2, fin 10.8 + 6.8 ft2,
    rudder 6.8 ft2, aileron 5.0 ft2 each, MAC LE and CG at 25 % MAC (drawing).
    MEASURED on the 300 dpi image of Figure 2 (scale 46.05 px/ft from the span, +-0.1 ft): the root chord 7.11 ft, the wing LE sweep
    2.99 deg (SM71 gives 2 deg 59 min 46 s), the x of the LE, the aileron span station (11.0 to 16.1 ft), the tail x, the fin
    planform and the fuselage stations. ESTIMATE (not published): the fuselage widths and heights, the z of the wing (0.9 ft below
    the CG), the z of the htail (1.2 ft above the CG), the fin root chord (fixed by the published fin area), the fin offset
    of 2 deg (not modelled), htail incidence 0 (TN5857: normal 0 deg, SM71 lists -3 deg), the hinge of the aileron (from its area)."""
    ft = FOOT_M
    half_b = 33.38 / 2.0
    le0, le1, c0, c1 = 5.23, 6.08, 7.11, 3.89                  # ft: LE x and chord at the centreline and at the tip
    z0, dih = -0.89, math.radians(7.5)
    ail = (10.97, 16.07)                                       # ft, the span of the aileron
    ys = [0.0, ail[0], ail[1], half_b]
    foils, secs = {}, []
    for y in ys:
        f = y / half_b
        coords, tag = _blend("naca4415", "naca6410", f, f"navion_wing_{y:.2f}")
        foils[tag] = coords
        sec = {"xyz_le": [_lerp(y, 0, half_b, le0, le1) * ft, y * ft, (z0 + y * math.tan(dih)) * ft],
               "chord": _lerp(y, 0, half_b, c0, c1) * ft, "twist_deg": _lerp(y, 0, half_b, 2.0, -1.0), "foil": tag, "controls": []}
        secs.append(sec)
    # the aileron: 5.0 ft2 on a span of 5.1 ft, the mean chord there 4.4 ft
    ail_chord = 5.0 / (ail[1] - ail[0])
    mid_chord = _lerp(0.5 * (ail[0] + ail[1]), 0, half_b, c0, c1)
    secs[1]["controls"] = [{"name": "aileron", "symmetric": False, "hinge_x_over_c": 1.0 - ail_chord / mid_chord}]
    wing = {"name": "wing", "mirror": True, "sections": secs, "foils": foils}

    ht = {"name": "htail", "mirror": True, "foils": {"naca0012": _foil("naca0012")}, "sections": [
        {"xyz_le": [21.42 * ft, 0.0, 1.2 * ft], "chord": 3.92 * ft, "twist_deg": 0.0, "foil": "naca0012",
         "controls": [{"name": "elevator", "symmetric": True, "hinge_x_over_c": 1.0 - 14.1 / 42.9}]},
        {"xyz_le": [22.31 * ft, 13.16 / 2 * ft, 1.2 * ft], "chord": 2.60 * ft, "twist_deg": 0.0, "foil": "naca0012", "controls": []}]}
    fin_area, fin_tip_chord, fin_h = 10.8 + 6.8, 2.32, 5.32 - 0.65
    fin_root = 2.0 * fin_area / fin_h - fin_tip_chord
    fin = {"name": "fin", "mirror": False, "foils": {"naca0012": _foil("naca0012")}, "sections": [
        {"xyz_le": [26.72 * ft - fin_root * ft, 0.0, 0.65 * ft], "chord": fin_root * ft, "twist_deg": 0.0, "foil": "naca0012",
         "controls": [{"name": "rudder", "symmetric": True, "hinge_x_over_c": 1.0 - 6.8 / fin_area}]},
        {"xyz_le": [24.37 * ft, 0.0, 5.32 * ft], "chord": fin_tip_chord * ft, "twist_deg": 0.0, "foil": "naca0012", "controls": []}]}
    # (x from the nose [ft], width, height, z centre above the CG): ESTIMATE from the side and top views of Figure 2
    stations = [(0.0, 2.7, 2.4, 0.2), (2.0, 3.5, 2.9, 0.3), (5.0, 3.9, 3.8, 0.4), (7.5, 3.8, 4.6, 0.8), (10.5, 3.9, 3.9, 0.25),
                (14.0, 3.3, 3.5, 0.35), (18.0, 1.9, 2.5, 0.4), (22.0, 1.2, 2.1, 0.45), (26.5, 0.4, 1.2, 0.5), (27.3, 0.05, 0.1, 0.5)]
    mac_le = 5.69                                              # ft, drawing; MAC 5.67 ft
    cg_x = (mac_le + cg_pct_mac / 100.0 * 5.67) * ft
    return {"surfaces": [wing, ht, fin], "fuselages": [{"name": "fuselage", "frames": _frames(stations, ft)}],
            "cg": [cg_x, 0.0, 0.0], "hub": [0.0, 0.0, 0.3 * ft], "diameter_m": 6.84 * ft}


def highwing_geometry(cg_pct_mac: float):
    """The airplane of SC79 in metres (x aft from the wing root LE, y right, z up, z 0 at the CG height).

    PUBLISHED (SC79 Table I and Figure 2): S 16.2 m2, b 11.0 m (the figure gives 10.91 m), MAC 1.49 m, root chord 1.63 m, tip chord 1.13 m,
    htail span 3.45 m, root chord 1.25 m, tip chord 0.81 m, LE sweep offset 0.26 m, the tail length 4.36 m (CG to the htail), fuselage
    length 8.17 m, CG 0.43 m behind the root LE (28.8 % MAC).
    MEASURED on Figure 2 (scale 68.7 px/m): the straight inboard panel to y = 2.55 m, the tip LE 0.38 m aft of the root LE, the wing
    z (0.85 m above the CG), the dihedral 1.3 deg (front view), the fuselage stations, the fin planform (root chord 1.7 m, tip chord
    0.66 m, height 1.4 m, a trapezoid of 1.65 m2 against the 1.04 m2 of Table I: the table and the drawing do not agree).
    ESTIMATE (not published): the airfoils (NACA 2412 wing, NACA 0012 tails), the wing incidence (0), the twist (0), the aileron
    (y 3.3 to 5.0 m, hinge 0.75 c), the rudder hinge (0.6 c), the strut (not modelled), the fuselage widths. The fin derivatives
    (CY_b, Cn_b, Cn_r) are not tested because of the conflict of the fin area."""
    half_b = 10.91 / 2.0
    y_in = 2.55
    foils = {"naca2412": _foil("naca2412")}
    dih = math.radians(1.3)
    z0 = 0.85

    def wsec(y, ctrl=None):
        le = 0.0 if y <= y_in else _lerp(y, y_in, half_b, 0.0, 0.38)
        ch = 1.63 if y <= y_in else _lerp(y, y_in, half_b, 1.63, 1.13)
        return {"xyz_le": [le, y, z0 + y * math.tan(dih)], "chord": ch, "twist_deg": 0.0, "foil": "naca2412", "controls": ctrl or []}

    secs = [wsec(0.0), wsec(y_in), wsec(3.3, [{"name": "aileron", "symmetric": False, "hinge_x_over_c": 0.75}]), wsec(5.0), wsec(half_b)]
    wing = {"name": "wing", "mirror": True, "sections": secs, "foils": foils}
    cg_x = 0.43 * (cg_pct_mac / 28.8)
    # the htail: the MAC quarter chord is 4.36 m behind the CG
    cr, ct, bt, sw = 1.25, 0.81, 3.45, 0.26
    lam = ct / cr
    mac_t = 2.0 / 3.0 * cr * (1 + lam + lam ** 2) / (1 + lam)
    y_mac = bt / 6.0 * (1 + 2 * lam) / (1 + lam)
    x_root = cg_x + 4.36 - (sw * y_mac / (0.5 * bt) + 0.25 * mac_t)
    ht = {"name": "htail", "mirror": True, "foils": {"naca0012": _foil("naca0012")}, "sections": [
        {"xyz_le": [x_root, 0.0, 0.0], "chord": cr, "twist_deg": 0.0, "foil": "naca0012",
         "controls": [{"name": "elevator", "symmetric": True, "hinge_x_over_c": 0.02}]},
        {"xyz_le": [x_root + sw, 0.5 * bt, 0.0], "chord": ct, "twist_deg": 0.0, "foil": "naca0012", "controls": []}]}
    x_fin_te = cg_x + 5.97                                     # the tail end: 8.17 m long, the nose 2.2 m ahead of the CG
    fin = {"name": "fin", "mirror": False, "foils": {"naca0012": _foil("naca0012")}, "sections": [
        {"xyz_le": [x_fin_te - 1.7, 0.0, 0.0], "chord": 1.7, "twist_deg": 0.0, "foil": "naca0012",
         "controls": [{"name": "rudder", "symmetric": True, "hinge_x_over_c": 0.6}]},
        {"xyz_le": [x_fin_te - 0.66 - 0.1, 0.0, 1.4], "chord": 0.66, "twist_deg": 0.0, "foil": "naca0012", "controls": []}]}
    # (x from the CG [m], width, height, z centre): ESTIMATE from the side view of Figure 2 (nose 2.2 m ahead of the CG)
    stations = [(-2.2, 0.5, 0.7, -0.15), (-1.6, 1.0, 1.0, -0.1), (-0.8, 1.1, 1.5, 0.0), (0.4, 1.1, 1.6, 0.05), (1.5, 0.9, 1.3, 0.0),
                (3.0, 0.6, 0.9, 0.0), (4.5, 0.35, 0.55, 0.0), (5.9, 0.1, 0.25, 0.0)]
    frames = _frames([(x + cg_x, w, h, zc) for x, w, h, zc in stations], 1.0)
    return {"surfaces": [wing, ht, fin], "fuselages": [{"name": "fuselage", "frames": frames}],
            "cg": [cg_x, 0.0, 0.0], "hub": [cg_x - 2.2, 0.0, 0.0], "diameter_m": 1.9}


def build_spec(case: Case):
    """The spec of the fixed-wing jobs (the form of aeroplan.aerosandbox.spoke.spec_from_doc) for one case."""
    if case.spec_key == "navion":
        g = navion_geometry(case.cg_pct_mac)
        r = case.ref
        ref = {"s_m2": r["s_ft2"] * FOOT_M ** 2, "b_m": r["b_ft"] * FOOT_M, "c_m": r["c_ft"] * FOOT_M}
    else:
        g = highwing_geometry(case.cg_pct_mac)
        ref = dict(case.ref)
    ref["xyz_ref"] = g["cg"]
    return {"name": case.key, "reference": ref, "surfaces": g["surfaces"], "fuselages": g["fuselages"],
            "mass": {"mass_kg": 1.0, "cg": g["cg"]},
            "propulsion": {"hub": g["hub"], "thrust_axis": [-1.0, 0.0, 0.0], "diameter_m": g["diameter_m"]},
            "flight": {"speed_m_s": case.v_m_s, "altitude_m": case.h_m}}


# ============================================================================================================== runs
_CACHE = {}


def run_case(case: Case, method: str, panels=None):
    key = (case.key, method, panels)
    if key not in _CACHE:
        _CACHE[key] = _run_case(case, method, panels)
    return dict(_CACHE[key])


def _run_case(case: Case, method: str, panels=None):
    """The derivatives of the model for one case and method (in this Python: it has aerosandbox). `panels` is (spanwise,
    chordwise) of the vortex lattice, or None for the default of the model. The anchors CL0 (CL - CLa alpha), Cm0 and CLtrim
    (CL at the case alpha with the moment trimmed by the elevator) are added to the derivatives."""
    from aeroplan.aerosandbox import model
    kw = {} if panels is None else {"spanwise": panels[0], "chordwise": panels[1]}
    out = model.FixedWingModel(case.key, build_spec(case)).stability(case.alpha_deg, 0.0, method, **kw)["stability"]
    d = dict(out["derivatives"])
    a = math.radians(case.alpha_deg)
    d["CL"], d["Cm"] = out["CL"], out["Cm"]
    d["CL0"], d["Cm0"] = out["CL"] - d["CLa"] * a, out["Cm"] - d["Cma"] * a
    d["CLtrim"] = out["CL"] - out["Cm"] / d["Cmde"] * d["CLde"]
    if case.key == "navion_sm71":                                # the static stability parameter of SM71
        four_mu = 2.0 * case.extra["cl_trim"] * case.v_m_s ** 2 / (G0 * case.ref["c_ft"] * FOOT_M)
        d["Asp"] = d["Cma"] + d["CLa"] * d["Cmq"] / four_mu
    return d


def compare(case: Case, method: str, panels=None):
    """Rows (name, published, model, percent difference, band, tested, ok)."""
    d = run_case(case, method, panels)
    cla_pub = case.pub["CLa"][0] if "CLa" in case.pub else d["CLa"]
    rows = []
    for name, (pub, basis, tested) in case.pub.items():
        got = d[name]
        band = band_of(name, pub, cla_pub)
        rows.append((name, pub, got, 100.0 * (got - pub) / abs(pub), band, basis, tested, abs(got - pub) <= band))
    return rows


def anchors(case: Case, method: str, panels=None):
    """CL0, Cm0 and CL at the trim of the model (no published value for CL0 and Cm0 in any source): for the report."""
    d = run_case(case, method, panels)
    return {k: d[k] for k in ("CL", "Cm", "CL0", "Cm0", "CLtrim")}


def failures(case: Case, method: str):
    return [r for r in compare(case, method) if r[6] and not r[7]]


def table(case: Case, method: str, rows) -> str:
    L = [f"{case.title} / {method}", f"{'derivative':10s} {'published':>10s} {'model':>10s} {'diff %':>8s} {'band':>7s}  basis      verdict"]
    for n, pub, got, pct, band, basis, tested, ok in rows:
        verdict = ("ok" if ok else "FAIL") if tested else ("(in band)" if ok else "(out, not tested)")
        L.append(f"{n:10s} {pub:10.4f} {got:10.4f} {pct:8.1f} {band:7.3f}  {basis:9s}  {verdict}")
    return "\n".join(L)


# ============================================================================================================= checks
def _make_check(case: Case, label: str, method: str, panels):
    def fn():
        rows = compare(case, method, panels)
        bad = [r for r in rows if r[6] and not r[7]]
        assert not bad, "outside the band:\n" + table(case, label, rows)
    fn.__name__ = f"check_{case.key}_{label}"
    return check(fn)


for _c in CASES:
    for _label, _m, _p in VARIANTS:
        _make_check(_c, _label, _m, _p)


@check
def check_the_two_methods_agree_on_the_signs_of_the_main_derivatives():
    """The sign of the main derivatives is known from physics: CLa, CLde > 0, Cma, Cmq, Cmde < 0, Clb < 0, Clp < 0, Cnb > 0, Cnr < 0.
    This holds for each case and each method, so a sign error in the conventions of the model shows here and not as a band."""
    for case in CASES:
        for _label, method, panels in VARIANTS[1:]:
            d = run_case(case, method, panels)
            for name, sign in (("CLa", 1), ("CLde", 1), ("Cma", -1), ("Cmq", -1), ("Cmde", -1), ("Clb", -1), ("Clp", -1)):
                assert d[name] * sign > 0.0, f"{case.key} {method}: {name} = {d[name]}"
            if case.spec_key == "navion":
                for name, sign in (("Cnb", 1), ("Cnr", -1), ("Cndr", -1), ("CYdr", 1), ("Clda", 1)):
                    assert d[name] * sign > 0.0, f"{case.key} {method}: {name} = {d[name]}"


# ====================================================================================================== pytest hooks
def run_check(name):
    # Opt-in: the file takes about 15 minutes, and its bands report known gaps of the methods (CLde, Cmde, CYb, Cnb).
    # Run it with AEROPLAN_VALIDATION=1 after a change of FixedWingModel.stability or vlm. A failed row is a finding, not a
    # reason to widen a band.
    if os.environ.get("AEROPLAN_VALIDATION") != "1":
        pytest.skip("validation against published data: set AEROPLAN_VALIDATION=1 (about 15 minutes)")
    if HAS_ASB:
        CHECKS[name]()
        return
    sys.path.insert(0, str(HERE))
    from aeroplan.spokes import load
    spoke = load("AeroSandbox")
    if not spoke.available():
        pytest.skip("no AeroSandbox here: run `pip install -e .[sizing]`")
    p = subprocess.run([str(spoke.python()), "-E", "-s", str(Path(__file__).resolve()), name], capture_output=True, text=True, cwd=str(TOOL))
    assert p.returncode == 0, (p.stdout + p.stderr)[-4000:]


if pytest is not None:
    def _make(name):
        def test():
            run_check(name)
        test.__name__ = "test_" + name[len("check_"):]
        return test

    for _name in list(CHECKS):
        globals()["test_" + _name[len("check_"):]] = _make(_name)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["report"]:                                  # every comparison, as a table (for the report)
        out = {}
        for case in CASES:
            for label, method, panels in VARIANTS:
                rows = compare(case, method, panels)
                print(table(case, label, rows), flush=True)
                print("anchors:", {k: round(v, 4) for k, v in anchors(case, method, panels).items()}, "\n", flush=True)
                out[f"{case.key}/{label}"] = [{"name": r[0], "published": r[1], "model": r[2], "diff_pct": r[3], "band": r[4],
                                                "basis": r[5], "tested": r[6], "ok": bool(r[7])} for r in rows]
        if args[1:]:
            Path(args[1]).write_text(json.dumps(out, indent=1), encoding="utf-8")
        sys.exit(0)
    failed = 0
    for nm in args or list(CHECKS):
        try:
            CHECKS[nm]()
            print("ok  ", nm)
        except Exception as e:                                  # print every failure, then exit with 1
            failed += 1
            print("FAIL", nm, type(e).__name__, e)
    sys.exit(1 if failed else 0)
