"""
Plots of a model, a `Result` or a `Snapshot`. Nothing here calls the solver: the plotter only reads numbers.

Static plots (matplotlib, so a notebook shows them on GitHub):
    view_3d(model, design)        the AeroSandbox 3D view with the lift booms and the rotor discs
    three_view(model, design)     AeroSandbox three-view with the rotor discs added
    mass_chart(result)            mass of each item of the mass list
    energy_chart(result)          energy of each mission segment
    margin_chart(result)          the limits with the smallest margin, and what one more unit of each costs
    frequency_chart(result)       boom mode against the rotor speed lines (1P, 2P) and the hover band
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
    fig = plt.figure(figsize=size)
    plane = model.airplane(design)
    plane.draw(backend="matplotlib", show=False, set_axis_visibility=False)
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
def _bars(ax, labels, values, colors=BLUE, fmt="{:.2f}"):
    y = np.arange(len(labels))
    ax.barh(y, values, color=colors, height=0.62, edgecolor=SURFACE, linewidth=1.5)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    for yi, v in zip(y, values):
        ax.text(v, yi, " " + fmt.format(v), va="center", ha="left", color=INK, fontsize=8.5)
    ax.set_xlim(0, max(values) * 1.18 if len(values) else 1.0)


def mass_chart(result, size=(6.4, 4.6)):
    """The mass of each item of the mass list (kg), largest first."""
    import matplotlib.pyplot as plt
    style()
    m = sorted(result.mass_by_item().items(), key=lambda kv: -kv[1])
    fig, ax = plt.subplots(figsize=size)
    _bars(ax, [k for k, _ in m], [v for _, v in m], fmt="{:.3f}")
    ax.set_xlabel("mass [kg]")
    ax.set_title(f"Mass list, total {result.mass_kg:.2f} kg")
    fig.tight_layout()
    return fig


def energy_chart(result, size=(6.4, 3.6)):
    """The energy of each mission segment (Wh)."""
    import matplotlib.pyplot as plt
    style()
    e = result.energy_by_segment()
    fig, ax = plt.subplots(figsize=size)
    _bars(ax, [k.replace("_", " ") for k in e], list(e.values()), fmt="{:.1f}")
    ax.set_xlabel("energy [Wh]")
    ax.set_title(f"Mission energy {result.energy_Wh:.1f} Wh of {result['energy_nominal_Wh']:.0f} Wh nominal")
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


def frequency_chart(result, size=(6.4, 4.2), margin_frac: Optional[float] = None):
    """The first bending frequency of the boom against the rotor speed. Lines: 1P and 2P (rotation and two-blade passing). The
    band is hover 1P +/- the resonance margin. A crossing of f1 with a line is a speed the rotors must not dwell at."""
    import matplotlib.pyplot as plt
    style()
    rpm_h = result["rotors"]["H_TO_f"]["rpm"]
    rpm_max = max(result["rotors"]["MAX_f"]["rpm"], result["rotors"]["MAX_r"]["rpm"])
    f1 = result["f1_Hz"]
    mg = margin_frac if margin_frac is not None else 0.2
    r = np.linspace(0.0, 1.05 * rpm_max, 50)
    fig, ax = plt.subplots(figsize=size)
    f_h = rpm_h / 60.0
    ax.axvspan(rpm_h * (1 - mg), rpm_h * (1 + mg), color=YELLOW, alpha=0.18, lw=0)
    ax.plot(r, r / 60.0, color=BLUE, label="1P (rotation)")
    ax.plot(r, 2.0 * r / 60.0, color=VIOLET, label="2P (two blades assumed)")
    ax.axhline(f1, color=ORANGE, label=f"boom mode f1 {f1:.1f} Hz")
    ax.axvline(rpm_h, color=MUTED, lw=1.0, ls=":")
    ax.text(rpm_h, ax.get_ylim()[1] * 0.97, " hover", color=MUTED, va="top", fontsize=8.5)
    ax.axvline(rpm_max, color=MUTED, lw=1.0, ls=":")
    ax.text(rpm_max, ax.get_ylim()[1] * 0.97, " full throttle", color=MUTED, va="top", ha="right", fontsize=8.5)
    ax.set_xlabel("rotor speed [rpm]")
    ax.set_ylabel("frequency [Hz]")
    ax.set_title(f"Boom mode against rotor speed (hover band +/- {100 * mg:.0f} %)")
    ax.legend(loc="upper left", fontsize=8.5)
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
