"""
Plots of a model, a `Result` or a `Snapshot`. Nothing here calls the solver: the plotter only reads numbers.

Static plots (matplotlib, so a notebook shows them on GitHub):
    view_3d(model, design)        the AeroSandbox 3D view with the lift booms and the rotor discs
    three_view(model, design)     AeroSandbox three-view with the rotor discs added
    weight_chart(result)          one stacked bar of the take-off mass, by system and item
    energy_chart(result)          one stacked bar of the mission energy by segment, with the usable and nominal battery energy
    fit_chart(model, result)      the motor and ESC mass fits against the maker rows, with the design point
    margin_chart(result)          the limits with the smallest margin, and what one more unit of each costs
    frequency_chart(result)       boom modes f1, f2 against the rotor speed lines (1P, 2P) and the hover band
    ladder_chart(run)             mass and energy at each level of the ladder

Interactive (plotly):
    scene_figure(model, design)   the 3D view as a plotly figure
    LiveView(model, design)       a FigureWidget that redraws the booms and rotors for each `Snapshot` of the solver, with the
                                  energy and the violation against the iteration (needs anywidget, in the notebook packages)

Colours: the categorical palette of the data-visualisation method (blue, orange, aqua, yellow ...), one hue for magnitude,
red for a violated limit.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np

BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300",
                                                         "#6250d6", "#e34948")
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def style():
    """The matplotlib style of these plots: light surface, thin marks, a recessive grid, ink text."""
    import matplotlib as mpl
    mpl.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE, "axes.edgecolor": MUTED,
        "axes.labelcolor": INK, "text.color": INK, "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
        "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
        "axes.axisbelow": True, "font.size": 9.5, "axes.titlesize": 10.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "lines.linewidth": 2.0, "figure.dpi": 110, "legend.frameon": False})


# ================================================================================================== the 3D view and three-view
def view_3d(model, design: Dict[str, float], elev: float = 24.0, azim: float = -58.0, size=(7.0, 5.2)):
    """The AeroSandbox 3D view (matplotlib) of the design, with the lift booms and the rotor discs. Returns the figure."""
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    style()
    plane = model.airplane(design)
    plane.draw(backend="matplotlib", show=False, set_axis_visibility=False)      # draw makes its own figure
    plt.gcf().set_size_inches(*size)
    ax = plt.gcf().axes[0]
    for d in model.rotor_discs(design):
        ax.add_collection(Poly3DCollection([d["rim"]], facecolors=ORANGE, edgecolors=ORANGE, alpha=0.35, linewidths=0.8, zorder=4))
    ax.view_init(elev=elev, azim=azim)
    ax.set_title(f"{model.name}: {model.layout} lift rotors, D {2000.0 * model.geometry(design)['R']:.0f} mm")
    return plt.gcf()


def three_view(model, design: Dict[str, float], size=(8.0, 8.0)):
    """The AeroSandbox three-view with the rotor discs added to the side, front and top views. Returns the figure."""
    import matplotlib.pyplot as plt
    style()
    plane = model.airplane(design)
    plane.draw_three_view(show=False)
    fig = plt.gcf()
    fig.set_size_inches(*size)
    ax = fig.axes
    side, front, top = ax[0], ax[1], ax[2]
    for d in model.rotor_discs(design):
        r = np.vstack([d["rim"], d["rim"][:1]])
        side.plot(r[:, 0], r[:, 2], color=ORANGE, lw=1.4)
        front.plot(r[:, 1], r[:, 2], color=ORANGE, lw=1.4)
        top.plot(r[:, 0], r[:, 1], color=ORANGE, lw=1.4)
    return fig


# ==================================================================================================== charts of a Result
# Item name -> system, for the stacked weight chart. An item that is not listed goes to "Other". The lift_* parts come from the
# split of lift_front and lift_rear (see _lift_parts). An older result with no m_mount keeps the two items.
WEIGHT_GROUPS = (
    ("Airframe", ("wing", "tail", "tail_boom", "fuselage", "landing_gear")),
    ("VTOL propulsion", ("lift_motor", "lift_esc", "lift_prop", "lift_mount", "lift_front", "lift_rear", "boom", "boom_clamp",
                         "cables")),
    ("Cruise propulsion", ("cruise_motor", "cruise_esc", "cruise_prop", "cruise_rest")),
    ("Battery", ("battery",)),
    ("Flight avionics", ("avionics_flight",)),
    ("Avionics projects", ("avionics_projects",)),
    ("Payload, released at the deployment", ("payload_cargo",)),
)

# Mission segment -> group, for the stacked energy chart.
ENERGY_GROUPS = (
    ("VTOL", ("vtol_takeoff_climb", "transitions", "deploy_hover", "landing")),
    ("Cruise", ("fw_climb", "transit_laps_rtl", "survey")),
    ("Reserve hover", ("reserve",)),
)

STACK_COLORS = (BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, MUTED)


def _grouped(values: Dict[str, float], groups):
    """[(group, [(item, value), ...]), ...] in the order of `groups`, plus "Other" for the items that no group lists. Empty
    groups are left out."""
    listed = {k for _, ks in groups for k in ks}
    rows = [(g, [(k, values[k]) for k in ks if k in values]) for g, ks in groups]
    rows.append(("Other", [(k, v) for k, v in values.items() if k not in listed]))
    return [(g, items) for g, items in rows if items]


def _stack(ax, rows, unit: str, fmt: str = "{:.2f}"):
    """One stacked bar at x = 0. Each group is one colour, split by thin lines into its items. The labels on the right give the
    group value, its share and the items. The labels move apart so that they do not overlap, with a leader line to the
    segment. Returns the total."""
    total = sum(v for _, items in rows for _, v in items)
    bottom, seg = 0.0, []
    for (g, items), col in zip(rows, STACK_COLORS):
        top = bottom
        for _, v in items:
            ax.bar(0, v, bottom=top, width=0.5, color=col, edgecolor=SURFACE, linewidth=1.2)
            top += v
        seg.append((g, items, top - bottom, 0.5 * (bottom + top)))
        bottom = top
    gap = 0.065 * total                                     # the least distance of two labels, so that they do not overlap
    ys = [m for *_, m in seg]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + gap)
    ys[-1] = min(ys[-1], total * 0.985)
    for i in range(len(ys) - 2, -1, -1):
        ys[i] = min(ys[i], ys[i + 1] - gap)
    for (g, items, m, mid), y in zip(seg, ys):
        ax.plot([0.25, 0.3, 0.33], [mid, y, y], color=MUTED, lw=0.7)
        ax.text(0.35, y + 0.012 * total, f"{g}  {fmt.format(m)} {unit} ({100 * m / total:.0f} %)", va="center", ha="left",
                color=INK, fontsize=9)
        ax.text(0.35, y - 0.016 * total, ", ".join(f"{k.replace('_', ' ')} {fmt.format(v)}" for k, v in items), va="center",
                ha="left", color=MUTED, fontsize=7.5)
    ax.set_xlim(-0.35, 1.75)
    ax.set_xticks([])
    ax.grid(axis="x", visible=False)
    ax.spines["bottom"].set_visible(False)
    return total


def _lift_parts(result, by_item: Dict[str, float]) -> Dict[str, float]:
    """Split the lift_front and lift_rear items into motors, ESCs, props and mounts (the unit masses of the result names times
    the number of rotors). The parts must add up to the two items."""
    n = result["names"]
    if "m_mount" not in n or "lift_front" not in by_item:
        return by_item
    unit = {"lift_motor": n["m_motor"], "lift_esc": n["m_esc"], "lift_prop": n["m_prop"], "lift_mount": n["m_mount"]}
    n_rot = (by_item["lift_front"] + by_item["lift_rear"]) / sum(unit.values())
    assert abs(n_rot - round(n_rot)) < 1e-6, f"the lift items are not a whole number of rotor units ({n_rot})"
    out = {k: v for k, v in by_item.items() if k not in ("lift_front", "lift_rear")}
    out.update({k: round(n_rot) * v for k, v in unit.items()})
    return out


def weight_chart(result, size=(7.0, 5.4), groups=WEIGHT_GROUPS):
    """One stacked bar of the take-off mass (kg). Each segment is a system (WEIGHT_GROUPS) and is split by thin lines into its
    items. The labels give the mass and the share of the total."""
    import matplotlib.pyplot as plt
    style()
    fig, ax = plt.subplots(figsize=size)
    total = _stack(ax, _grouped(_lift_parts(result, result.mass_by_item()), groups), "kg")
    ax.set_ylim(0, total * 1.02)
    ax.set_ylabel("mass [kg]")
    ax.set_title(f"Weight breakdown, take-off mass {total:.2f} kg")
    fig.tight_layout()
    return fig


def energy_chart(result, size=(7.0, 4.6), groups=ENERGY_GROUPS):
    """One stacked bar of the mission energy (Wh), by segment (ENERGY_GROUPS), with the usable and the nominal battery energy
    as lines."""
    import matplotlib.pyplot as plt
    style()
    fig, ax = plt.subplots(figsize=size)
    total = _stack(ax, _grouped(result.energy_by_segment(), groups), "Wh", "{:.1f}")
    nominal = result["energy_nominal_Wh"]
    usable = (result["constraints"].get("energy_Wh") or {}).get("hi")
    for y, txt, ls in ((usable, "usable", "--"), (nominal, "nominal", ":")):
        if y is not None:
            ax.plot([-0.33, 0.25], [y, y], color=INK, lw=1.0, ls=ls)
            ax.text(-0.33, y, f"{txt} {y:.0f} Wh", va="bottom", ha="left", color=INK, fontsize=8)
    ax.set_ylim(0, max(total, nominal) * 1.08)
    ax.set_ylabel("energy [Wh]")
    share = f", {100 * total / usable:.0f} % of usable" if usable else ""
    ax.set_title(f"Mission energy {total:.1f} Wh{share}")
    fig.tight_layout()
    return fig


def fit_chart(model, result, size=(10.0, 4.0)):
    """The motor and ESC mass fits against the maker rows. Left: motor mass against q_cap (data/motor_survey.csv). Right: ESC
    mass against the continuous current (data/esc_survey.csv), with AIAA 2016-0581 Eq. 2 for comparison. The diamond is the
    design."""
    import matplotlib.pyplot as plt
    from component import esc_model, motor_model
    style()
    mm = motor_model(model.c["motor"])
    esc, cells = model.c["esc"], int(model.c["battery"]["cells_s"])
    em = esc_model(esc, cells)
    n, d = result["names"], result.design
    fig, (a1, a2) = plt.subplots(1, 2, figsize=size)
    q = np.linspace(0.8 * mm.q_cap.min(), 1.05 * mm.q_cap.max(), 60)
    a1.plot(mm.q_cap, mm.m_g, "o", color=BLUE, ms=4, alpha=0.75, label=f"maker rows ({mm.n})")
    a1.plot(q, np.exp(mm.mass_fit[0]) * q ** mm.mass_fit[1], color=INK, lw=1.4,
            label=f"fit {np.exp(mm.mass_fit[0]):.0f} q^{mm.mass_fit[1]:.2f} g (log RMS {mm.mass_rms:.2f})")
    a1.plot([d["q_cap"]], [1000.0 * n["m_motor"]], "D", color=ORANGE, ms=7, label=f"design {1000.0 * n['m_motor']:.0f} g")
    a1.set_xlabel("q_cap: torque for the 180 s peak current [N m]")
    a1.set_ylabel("motor mass [g]")
    a1.set_title("Lift motor mass")
    a1.legend(fontsize=8, loc="upper left")
    i = np.linspace(1.0, 1.05 * em.i_A.max(), 60)
    a2.plot(em.i_A, em.m_g, "o", color=BLUE, ms=4, alpha=0.75, label=f"maker rows ({em.n})")
    a2.plot(i, np.exp(em.fit[0]) * i ** em.fit[1], color=INK, lw=1.4,
            label=f"fit {np.exp(em.fit[0]):.2f} I^{em.fit[1]:.2f} g (log RMS {em.rms:.2f})")
    a2.plot(i, 0.8421 * i, color=MUTED, lw=1.0, ls="--", label="AIAA 2016-0581 Eq. 2 (0.84 g/A)")
    i_d = esc.num("peak_factor") * n["I_pk"]
    a2.plot([i_d], [1000.0 * n["m_esc"]], "D", color=ORANGE, ms=7, label=f"design {1000.0 * n['m_esc']:.0f} g at {i_d:.0f} A")
    a2.set_xlabel("ESC continuous current [A]")
    a2.set_ylabel("ESC mass [g]")
    a2.set_title(f"Lift ESC mass ({cells}S rows)")
    a2.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    return fig


def margin_chart(result, n: int = 14, size=(7.4, 4.8)):
    """The n inequalities with the smallest margin (% of the limit). Red: a violated limit. The label gives the cost of one more
    unit of the limit in Wh when the limit is active."""
    import matplotlib.pyplot as plt
    style()
    rows = sorted(result.enabled().items(), key=lambda kv: kv[1]["margin"])[:n]
    fig, ax = plt.subplots(figsize=size)
    vals = [100.0 * c["margin"] for _, c in rows]
    y = np.arange(len(rows))
    ax.barh(y, vals, color=[RED if v < -1e-4 else BLUE for v in vals], height=0.62, edgecolor=SURFACE, linewidth=1.5)
    ax.set_yticks(y, [k for k, _ in rows])
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    span = max(max(vals), 1.0)
    for yi, (k, c) in zip(y, rows):
        cost = c.get("cost_Wh_per_unit")
        txt = f" {100.0 * c['margin']:.1f} %" + (f", {cost:.2g} Wh per unit" if cost and c["margin"] < 1e-3 else "")
        ax.text(max(100.0 * c["margin"], 0.0), yi, txt, va="center", ha="left", color=INK, fontsize=8)
    ax.set_xlim(min(0.0, min(vals)) - 1.0, span * 1.5)
    ax.set_xlabel("margin [% of the limit]")
    ax.set_title("Limits closest to their bound")
    fig.tight_layout()
    return fig


def frequency_chart(result, size=(6.4, 4.8), margin_frac: Optional[float] = None):
    """The first two bending frequencies of the boom against the rotor speed. Lines: 1P and 2P (rotation and two-blade passing).
    The band is hover 1P +/- the resonance margin. A crossing of f1 or f2 with a line is a speed the rotors must not dwell at.
    f2 includes the tip rotary inertia of the motor and prop (an estimate). A dot marks each crossing up to full throttle.
    The text labels sit in boxes off the lines, and the legend is below the axes."""
    import matplotlib.pyplot as plt
    style()
    rpm_h = result["rotors"]["H_TO_f"]["rpm"]
    rpm_max = max(result["rotors"]["MAX_f"]["rpm"], result["rotors"]["MAX_r"]["rpm"])
    f1, f2 = result["f1_Hz"], result["f2_Hz"]
    mg = margin_frac if margin_frac is not None else 0.2
    r = np.linspace(0.0, 1.05 * rpm_max, 50)
    fig, ax = plt.subplots(figsize=size)
    ax.axvspan(rpm_h * (1 - mg), rpm_h * (1 + mg), color=YELLOW, alpha=0.18, lw=0)
    ax.plot(r, r / 60.0, color=BLUE, label="1P (rotation)")
    ax.plot(r, 2.0 * r / 60.0, color=VIOLET, label="2P (two blades assumed)")
    ax.axhline(f1, color=ORANGE, label=f"boom mode f1 {f1:.1f} Hz")
    ax.axhline(f2, color=ORANGE, ls="--", label=f"boom mode f2 {f2:.0f} Hz (tip rotary inertia)")
    ax.set_ylim(0, 1.1 * max(f2, 2.0 * rpm_max / 60.0))
    box = dict(boxstyle="round,pad=0.3", fc=SURFACE, ec="none", alpha=0.9)
    cross = []
    for name, f in (("f1", f1), ("f2", f2)):
        for k in (1, 2):
            rpm_x = 60.0 * f / k
            if rpm_x <= rpm_max:
                ax.plot([rpm_x], [f], "o", color=INK, ms=4, zorder=5)
                cross.append(f"{name} = {k}P at {rpm_x:.0f} rpm")
    if cross:                                               # one box in the empty top left corner, not on the lines
        ax.text(0.02, 0.80, "Crossings (dots):\n" + "\n".join(cross), transform=ax.transAxes, color=INK, fontsize=8,
                ha="left", va="top", bbox=box, zorder=6)
    y_txt = 0.5 * ax.get_ylim()[1]
    for x, txt in ((rpm_h, "hover"), (rpm_max, "full throttle")):
        ax.axvline(x, color=MUTED, lw=1.0, ls=":")
        ax.text(x, y_txt, txt, color=MUTED, rotation=90, ha="center", va="center", fontsize=8.5, bbox=box, zorder=6)
    ax.set_xlabel("rotor speed [rpm]")
    ax.set_ylabel("frequency [Hz]")
    above = "f2 above 2P at full throttle" if f2 > 2.0 * rpm_max / 60.0 else "f2 crosses 2P"
    ax.set_title(f"Boom modes against rotor speed\n(hover band +/- {100 * mg:.0f} %, {above})")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2, fontsize=8.5)
    ax.set_xlim(0, 1.05 * rpm_max)
    fig.tight_layout()
    return fig


def ladder_chart(run: Dict[str, Any], size=(7.0, 3.0)):
    """Mass and energy at each level of a ladder (the rows of `optimise.ladder`)."""
    import matplotlib.pyplot as plt
    style()
    rows = [r for r in run["levels"] if "M_kg" in r]
    lv = [r["level"] for r in rows]
    fig, ax = plt.subplots(1, 2, figsize=size)
    ax[0].plot(lv, [r["E_Wh"] for r in rows], "o-", color=BLUE)
    ax[0].set_ylabel("energy [Wh]")
    ax[1].plot(lv, [r["M_kg"] for r in rows], "o-", color=ORANGE)
    ax[1].set_ylabel("take-off mass [kg]")
    for a in ax:
        a.set_xlabel("level")
    fig.suptitle(f"Ladder {run['case']}", x=0.01, ha="left", fontweight="bold", fontsize=10.5)
    fig.tight_layout()
    return fig


# ========================================================================================================= plotly scene
def _disc_mesh(d: Dict[str, Any]):
    """The vertices and faces (a fan) of a rotor disc."""
    pts = np.vstack([d["centre"], d["rim"]])
    n = len(d["rim"])
    i = np.zeros(n, int)
    j = np.arange(1, n + 1)
    k = np.roll(j, -1)
    return pts, i, j, k


def scene_traces(model, design: Dict[str, float]):
    """(static traces, dynamic traces) of the 3D scene. Static: the base airframe and the new fuselage (the AeroSandbox mesh).
    Dynamic: two boom lines, the rotor discs, the CG and the battery. The dynamic traces change with the design."""
    import plotly.graph_objects as go
    plane = model.airplane(design, booms=False)
    static = list(plane.draw(backend="plotly", show=False).data)
    g = model.geometry(design)
    dyn = []
    L = 2.0 * g["a"] + 2.0 * g["overhang"]
    for side in (-1, 1):
        dyn.append(go.Scatter3d(x=[g["x_c"] - 0.5 * L, g["x_c"] + 0.5 * L], y=[side * g["y_b"]] * 2, z=[g["z_b"]] * 2, mode="lines",
                                line=dict(color=INK, width=max(4.0, 400.0 * g["r_o"])), name="lift boom", showlegend=side < 0))
    for d in model.rotor_discs(design):
        pts, i, j, k = _disc_mesh(d)
        dyn.append(go.Mesh3d(x=pts[:, 0], y=pts[:, 1], z=pts[:, 2], i=i, j=j, k=k, color=ORANGE, opacity=0.45, name="lift rotor",
                             showlegend=d["name"].endswith("left_f0")))
    dyn.append(go.Scatter3d(x=[g["x_cg"]], y=[0.0], z=[0.0], mode="markers", marker=dict(size=5, color=BLUE, symbol="diamond"), name="CG"))
    dyn.append(go.Scatter3d(x=[g["x_batt"]], y=[0.0], z=[0.0], mode="markers", marker=dict(size=5, color=GREEN, symbol="square"), name="battery"))
    return static, dyn


def update_dynamic(model, dyn, design: Dict[str, float]) -> None:
    """Write the numbers of `design` into the dynamic traces made by `scene_traces` (in place)."""
    g = model.geometry(design)
    L = 2.0 * g["a"] + 2.0 * g["overhang"]
    for t, side in zip(dyn[:2], (-1, 1)):
        t.x, t.y, t.z = [g["x_c"] - 0.5 * L, g["x_c"] + 0.5 * L], [side * g["y_b"]] * 2, [g["z_b"]] * 2
        t.line.width = max(4.0, 400.0 * g["r_o"])
    for t, d in zip(dyn[2:-2], model.rotor_discs(design)):
        pts, _, _, _ = _disc_mesh(d)
        t.x, t.y, t.z = pts[:, 0], pts[:, 1], pts[:, 2]
    dyn[-2].x = [g["x_cg"]]
    dyn[-1].x = [g["x_batt"]]


def scene_figure(model, design: Dict[str, float], height: int = 520):
    """The 3D view as a plotly figure."""
    import plotly.graph_objects as go
    static, dyn = scene_traces(model, design)
    fig = go.Figure(static + dyn)
    fig.update_layout(scene=dict(aspectmode="data"), height=height, margin=dict(l=0, r=0, t=30, b=0), paper_bgcolor=SURFACE,
                      title=f"{model.name}: {model.layout}", legend=dict(orientation="h"))
    return fig


class LiveView:
    """
    A plotly FigureWidget of the 3D scene, the energy and the violation. `update(snapshot)` redraws the booms and rotors and
    adds a point to each trace. It reads a `result.Snapshot` and the model's geometry. It never calls the solver, so the solver
    and the plot stay separate: `optimise.Problem.solve(callback=view.update)`.
    """

    def __init__(self, model, design: Dict[str, float], height: int = 560):
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        self.model = model
        static, dyn = scene_traces(model, design)
        fig = make_subplots(rows=2, cols=2, specs=[[{"type": "scene", "rowspan": 2}, {"type": "xy"}], [None, {"type": "xy"}]],
                            column_widths=[0.64, 0.36], vertical_spacing=0.14, horizontal_spacing=0.08,
                            subplot_titles=("", "energy [Wh]", "largest violation [scaled]"))
        for t in static + dyn:
            fig.add_trace(t, row=1, col=1)
        fig.add_trace(go.Scatter(x=[], y=[], mode="lines", line=dict(color=BLUE, width=2), name="energy", showlegend=False), row=1, col=2)
        fig.add_trace(go.Scatter(x=[], y=[], mode="lines", line=dict(color=RED, width=2), name="violation", showlegend=False), row=2, col=2)
        fig.update_layout(height=height, margin=dict(l=0, r=10, t=40, b=30), paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
                          scene=dict(aspectmode="data"), legend=dict(orientation="h", y=-0.02), title=f"{model.name}: {model.layout}")
        fig.update_yaxes(type="log", row=2, col=2)
        fig.update_xaxes(title_text="iteration", row=2, col=2)
        try:
            self.fig = go.FigureWidget(fig)
        except ImportError as e:                                   # plotly 7 needs anywidget
            raise ImportError("LiveView needs anywidget: run `python -m aeroplan setup AeroSandbox` again") from e
        self.n_static = len(static)
        self.dyn = list(self.fig.data[self.n_static:self.n_static + len(dyn)])
        self.energy = self.fig.data[-2]
        self.violation = self.fig.data[-1]
        self.it: List[int] = []
        self.E: List[float] = []
        self.V: List[float] = []

    def update(self, snap) -> None:
        """Redraw for one snapshot (a function with this one argument goes to `Problem.solve(callback=...)`)."""
        self.it.append(snap.iteration)
        self.E.append(snap.energy_Wh)
        self.V.append(max(snap.violation, 1e-9))
        with self.fig.batch_update():
            update_dynamic(self.model, self.dyn, snap.design)
            self.energy.x, self.energy.y = list(self.it), list(self.E)
            self.violation.x, self.violation.y = list(self.it), list(self.V)
            self.fig.layout.title.text = (f"{self.model.name} {self.model.layout}: iteration {snap.iteration}, "
                                          f"{snap.energy_Wh:.1f} Wh, {snap.mass_kg:.2f} kg")

    def reset(self) -> None:
        self.it, self.E, self.V = [], [], []

    def show_design(self, design: Dict[str, float]) -> None:
        """Draw a design with no solver (a Result or the start values)."""
        with self.fig.batch_update():
            update_dynamic(self.model, self.dyn, design)
