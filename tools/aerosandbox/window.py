"""
The window: change a few params of a model, see the design and the limits change, and optimise the free ones in front of you.

    from window import Window
    Window(model).show()          # in a notebook; needs ipywidgets and anywidget (the notebook packages of the AeroSandbox Python)

What it shows:
  - one row for each numeric param of each component (value, free or fixed, units, change from the start). Only the design
    variables (model.DESIGN_VARS) can be free; every other param is a fixed input.
  - Evaluate: every param fixed at its value (the battery x closes the CG). The 3D view, the table and the margins show the result.
  - Optimise: the params marked free are the variables, they start at the value in the row. The 3D view redraws at each iteration of
    the solver (`optimise.Problem.solve(callback=...)`), with the energy and the largest violation beside it.
  - "changed only": the comparison table lists only what differs from the start design.
  - Save writes settings/<aircraft>.json.

The logic is in `Session`, with no widget in it, so a script or a test can use it. `Window` only wraps widgets round a Session.
The solver does not draw and the plot does not solve: the window gives the plot function (`plot.LiveView.update`) to the solver.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from model import DESIGN_VARS, AircraftModel
from optimise import Problem, evaluate, init_from, solve_level
from result import Result


class Session:
    """The model being edited, the start model, and the results. No widgets."""

    def __init__(self, model: AircraftModel, level: str = "L1"):
        self.start = model.copy()
        self.model = model.copy()
        self.level = level
        self.baseline: Optional[Result] = None
        self.current: Optional[Result] = None

    # -- the params
    def rows(self) -> List[Tuple[str, str, Any]]:
        """(component, param, Param) of every numeric param."""
        return [(ck, pk, p) for ck, pk, p in self.model.params()
                if isinstance(p.value, (int, float)) and not isinstance(p.value, bool)]

    def is_design(self, ck: str, pk: str) -> bool:
        return (ck, pk) in DESIGN_VARS.values()

    def set(self, ck: str, pk: str, value: float) -> None:
        self.model.c[ck].params[pk].value = float(value)

    def set_free(self, ck: str, pk: str, free: bool) -> None:
        if not self.is_design(ck, pk):
            raise ValueError(f"{ck}.{pk} is not a design variable of the model")
        self.model.c[ck].params[pk].free = bool(free)

    def changed(self) -> List[Tuple[str, str, float, float]]:
        """(component, param, start value, value) of every param that differs from the start."""
        out = []
        for ck, pk, p in self.rows():
            v0 = self.start.c[ck].params[pk].value
            if abs(float(p.value) - float(v0)) > 1e-12 * max(abs(float(v0)), 1.0):
                out.append((ck, pk, float(v0), float(p.value)))
        return out

    def reset(self) -> None:
        self.model = self.start.copy()
        self.current = None

    # -- the runs
    def design_now(self) -> Dict[str, float]:
        return {name: float(self.model.c[ck][pk]) for name, (ck, pk) in DESIGN_VARS.items()}

    def evaluate(self, level: Optional[str] = None) -> Result:
        """Every param fixed at its value (the battery x closes the CG)."""
        if self.baseline is None:
            self.baseline = evaluate(self.start, level or self.level)
        self.current = evaluate(self.model, level or self.level)
        return self.current

    def optimise(self, level: Optional[str] = None, callback=None) -> Result:
        """The params marked free are the variables. They start at their values. `callback(snapshot)` runs at each iteration."""
        if self.baseline is None:
            self.baseline = evaluate(self.start, level or self.level)
        run = solve_level(self.model, level or self.level, None, callback=callback)
        self.current = run["rep"]
        self.status = run["status"]
        return self.current

    def adopt(self) -> None:
        """Take the design values of the last result into the params (a free param keeps its free flag)."""
        if self.current is None:
            return
        for name, (ck, pk) in DESIGN_VARS.items():
            self.model.c[ck].params[pk].value = float(self.current.design[name])

    # -- the comparison
    def compare(self, changed_only: bool = False):
        """A pandas DataFrame: rows are numbers of the design, columns the start and the present result."""
        import pandas as pd
        if self.current is None or self.baseline is None:
            return pd.DataFrame()
        a, b = self.baseline, self.current
        rows = {"take-off mass [kg]": (a.mass_kg, b.mass_kg), "energy [Wh]": (a.energy_Wh, b.energy_Wh),
                "rotor diameter [mm]": (1000 * a["D_m"], 1000 * b["D_m"]), "boom f1 [Hz]": (a["f1_Hz"], b["f1_Hz"]),
                "hover 1P [Hz]": (a["f_hover_1P_Hz"], b["f_hover_1P_Hz"]),
                "limits at the bound": (len(a.active()), len(b.active())), "limits broken": (len(a.violated()), len(b.violated()))}
        for name, (ck, pk) in DESIGN_VARS.items():
            rows[f"{ck}.{pk}"] = (a.design[name], b.design[name])
        df = pd.DataFrame(rows, index=["start", "now"]).T
        df["change"] = df["now"] - df["start"]
        if changed_only:
            df = df[df["change"].abs() > 1e-9 * df[["start", "now"]].abs().max(axis=1).clip(lower=1.0)]
        return df

    def save(self) -> Any:
        if self.current is not None:
            self.model.result_summary = self.current.summary()
        return self.model.save()


class Window:
    """ipywidgets around a Session. `Window(model).show()` in a notebook."""

    def __init__(self, model: AircraftModel, level: str = "L1"):
        import ipywidgets as W
        from plot import LiveView
        self.W = W
        self.s = Session(model, level)
        self.live = LiveView(self.s.model, self.s.design_now())
        self.out = W.Output()
        self.status = W.HTML("")
        self.changed_only = W.Checkbox(value=False, description="changed only", indent=False)
        self.level = W.Dropdown(options=["L1", "L2", "L3", "L4"], value=level, description="level", layout=W.Layout(width="140px"))
        self.buttons = {k: W.Button(description=k, button_style=st) for k, st in
                        (("Evaluate", "info"), ("Optimise", "success"), ("Reset", ""), ("Adopt result", ""), ("Save", "warning"))}
        self.buttons["Evaluate"].on_click(lambda _: self._run("evaluate"))
        self.buttons["Optimise"].on_click(lambda _: self._run("optimise"))
        self.buttons["Reset"].on_click(lambda _: self._reset())
        self.buttons["Adopt result"].on_click(lambda _: self._adopt())
        self.buttons["Save"].on_click(lambda _: self._save())
        self.changed_only.observe(lambda _: self._show_table(), names="value")
        self.fields: Dict[Tuple[str, str], Tuple[Any, Any]] = {}
        self.box = W.VBox([W.HBox([self.level] + list(self.buttons.values()) + [self.changed_only]), self.status,
                           self._accordion(), self.live.fig, self.out])

    def _accordion(self):
        W = self.W
        groups: Dict[str, List[Any]] = {}
        for ck, pk, p in self.s.rows():
            val = W.FloatText(value=float(p.value), layout=W.Layout(width="150px"), step=None)
            val.observe(lambda ch, ck=ck, pk=pk: self._on_value(ck, pk, ch["new"]), names="value")
            free = W.Checkbox(value=bool(p.free), description="free", indent=False, layout=W.Layout(width="70px"),
                              disabled=not self.s.is_design(ck, pk))
            free.observe(lambda ch, ck=ck, pk=pk: self.s.set_free(ck, pk, ch["new"]), names="value")
            self.fields[(ck, pk)] = (val, free)
            tag = " (stand-in)" if p.placeholder else ""
            lab = W.HTML(f"<b>{pk}</b> <span style='color:#52514e'>{p.units}{tag}</span>", layout=W.Layout(width="260px"),
                         tooltip=p.source)
            groups.setdefault(ck, []).append(W.HBox([lab, val, free]))
        acc = W.Accordion(children=[W.VBox(rows) for rows in groups.values()])
        for i, k in enumerate(groups):
            acc.set_title(i, k)
        acc.selected_index = None
        return acc

    def _on_value(self, ck, pk, v):
        self.s.set(ck, pk, v)
        self.live.show_design(self.s.design_now())

    def _run(self, what: str):
        self.status.value = f"running {what} at {self.level.value} ..."
        self.live.reset()
        try:
            if what == "evaluate":
                self.s.evaluate(self.level.value)
            else:
                self.s.optimise(self.level.value, callback=self.live.update)
            r = self.s.current
            self.live.show_design(r.design)
            word = "converged" if r.ok else ("the solver could not meet every limit: these numbers are its last iterate"
                                             if what == "evaluate" else "NOT converged")
            self.status.value = (f"<b>{what}</b> {r['level']}: {word}. {r.energy_Wh:.1f} Wh, {r.mass_kg:.2f} kg. "
                                 f"Broken limits: {', '.join(r.violated()) or 'none'}")
        except Exception as e:                                   # show the error in the window, keep the window alive
            self.status.value = f"<b style='color:#e34948'>{type(e).__name__}: {str(e)[:300]}</b>"
            return
        self._show_table()

    def _show_table(self):
        from IPython.display import display
        import matplotlib.pyplot as plt
        import plot
        self.out.clear_output(wait=True)
        if self.s.current is None:
            return
        with self.out:
            display(self.s.compare(self.changed_only.value).style.format("{:.4g}"))
            fig = plot.margin_chart(self.s.current, n=10, size=(6.4, 3.4))
            display(fig)
            plt.close(fig)

    def _reset(self):
        self.s.reset()
        for (ck, pk), (val, free) in self.fields.items():
            p = self.s.model.c[ck].params[pk]
            val.value, free.value = float(p.value), bool(p.free)
        self.live.show_design(self.s.design_now())
        self.out.clear_output()
        self.status.value = "reset to the start design"

    def _adopt(self):
        self.s.adopt()
        for (ck, pk), (val, _) in self.fields.items():
            val.value = float(self.s.model.c[ck].params[pk].value)
        self.status.value = "the values of the last result are now the start values of the rows"

    def _save(self):
        path = self.s.save()
        self.status.value = f"saved {path}"

    def show(self):
        from IPython.display import display
        display(self.box)
        return self
