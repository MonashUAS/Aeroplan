"""
The solver driver. It turns a model (model.py) into one `asb.Opti` problem, solves it, and gives a `Result` (result.py).

    p = Problem(model, "L4")           # one problem at one level; the free params of the components are the variables
    p.build(); p.solve(); res = p.report()
    res = solve_level(model, "L2", init)                # the elastic feasibility phase, then the optimality phase
    run = ladder(model, "L0..L4", out=folder)           # the fidelity ladder: each level starts from the one below
    res = evaluate(model)                               # the design as it is: all params fixed, the CG closed by the battery

What the problem does for a model:
  design(name, param)   a free param is an Opti variable (bounds, scale, start from the param); a fixed param is an Opti parameter
  state(name, ...)      a variable that is not a design choice (shaft speeds, peak current, cruise speeds)
  limit(name, expr, lo, hi, scale, group)   constrain when the group is on at this level, and keep it for the report. In the
                        feasibility phase a slack >= 0 relaxes the limit and the objective is the sum of the slacks
  solve(callback)       IPOPT with the exact Hessian. `callback(snapshot)` runs at each iteration (the plotter reads the snapshot)

The solver never draws. A window or a notebook gives `callback` a function that draws a `result.Snapshot`.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from component import G0, Level, Tube, level, parse_levels, work_dir
from model import DESIGN_VARS
from result import OK_STATUS, Result, Snapshot, margin, passes


@dataclass
class LadderSettings:
    """Tuning of the ladder. These are solver settings, not aircraft data. The values are stand-ins found by use (placeholder),
    except `active_margin` (a constraint with a margin below 1e-3 is active)."""
    feasibility_tol: float = 1.0e-4     # largest scaled slack below which the level counts as feasible. IPOPT leaves each slack near 1e-6
    elastic_pull: float = 1.0e-2        # weight of the squared distance (in bound widths) to the start point in the elastic phase
    active_margin: float = 1.0e-3
    multistart_seed: int = 20261017     # fixed seed so that the random starts repeat
    first: Tuple[float, float] = (1.0e-3, 1.0e-4)     # IPOPT (mu_init, bound_push) of a warm start
    retry: Tuple[float, float] = (1.0e-1, 1.0e-3)     # the retry after a failed optimality phase


def _status_word(p: "Problem") -> str:
    rs = p.stats.get("return_status", "")
    if p.sol is None:
        return "failed"
    return "ok" if rs == "Solve_Succeeded" else "acceptable"


class Problem:
    """One optimisation problem of a model at one level. `init`: start values by name (see `init_from`). `feasibility`: minimise
    the sum of the slacks of the limits in place of the objective. `objective`: "energy" (mission energy, Wh), "mass" or a
    function of the model output."""

    def __init__(self, model, lvl: Any = "L4", feasibility: bool = False, init: Optional[Dict[str, float]] = None,
                 objective: Any = "energy", settings: Optional[LadderSettings] = None):
        import aerosandbox as asb
        self.model, self.level = model, level(lvl)
        self.feasibility = bool(feasibility)
        self.init = dict(init or {})
        self.objective = objective
        self.settings = settings or LadderSettings()
        self.opti = asb.Opti()
        self.v: Dict[str, Any] = {}                         # design variables (and parameters when fixed)
        self.fixed_values: Dict[str, float] = {}
        self.named: Dict[str, Any] = {}                     # every Opti variable by name (design, I_pk, V_lap, w_<state>)
        self.bounds: Dict[str, Tuple[float, float]] = {}
        self.cons: Dict[str, Any] = {}                      # name -> (expression, lo, hi), the report
        self.cgroup: Dict[str, str] = {}
        self.cscale: Dict[str, float] = {}
        self.duals: Dict[str, List[Any]] = {}
        self.slacks: Dict[str, Any] = {}
        self.sol = None
        self.error = ""
        self.stats: Dict[str, Any] = {}
        self.out: Optional[Dict[str, Any]] = None
        self._eval = None

    # -- the interface of the models
    def design(self, name: str, p, lo: Optional[float] = None, hi: Optional[float] = None):
        """A design variable from a param. Free: an Opti variable that starts at `init[name]` (or the value of the param),
        clipped to the bounds of the param (`lo`, `hi` are the defaults when the param has none). Fixed: an Opti parameter."""
        o = self.opti
        if not p.free:
            x = o.parameter(float(p.value))
            self.fixed_values[name] = float(p.value)
        else:
            lo, hi = (p.lo if p.lo is not None else lo), (p.hi if p.hi is not None else hi)
            if lo is None or hi is None:
                raise ValueError(f"{name}: a free param needs bounds (lo and hi)")
            x0 = min(max(float(self.init.get(name, p.value)), lo), hi)
            x = o.variable(init_guess=x0, lower_bound=lo, upper_bound=hi, scale=p.scale or max(abs(float(p.value)), 1e-3))
            self.named[name] = x
            self.bounds[name] = (lo, hi)
        self.v[name] = x
        return x

    def state(self, name: str, init: float, lo: float, hi: float, scale: Optional[float] = None):
        """An Opti variable that is not a design choice. Start value: self.init[name] (clipped to the bounds) or init."""
        x0 = min(max(float(self.init.get(name, init)), lo), hi)
        x = self.opti.variable(init_guess=x0, lower_bound=lo, upper_bound=hi, scale=scale or max(abs(init), 1e-3))
        self.named[name] = x
        self.bounds[name] = (lo, hi)
        return x

    def start(self, name: str, default: float) -> float:
        """The numeric start value of a variable or fixed parameter."""
        return float(self.fixed_values[name]) if name in self.fixed_values else float(self.init.get(name, default))

    def limit(self, name, expr, lo=None, hi=None, scale=None, group="misc"):
        """Constrain lo <= expr <= hi when the group is on at this level, and keep it for the report. The constraint is
        scaled by `scale` (default: the size of the numeric bound). In the feasibility phase a slack >= 0 relaxes it."""
        o = self.opti
        if scale is None:
            b = [abs(x) for x in (lo, hi) if isinstance(x, (int, float)) and x != 0.0]
            scale = b[0] if b else 1.0
        self.cons[name], self.cgroup[name], self.cscale[name] = (expr, lo, hi), group, float(scale)
        if group not in self.level.groups:
            return
        sl = 0.0
        if self.feasibility:
            # Start the slack at the violation of the start point (a start that is feasible gives a slack near zero)
            # in place of a fixed 0.05, which pushes the phase away from a good start.
            s0 = 0.05
            if self.init:
                try:
                    ev = lambda x: float(np.ravel(o.value(x, o.initial()))[0])
                    v0 = ev(expr)
                    s0 = max(0.0, (ev(lo) - v0) / scale if lo is not None else 0.0, (v0 - ev(hi)) / scale if hi is not None else 0.0)
                    s0 = min(s0 + 1e-4, 1.0) if np.isfinite(s0) else 0.05
                except RuntimeError:
                    s0 = 0.05
            sl = o.variable(init_guess=s0, lower_bound=0.0, scale=0.1)
            self.slacks[name] = sl
        d = []
        if lo is not None:
            d.append(o.subject_to(expr / scale >= lo / scale - sl))
        if hi is not None:
            d.append(o.subject_to(expr / scale <= hi / scale + sl))
        self.duals[name] = d

    # -- build, solve
    def build(self) -> "Problem":
        o = self.opti
        self.out = self.model.build(self)
        if self.feasibility and self.slacks:
            obj = sum(self.slacks.values())                            # elastic phase: the sum of the scaled slacks
            # Small pull to the start point: with all slacks at zero the objective is flat, and IPOPT can drift far away
            # from a start that is already feasible. The weight is small, so a real violation still wins.
            near = [((self.named[k] - self.start(k, 0.0)) / (hi - lo)) ** 2 for k, (lo, hi) in self.bounds.items()
                    if k in self.v and hi > lo and k in self.init]
            if near:
                obj = obj + self.settings.elastic_pull * sum(near)
            o.minimize(obj)
        else:
            f = {"energy": lambda out: out["E_total"] / 100.0, "mass": lambda out: out["names"]["M"] / 10.0}.get(self.objective, self.objective)
            o.minimize(f(self.out))
        return self

    def solve(self, verbose=False, max_iter=300, max_runtime=1e20, options=None, attempts=1,
              callback: Optional[Callable[[Snapshot], None]] = None):
        """IPOPT with the exact Hessian. attempts > 1: a failed attempt hands its last iterate to the next one. The status is in
        self.stats (return_status, iter_count, success, seconds). The last iterate stays available for the report.
        callback: a function of a `Snapshot`, called at each iteration."""
        opts = {"ipopt.mu_strategy": "adaptive", "ipopt.tol": 1e-5, "ipopt.acceptable_tol": 1e-3,
                "ipopt.acceptable_iter": 5, "ipopt.bound_relax_factor": 1e-8}
        opts.update(options or {})
        cb = (lambda i: callback(self.snapshot(i))) if callback else None
        t0, iters = time.time(), 0
        for k in range(attempts):
            try:
                self.sol = self.opti.solve(verbose=verbose, max_iter=max_iter, max_runtime=max_runtime, options=opts, callback=cb)
                self.error = ""
                st = self.sol.stats()
                self.stats = {"return_status": st.get("return_status"), "iter_count": iters + int(st.get("iter_count", 0)), "success": True}
                break
            except RuntimeError as e:
                self.error = str(e).splitlines()[0]
                self.sol = None
                try:
                    st = self.opti.debug.stats()
                except Exception:
                    st = {}
                iters += int(st.get("iter_count", 0) or 0)
                self.stats = {"return_status": st.get("return_status", "error"), "iter_count": iters, "success": False}
                try:
                    self.opti.set_initial(self.opti.x, self.opti.debug.value(self.opti.x))
                except Exception:
                    break
        self.stats["seconds"] = time.time() - t0
        return self.sol

    def snapshot(self, iteration: int) -> Snapshot:
        """The numbers of the present iterate (inside the callback) or of the solution: design values, mass, energy and the
        largest scaled violation of an enabled limit."""
        import casadi as cas
        o = self.opti
        if self._eval is None:
            enabled = [k for k in self.cons if self.cgroup[k] in self.level.groups]
            outs = [cas.vec(cas.MX(e)) for e in list(self.v.values()) + [self.out["E_total"], self.out["names"]["M"]]]
            for k in enabled:
                e, lo, hi = self.cons[k]
                outs += [cas.vec(cas.MX(e)), cas.vec(cas.MX(float("nan") if lo is None else lo)),
                         cas.vec(cas.MX(float("nan") if hi is None else hi))]
            self._eval = (cas.Function("snap", [o.x, o.p], [cas.vertcat(*outs)]), enabled)
        fn, enabled = self._eval
        x, pv = o.debug.value(o.x), o.debug.value(o.p)
        y = np.ravel(np.array(fn(x, pv)))
        n = len(self.v)
        design = dict(zip(self.v, map(float, y[:n])))
        viol = 0.0
        tail = y[n + 2:].reshape(-1, 3)
        for (val, lo, hi), k in zip(tail, enabled):
            sc = self.cscale[k]
            if np.isfinite(lo):
                viol = max(viol, (lo - val) / sc)
            if np.isfinite(hi):
                viol = max(viol, (val - hi) / sc)
        return Snapshot(iteration, design, mass_kg=float(y[n + 1]), energy_Wh=float(y[n]), violation=max(viol, 0.0))

    # -- read
    def value(self, x) -> float:
        if isinstance(x, (int, float)):
            return float(x)
        if self.sol is not None:
            return float(np.ravel(self.sol(x))[0])
        try:
            return float(np.ravel(self.opti.debug.value(x))[0])
        except RuntimeError:                              # the solver stopped before the first iterate: use the start values
            return float(np.ravel(self.opti.value(x, self.opti.initial()))[0])

    def _dual(self, d) -> float:
        """The multiplier of a constraint (0 when the solver gives none: a parametric constraint, or a failed solve)."""
        if d is None:
            return 0.0
        try:
            return float(np.ravel(self.sol.value(d))[0]) if self.sol is not None else float(np.ravel(self.opti.debug.value(d))[0])
        except Exception:
            return 0.0

    def report(self) -> Result:
        """The numbers of the solution (the last iterate when the solve failed)."""
        g, m, out = self.value, self.model, self.out
        R_m = g(out["R"])
        rep: Dict[str, Any] = {"config": m.layout, "cells_s": int(m.c["battery"]["cells_s"]), "converged": self.sol is not None,
                               "error": self.error, "design": {k: g(v) for k, v in self.v.items()}, "R_m": R_m, "D_m": 2.0 * R_m}
        rep["names"] = {k: g(v) for k, v in out["names"].items()}
        word = _status_word(self)
        rep["status_word"] = word
        rep["ok"] = bool(word in OK_STATUS and self.stats.get("return_status") != "Infeasible_Problem_Detected")
        rep.update(m.static_report(R_m))
        rep["names"]["E_Wh"] = g(out["E_total"])
        rep["level"], rep["feasibility_phase"], rep["status"] = self.level.name, self.feasibility, dict(self.stats)
        rep["constraints"] = {}
        for k, (e, lo, hi) in self.cons.items():
            c = {"value": g(e), "lo": None if lo is None else g(lo), "hi": None if hi is None else g(hi), "group": self.cgroup[k],
                 "enabled": self.cgroup[k] in self.level.groups, "scale": self.cscale[k]}
            c["equality"] = c["lo"] is not None and c["lo"] == c["hi"]
            c["margin"] = margin(c) if not c["equality"] else -abs(c["value"] - c["lo"]) / max(abs(c["lo"]), 1e-9)
            lam = [abs(self._dual(d)) for d in self.duals.get(k, [])]
            c["dual_scaled"] = float(sum(lam)) if lam else None
            if lam and not self.feasibility:
                c["cost_Wh_per_unit"] = float(sum(lam)) * 100.0 / self.cscale[k]      # the objective is E / 100 Wh
            if k in self.slacks:
                c["slack"] = g(self.slacks[k])
            rep["constraints"][k] = c
        rep["slacks"] = {k: g(v) for k, v in self.slacks.items()}
        rep["energy_Wh"] = {k: g(v) / 3600.0 for k, v in out["seg_J"].items()}
        rep["energy_total_Wh"], rep["energy_nominal_Wh"] = g(out["E_total"]), g(out["E_nom"])
        rep["time_s"] = {k: g(v) for k, v in out["t"].items()}
        rep["inertia_kg_m2"] = {k: g(v) for k, v in zip(("ixx", "iyy", "izz"), out["inertia"])}
        rep["control"] = {k: g(v) for k, v in out["ctl"].items()}
        rep["cruise"] = {"lap": {k: g(v) for k, v in out["lap"].items()}, "map": {k: g(v) for k, v in out["map"].items()}}
        rep["cda_m2"] = {k: g(v) for k, v in out["cda"].items()}
        rep["P_battery_W"] = {k: g(v) for k, v in out["P"].items()} | {"MAX": g(out["P_max"])}
        rep["I_battery_max_A"], rep["V_bus_max_V"] = g(out["I_b_max"]), g(out["V_bus"])
        rep["f1_Hz"], rep["f_hover_1P_Hz"] = g(out["f1"]), max(g(f) for f in out["freq_hover"])
        bm = {k: g(v) for k, v in out["boom_modal"].items()}          # f2: a check after the solve (Tube.modes_hz)
        rep["f1_exact_Hz"], rep["f2_Hz"] = Tube.modes_hz(bm["E"], bm["I"], bm["a"], bm["m_tip"], bm["m_arm"], bm["J_tip"])
        rep["f2_no_J_Hz"] = Tube.modes_hz(bm["E"], bm["I"], bm["a"], bm["m_tip"], bm["m_arm"], 0.0)[1]
        rep["boom_J_tip_kg_m2"] = bm["J_tip"]
        rep["structure"] = [{k: g(v) for k, v in d.items()} for d in out["struct"]]
        rep["rotors"] = {n: {"omega_rad_s": g(r["omega"]), "rpm": g(r["omega"]) * 60 / (2 * math.pi), "Q_Nm": g(r["Q"]),
                             "T_N": g(r["T"]), "P_shaft_W": g(r["P_shaft"]), "I_A": g(r["I"]), "Pe_W": g(r["Pe"])}
                         for n, r in out["rotors"].items()}
        rep["items"] = [{"name": i[0], "mass_kg": g(i[1]), "x": g(i[2]), "y": g(i[3]), "z": g(i[4])} for i in out["items"]]
        rep["placeholders"] = m.placeholders()
        rep["motor_fit"] = m.d.motor_fit.summary()
        rep["airframe"] = m.af.summary()
        return Result(rep)


# ================================================================================================================ ladder
def init_from(rep: Any) -> Dict[str, float]:
    """Start values for the next level from the report of this one: the design variables, I_pk, V_lap, M and the shaft speed
    of every rotor state (names as in Problem.named)."""
    rep = rep.data if isinstance(rep, Result) else rep
    d = {k: float(v) for k, v in rep["design"].items()}
    d["I_pk"], d["V_lap"], d["V_map"], d["M"] = (float(rep["names"][k]) for k in ("I_pk", "V_lap", "V_map", "M"))
    for n, r in rep["rotors"].items():
        d["w_" + n] = float(r["omega_rad_s"])
    for k in ("lap", "map"):
        d["w_cr_" + k] = float(rep["cruise"][k]["omega"])
    return d


def solve_level(model, lvl: Any, init: Optional[Dict[str, float]] = None, settings: Optional[LadderSettings] = None,
                verbose=False, max_iter=300, max_runtime=1e20, callback=None, objective: Any = "energy") -> Dict[str, Any]:
    """
    One level: the elastic feasibility phase (feasible when the largest scaled slack is at most feasibility_tol), then the
    optimality phase from the feasibility point. When the optimality phase fails, one retry from the feasibility point with the
    retry options. Returns {status, rep, feasibility, iterations, seconds, attempts}. status: ok, acceptable, infeasible or failed.
    """
    st = settings or LadderSettings()
    t0 = time.time()

    def left():
        return max(max_runtime - (time.time() - t0), 1.0)

    def make(feas, ini):
        return Problem(model, lvl, feasibility=feas, init=ini, objective=objective, settings=st).build()

    cf = make(True, init)
    # A warm start (a point from the level below) gets the small barrier start of `first`. The default start
    # (mu_init 0.1, bound push 0.01) throws the iterate far from a start that is nearly feasible.
    w = st.first
    wopt = {"ipopt.mu_init": float(w[0]), "ipopt.bound_push": float(w[1]), "ipopt.bound_frac": float(w[1])} if init else None
    cf.solve(verbose=verbose, max_iter=max_iter, max_runtime=left(), options=wopt, callback=callback)
    rf = cf.report()
    worst_slack = float(max(rf["slacks"].values(), default=0.0))      # IPOPT leaves each slack near 1e-6, so the sum grows with the count
    feas = {"slack_total": float(sum(rf["slacks"].values())), "slack_max": worst_slack, "slacks": rf["slacks"], "status": cf.stats,
            "feasible": worst_slack <= st.feasibility_tol}
    res: Dict[str, Any] = {"feasibility": feas, "iterations": {"feasibility": cf.stats.get("iter_count", 0), "optimality": 0}, "attempts": []}
    if not feas["feasible"]:
        res.update(status="infeasible", rep=rf, seconds=time.time() - t0)
        return res
    ini = init_from(rf)
    last = None
    for tag, o in (("first", st.first), ("retry", st.retry)):
        co = make(False, ini)
        co.solve(verbose=verbose, max_iter=max_iter, max_runtime=left(), callback=callback,
                 options={"ipopt.mu_init": float(o[0]), "ipopt.bound_push": float(o[1]), "ipopt.bound_frac": float(o[1])})
        res["attempts"].append({"tag": tag, "status": co.stats, "error": co.error})
        res["iterations"]["optimality"] += co.stats.get("iter_count", 0)
        last = co
        if co.sol is not None:
            break
        if time.time() - t0 > max_runtime:
            break
    res["status"] = _status_word(last)
    res["rep"] = last.report()
    res["seconds"] = time.time() - t0
    return res


def random_starts(bounds: Dict[str, Tuple[float, float]], base: Dict[str, float], n: int, seed: int,
                  fixed: Optional[Dict[str, float]] = None) -> List[Dict[str, float]]:
    """The base start and n - 1 random starts inside the bounds of the design variables (fixed seed). Shaft speeds keep the
    start of the base."""
    rng = np.random.default_rng(seed)
    out = [dict(base)]
    for _ in range(max(n - 1, 0)):
        d = dict(base)
        for k, (lo, hi) in bounds.items():
            if not k.startswith("w_") and k not in (fixed or {}):
                d[k] = float(rng.uniform(lo, hi))
        out.append(d)
    return out


def _gap(rep: Dict[str, Any], prev: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if prev is None:
        return None
    f = {"M_kg": lambda r: r["names"]["M"], "E_Wh": lambda r: r["energy_total_Wh"], "D_m": lambda r: r["D_m"],
         "kv": lambda r: r["design"]["kv"]}
    return {k: f[k](rep) - f[k](prev) for k in f}


def case_name(model) -> str:
    return f"{model.layout}_{int(model.c['battery']['cells_s'])}S"


def ladder(model, levels: str = "L0..L4", out: Optional[Path] = None, multistart: int = 5, verbose=False,
           time_limit_s: Optional[float] = None, resume: bool = False, max_iter: int = 300,
           settings: Optional[LadderSettings] = None, callback=None, log=print) -> Dict[str, Any]:
    """
    The fidelity ladder for one model. Each level has the elastic feasibility phase and the optimality phase and starts from the
    result of the level below. It writes out/<case>/L<k>.json and stops at the first level that fails.
    resume: the first level starts from the L<k-1>.json that is already on disk.
    Returns {"case", "levels": [row, ...], "last_ok": level name or None, "reports": {level: Result}}.
    """
    st = settings or LadderSettings()
    t_start = time.time()
    case = case_name(model)
    d = (out or work_dir(model.name) / "ladder") / case
    d.mkdir(parents=True, exist_ok=True)
    lv = parse_levels(levels)
    init: Dict[str, float] = {}
    prev: Optional[Dict[str, Any]] = None
    if resume:
        k0 = int(lv[0][1:])
        if k0 > 0:
            prev = json.loads((d / f"L{k0 - 1}.json").read_text(encoding="utf-8"))
            init = init_from(prev)
    bounds = Problem(model, "L0", settings=st).build().bounds
    fixed = {}
    rows, reports, last_ok = [], {}, None
    for L in lv:
        t0 = time.time()
        remaining = None if time_limit_s is None else time_limit_s - (time.time() - t_start)
        if remaining is not None and remaining <= 0:
            rows.append({"level": L, "status": "time limit", "seconds": 0.0})
            break
        n_ms = multistart if L in ("L0", "L1") else 1
        starts = random_starts(bounds, init, n_ms, st.multistart_seed, fixed)
        best, tried = None, []
        for i, s0 in enumerate(starts):
            try:
                r = solve_level(model, L, s0, st, verbose=verbose, max_iter=max_iter,
                                max_runtime=1e20 if remaining is None else max(remaining - (time.time() - t0), 5.0), callback=callback)
            except RuntimeError as e:                    # a random start that gives NaN at the first point
                tried.append({"start": i, "status": "error", "error": str(e).splitlines()[0]})
                log(f"  [{case} {L}] start {i}: error {str(e).splitlines()[0][:80]}")
                continue
            E = r["rep"]["energy_total_Wh"]
            tried.append({"start": i, "status": r["status"], "E_Wh": E, "seconds": r["seconds"], "slack_total": r["feasibility"]["slack_total"]})
            if n_ms > 1:
                log(f"  [{case} {L}] start {i}: {r['status']} E={E:.1f} Wh {r['seconds']:.1f} s")
            good = r["status"] in OK_STATUS
            if best is None or (good and (best["status"] not in OK_STATUS or E < best["rep"].energy_Wh)) or \
                    (not good and best["status"] not in OK_STATUS and r["feasibility"]["slack_total"] < best["feasibility"]["slack_total"]):
                best = r
        if best is None:
            raise RuntimeError(f"{case} {L}: no start could be solved")
        res = best["rep"]
        rep = res.data
        rep["converged"] = best["status"] in OK_STATUS
        rep["ladder_status"] = best["status"]
        rep["status_word"], rep["ok"] = best["status"], best["status"] in OK_STATUS
        rep["gap_to_lower_level"] = _gap(rep, prev)
        rep["active"] = [k for k, c in rep["constraints"].items() if c["enabled"] and not c["equality"] and c["margin"] < st.active_margin]
        rep["infeasible"] = [k for k, c in rep["constraints"].items() if c["enabled"] and not c["equality"] and not passes(c)]
        rep["feasibility"] = best["feasibility"]
        rep["iterations"], rep["attempts"], rep["multistart"] = best["iterations"], best["attempts"], tried
        rep["seconds"] = time.time() - t0
        res.save(d / f"{L}.json")
        row = {"level": L, "status": best["status"], "seconds": rep["seconds"], "M_kg": rep["names"]["M"], "E_Wh": rep["energy_total_Wh"],
               "D_m": rep["D_m"], "kv": rep["design"]["kv"], "worst": res.worst(), "iterations": best["iterations"],
               "slack_total": best["feasibility"]["slack_total"]}
        if best["status"] == "infeasible":
            row["slack_names"] = sorted(((k, v) for k, v in best["feasibility"]["slacks"].items() if v > 1e-6), key=lambda kv: -kv[1])[:8]
        rows.append(row)
        reports[L] = res
        log(f"[{case} {L}] {best['status']} {rep['seconds']:.1f} s  M={row['M_kg']:.2f} kg E={row['E_Wh']:.0f} Wh "
            f"D={1000 * row['D_m']:.0f} mm kv={row['kv']:.0f}  iters {best['iterations']}")
        if best["status"] not in OK_STATUS:
            break
        last_ok, prev, init = L, rep, init_from(rep)
    return {"case": case, "levels": rows, "last_ok": last_ok, "reports": reports}


def ladder_table(run: Dict[str, Any]) -> str:
    """The rows of a ladder as text."""
    L = [f"Ladder {run['case']}",
         f"{'level':5s} {'status':11s} {'s':>7s} {'M kg':>7s} {'E Wh':>7s} {'D mm':>6s} {'kv':>6s}  worst 5 constraints (margin)"]
    for r in run["levels"]:
        if "M_kg" not in r:
            L.append(f"{r['level']:5s} {r['status']}")
            continue
        w = ", ".join(f"{k} {m:+.3f}" for k, m in r["worst"])
        L.append(f"{r['level']:5s} {r['status']:11s} {r['seconds']:7.1f} {r['M_kg']:7.2f} {r['E_Wh']:7.0f} {1000 * r['D_m']:6.0f} {r['kv']:6.0f}  {w}")
        if r.get("slack_names"):
            L.append("      slack > 0: " + ", ".join(f"{k} {v:.3g}" for k, v in r["slack_names"]))
    return "\n".join(L)


def optimise(model, lvl: Any = "L4", init: Optional[Dict[str, float]] = None, **kw) -> Result:
    """One level for the model as it is (the free params are the variables): feasibility phase, then the optimum.
    `init` is a start (for example `init_from(result)`). Returns the Result; `result.ok` says whether it converged."""
    return solve_level(model, lvl, init, **kw)["rep"]


def evaluate(model, lvl: Any = "L4", free: Tuple[str, ...] = ("battery.x_m",), **kw) -> Result:
    """The design as it is: every param fixed at its value, except the params in `free` (the battery x closes the CG). A
    freed param starts at its value. Returns the Result with the constraints; `result.violated()` lists the limits it breaks."""
    m = model.copy()
    for _, _, p in m.params():
        p.free = False
    m.free(*free)
    init = {name: float(m.c[ck][pk]) for name, (ck, pk) in DESIGN_VARS.items() if f"{ck}.{pk}" in free}
    p = Problem(m, lvl, init=init).build()
    p.solve(attempts=2, **kw)
    return p.report()
