"""Rosella H4 12S model drawing with boom sizing values. Input: result JSON and geometry JSON. Output: SVG and PNG."""
import json
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle, Polygon, FancyArrowPatch
from matplotlib.gridspec import GridSpec

res = json.load(open(sys.argv[1]))
geo = json.load(open(sys.argv[2]))
out = sys.argv[3]
d, n, c = res["design"], res["names"], res["constraints"]
ro, t = d["r_boom"], d["t_boom"]
ri = ro - t
yb, a, dx = d["y_b"], d["a"], d["dx"]
xc, xf, xr, R, Lb = n["x_c"], n["x_f"], n["x_r"], n["R"], n["L_boom"]
over = (Lb - 2 * a) / 2
xcg, xnp = geo["x_cg"], geo["x_np"]


def mm(v):
    return f"{1000 * v:.1f} mm"


C_WING, C_BOOM, C_ROT, C_DIM, C_TXT = "#c9d3dd", "#1f5fa8", "#d9822b", "#555555", "#222222"
fig = plt.figure(figsize=(13, 12.5))
gs = GridSpec(2, 2, height_ratios=[2.7, 1.0], width_ratios=[1.35, 1], hspace=0.12, wspace=0.12, figure=fig)

# ------------------------------------------------------------------ A. plan view (nose up, right wing on the right)
ax = fig.add_subplot(gs[0, :])
ax.set_aspect("equal")
ax.axis("off")


def P(x, y):
    return (y, -x)


def dim(p0, p1, text, tp=None, ha="center", va="center", rot=0, fs=8.5, color=C_DIM):
    ax.add_patch(FancyArrowPatch(P(*p0), P(*p1), arrowstyle="<->", mutation_scale=7, lw=0.9, color=color, shrinkA=0, shrinkB=0, zorder=9))
    q = tp if tp is not None else ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    ax.text(*P(*q), text, ha=ha, va=va, rotation=rot, fontsize=fs, color=color, bbox=dict(fc="white", ec="none", pad=0.8, alpha=0.9), zorder=10)


def ext(p0, p1):
    ax.plot(*zip(P(*p0), P(*p1)), color="#bbb", lw=0.5, zorder=0)


for sgn in (1, -1):
    w = geo["wing"]
    pts = [P(s_["xyz_le"][0], sgn * s_["xyz_le"][1]) for s_ in w] + [P(s_["xyz_le"][0] + s_["chord"], sgn * s_["xyz_le"][1]) for s_ in reversed(w)]
    ax.add_patch(Polygon(pts, fc=C_WING, ec="#8a97a5", lw=0.8, zorder=1))
    h = geo["htail"]
    pts = [P(s_["xyz_le"][0], sgn * s_["xyz_le"][1]) for s_ in h] + [P(s_["xyz_le"][0] + s_["chord"], sgn * s_["xyz_le"][1]) for s_ in reversed(h)]
    ax.add_patch(Polygon(pts, fc=C_WING, ec="#8a97a5", lw=0.8, zorder=1))
fx = [f[0][0] for f in geo["fuselage"]]
fw = [max(p[1] for p in f) for f in geo["fuselage"]]
pts = [P(x, v) for x, v in zip(fx, fw)] + [P(x, -v) for x, v in zip(fx[::-1], fw[::-1])]
ax.add_patch(Polygon(pts, fc="#e8e8e8", ec="#777", lw=0.8, zorder=2))
tb = geo["tail_boom"]
ax.plot(*zip(P(tb[0][0][0], 0), P(tb[-1][0][0], 0)), color="#777", lw=3, zorder=2, solid_capstyle="butt")
ax.plot(*zip(P(0, -1.9), P(0, 1.9)), color="#999", lw=0.5, ls=":", zorder=0)
ax.text(*P(0.0, 1.9), "wing root LE: x = 0", fontsize=8, color="#666", ha="right", va="bottom")
for sgn in (1, -1):
    y = sgn * yb
    ax.plot(*zip(P(xc - a - over, y), P(xc + a + over, y)), color=C_BOOM, lw=5, solid_capstyle="butt", zorder=4)
    ax.add_patch(Rectangle((y - 0.012, -xc - 0.025), 0.024, 0.05, fc="#0d3a6e", ec="none", zorder=5))
    for x in (xf, xr):
        ax.add_patch(Circle(P(x, y), R, fc=C_ROT, alpha=0.16, ec=C_ROT, lw=1.1, zorder=3))
        ax.plot(*P(x, y), "o", color=C_ROT, ms=4, zorder=6)
ax.plot(*P(xcg, 0), marker="o", mfc="white", mec="k", ms=9, zorder=7)
ax.plot(*P(xcg, 0), marker="+", color="k", ms=9, zorder=7)
ax.text(*P(xcg - 0.07, 0.15), f"CG {mm(xcg)}", ha="left", va="center", fontsize=8.5, zorder=8)
ax.plot(*zip(P(xnp, -0.10), P(xnp, 0.10)), color="#2a9d4a", lw=1.2, zorder=7)
ax.text(*P(xnp + 0.07, 0.15), f"NP {mm(xnp)}", fontsize=8, color="#2a9d4a", ha="left", va="center", zorder=8)

# right boom: stacked dimension chain outside the rotor discs
yc = yb + R + 0.14
for x in (xc - a - over, xf, xc, xr, xc + a + over):
    ext((x, yb + 0.02), (x, yc + 0.18))
dim((xc - a - over, yc + 0.17), (xc + a + over, yc + 0.17), f"L_boom (cut) = {mm(Lb)}", tp=(xc, yc + 0.17 + 0.0), rot=90, fs=9.5, color=C_BOOM)
dim((xc - a - over, yc), (xf, yc), f"overhang {mm(over)}", tp=(xc - a - over / 2, yc + 0.3), ha="left", fs=8)
dim((xf, yc), (xc, yc), f"a = {mm(a)}", tp=(xf / 2 + xc / 2, yc), rot=90, fs=9, color=C_BOOM)
dim((xc, yc), (xr, yc), f"a = {mm(a)}", tp=(xc / 2 + xr / 2, yc), rot=90, fs=9, color=C_BOOM)
dim((xr, yc), (xc + a + over, yc), f"overhang {mm(over)}", tp=(xr + over / 2, yc + 0.3), ha="left", fs=8)
ax.text(*P(xf, yb + R + 0.04), "", fontsize=1)
# rotor diameters (right boom front, rear)
for x, nm in ((xf, "front"), (xr, "rear")):
    dim((x, yb - R), (x, yb + R), f"rotor D\n{mm(2 * R)}" + (" (26 in)" if nm == "front" else ""), tp=(x - 0.075, yb + 0.19), fs=8, color=C_ROT, rot=0)
# y_b on the left side
dim((xc + 0.18, 0), (xc + 0.18, -yb), f"y_b = {mm(yb)}", tp=(xc + 0.18 - 0.07, -yb / 2), fs=9.5, color=C_BOOM)
ext((xc + 0.2, 0.0), (xc + 0.2, -yb))
# dx and clamp x_c on the left boom
mid = 0.5 * (geo["wing_le"][1] + geo["wing_te"][1])
yd = -yb - R - 0.16
ext((mid, -yb + 0.02), (mid, yd - 0.04))
ext((xc, -yb - 0.02), (xc, yd - 0.04))
dim((mid, yd), (xc, yd), "", fs=9, color=C_BOOM)
ax.text(*P((mid + xc) / 2, yd - 0.04), f"dx = {mm(dx)}  (clamp x_c = {mm(xc)}\nfrom wing root mid-chord x = {mm(mid)})", fontsize=8.5, ha="right",
        va="center", color=C_BOOM, zorder=10)

te_y = geo["wing_te"][0] * yb + geo["wing_te"][1]
le_y = geo["wing_le"][0] * yb + geo["wing_le"][1]
g_te = c["clear_rear_to_wing_TE_m"]["value"]
g_le = c["clear_front_to_wing_LE_m"]["value"]
g_f = c["clear_fuselage_m"]["value"]
# gaps drawn on the left boom
dim((xf + R, -yb - 0.28), (le_y, -yb - 0.28), "", fs=1)
ax.annotate(f"rotor to wing LE: {mm(g_le)}", xy=P((xf + R + le_y) / 2, -yb - 0.28), xytext=P(-0.62, -1.55), fontsize=8, color=C_DIM,
            arrowprops=dict(arrowstyle="-", lw=0.6, color=C_DIM), ha="center", zorder=11)
dim((xr - R, -yb - 0.28), (te_y, -yb - 0.28), "", fs=1)
ax.annotate(f"rotor to wing TE: {mm(g_te)} (active)", xy=P((xr - R + te_y) / 2, -yb - 0.28), xytext=P(0.95, -1.55), fontsize=8, color=C_DIM,
            arrowprops=dict(arrowstyle="-", lw=0.6, color=C_DIM), ha="center", zorder=11)
dim((xf, -0.12), (xf, -yb + R), "", fs=1)
ax.annotate(f"rotor to fuselage: {mm(g_f)} (active)", xy=P(xf, -(0.12 + yb - R) / 2), xytext=P(-0.82, -0.18), fontsize=8, color=C_DIM,
            arrowprops=dict(arrowstyle="-", lw=0.6, color=C_DIM), ha="center", zorder=11)
ax.set_xlim(-1.95, 2.25)
ax.set_ylim(-1.62, 1.05)
ax.set_title(f"Rosella H4 12S: plan view of the lift booms (nose up, x aft down).   M = {n['M']:.2f} kg,   E = {res['energy_total_Wh']:.0f} Wh,   "
             f"level {res.get('level_reached', res.get('level'))}", fontsize=11, loc="left")

# ------------------------------------------------------------------ B. tube cross-section
bx = fig.add_subplot(gs[1, 0])
bx.set_aspect("equal")
bx.axis("off")
bx.set_xlim(-45, 115)
bx.set_ylim(-45, 40)
bx.add_patch(Circle((0, 0), ro * 1000, fc=C_BOOM, ec="k", lw=0.8))
bx.add_patch(Circle((0, 0), ri * 1000, fc="white", ec="k", lw=0.8))
bx.annotate("", xy=(-ro * 1000, -33), xytext=(ro * 1000, -33), arrowprops=dict(arrowstyle="<->", lw=0.9, color=C_DIM))
bx.text(0, -36, f"OD = {2000 * ro:.1f} mm", ha="center", va="top", fontsize=9.5, color=C_BOOM)
bx.plot([-ri * 1000, ri * 1000], [0, 0], color=C_DIM, lw=0.7, ls="--")
bx.text(0, 2, f"ID = {2000 * ri:.1f} mm", ha="center", va="bottom", fontsize=9, color=C_DIM)
bx.annotate(f"wall t = {1000 * t:.2f} mm\n(minimum, active bound)", xy=(ro * 1000 * 0.707, ro * 1000 * 0.707), xytext=(36, 36), fontsize=9,
            arrowprops=dict(arrowstyle="-", lw=0.7, color=C_DIM), color=C_BOOM, va="top")
bx.text(36, 12, "Material: roll-wrapped carbon tube\nE = 62.7 GPa,  rho = 1522 kg/m3 (unit not confirmed)\n"
        "allowable 359 MPa (compression)\nr_o / t = %.1f  (limit 60)\nmass of each boom = %.0f g" % (ro / t, 1000 * n["m_boom"] / 2),
        fontsize=8.5, va="top", color=C_TXT)
bx.set_title("Tube cross-section (to scale)", fontsize=10, loc="left")

# ------------------------------------------------------------------ C. cantilever and margins
cx = fig.add_subplot(gs[1, 1])
cx.axis("off")
cx.set_xlim(0, 10)
cx.set_ylim(0, 10)
cx.set_title("Cantilever model of one boom end and its margins", fontsize=10, loc="left")
cx.add_patch(Rectangle((0.2, 6.0), 0.5, 2.2, fc="#0d3a6e"))
cx.text(0.45, 8.5, "clamp", ha="center", fontsize=8)
cx.plot([0.7, 8.2], [7.1, 7.1], color=C_BOOM, lw=6, solid_capstyle="butt")
cx.add_patch(Circle((8.2, 7.1), 0.22, fc=C_ROT, ec="none"))
cx.add_patch(FancyArrowPatch((8.2, 7.1), (8.2, 9.4), arrowstyle="-|>", mutation_scale=12, lw=1.6, color=C_ROT))
cx.text(8.45, 9.25, f"T_max = {res['structure'][0]['F_N']:.0f} N", fontsize=9, color=C_ROT, va="top")
cx.add_patch(FancyArrowPatch((0.7, 5.5), (8.2, 5.5), arrowstyle="<->", mutation_scale=8, lw=0.9, color=C_DIM))
cx.text(4.45, 5.2, f"a = {mm(a)}", ha="center", va="top", fontsize=9, color=C_BOOM)
cx.text(0.2, 4.3, f"f1 = {res['f1_Hz']:.1f} Hz   (hover 1P {res['f_hover_1P_Hz']:.1f} Hz, needs f1 >= 1.2 x 1P) - active", fontsize=8.5, va="top")
rows = [("von Mises stress at T_max", c["boom_stress_Pa_front_T"]["value"] / 1e6, 359, "MPa", c["boom_stress_Pa_front_T"]["margin"]),
        ("local buckling at T_max", c["boom_buckling_Pa_front_T"]["value"] / 1e6, n["sigma_cr"] / 1e6, "MPa", c["boom_buckling_Pa_front_T"]["margin"]),
        ("tip slope at T_max", c["boom_tip_slope_deg_front_T"]["value"], 1.0, "deg", c["boom_tip_slope_deg_front_T"]["margin"]),
        ("stress at 3 g tip mass", c["boom_stress_Pa_front_g"]["value"] / 1e6, 359, "MPa", c["boom_stress_Pa_front_g"]["margin"])]
for i, (nm, v, lim, u, m) in enumerate(rows):
    cx.text(0.2, 3.5 - 0.72 * i, f"{nm}: {v:.3g} of {lim:.3g} {u}  (margin {100 * m:.0f} %)", fontsize=8.5, va="top")
cx.text(0.2, 0.1, "Safety factor 1.5 is inside the loads.", fontsize=8, va="bottom", color="#666")

fig.text(0.01, 0.005, "Source: work/aerosandbox/rosella/sizing/H4_12S.json (tools/aerosandbox/rosella.py). Wing and tail from aircraft/currawong. "
         "The values are optimiser outputs, not parts.", fontsize=7.5, color="#777")
fig.savefig(out + ".svg", bbox_inches="tight")
fig.savefig(out + ".png", dpi=120, bbox_inches="tight")
print("ok")
