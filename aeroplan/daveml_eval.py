"""Evaluate a DAVE-ML model in its ADH `DAVEfunc` form, and run its checkData static shots.

A model is a set of variables. A variable gets its value from (first match):
  1. an input given by the caller (by varID or by name),
  2. the dependent variable of a `function` (a gridded table, inline points, or an ungridded table of one input),
  3. its `calculation` (MathML content markup),
  4. its `initialValue`.
Each variable is evaluated once, when it is needed. A loop in the definitions is an error.

Tables (DAVE-ML 2.0 section 4): a gridded table holds its values in row-major order, the last breakpoint set
changes fastest. Interpolation is multilinear. Each independent variable is clamped to its `min` and `max`, then
held at the end breakpoints unless `extrapolate` (min, max, both) allows a linear extrapolation on that side.
`interpolate` may also be `floor`, `ceiling` or `discrete` (nearest).

MathML: the content elements that flight models use: apply with plus, minus, times, divide, power, abs, root,
exp, ln, log, sin, cos, tan, arcsin, arccos, arctan, min, max, floor, ceiling, quotient, rem, the relations
(lt, leq, gt, geq, eq, neq), and, or, xor, not, piecewise (also inside an apply), ci, cn (with e-notation and
rational), pi, exponentiale, true, false and the DAVE-ML csymbol atan2.

checkData: each static shot sets its checkInputs (by signal name or varID, the units must match the variable
units), then each checkOutputs signal must be within `tol` (absolute) of its value. The internalValues signals are
compared too, with the tol of the shot outputs (the smallest one), and reported as notes when they differ.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

MATHML = "{http://www.w3.org/1998/Math/MathML}"


class EvalError(ValueError):
    """The model cannot be evaluated (a missing variable, a loop, an unknown MathML element)."""


def _numbers(text: str) -> np.ndarray:
    return np.array([float(t) for t in re.split(r"[\s,]+", text.strip()) if t], dtype=float)


def _tag(e: ET.Element) -> str:
    return e.tag[len(MATHML):] if e.tag.startswith(MATHML) else e.tag


def _cn(e: ET.Element) -> float:
    kind = e.get("type", "real")
    if kind in ("e-notation", "rational"):
        parts = [(e.text or "").strip()] + [(c.tail or "").strip() for c in e]
        a, b = float(parts[0]), float(parts[1])
        return a * 10.0 ** b if kind == "e-notation" else a / b
    return float((e.text or "").strip())


_UNARY: Dict[str, Callable[[float], float]] = {
    "abs": abs, "exp": math.exp, "ln": math.log, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "arcsin": math.asin, "arccos": math.acos, "arctan": math.atan, "floor": math.floor, "ceiling": math.ceil,
    "not": lambda x: float(not x), "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
}
_RELATIONS = {"lt": lambda a, b: a < b, "leq": lambda a, b: a <= b, "gt": lambda a, b: a > b,
              "geq": lambda a, b: a >= b, "eq": lambda a, b: a == b, "neq": lambda a, b: a != b}


class Model:
    """A DAVE-ML model (ADH DAVEfunc form) ready to evaluate."""

    def __init__(self, d: Dict[str, Any]):
        self.vars = {v["var_id"]: v for v in d.get("variable_def") or []}
        self.by_name = {v["name"]: v["var_id"] for v in d.get("variable_def") or []}
        self.bps = {b["bp_id"]: _numbers(b["bp_vals"]) for b in d.get("breakpoint_def") or []}
        self.gtables = {g["gt_id"]: g for g in d.get("gridded_table_def") or [] if g.get("gt_id")}
        self.utables = {u["ut_id"]: u for u in d.get("ungridded_table_def") or [] if u.get("ut_id")}
        self.functions: Dict[str, Dict[str, Any]] = {}
        for f in d.get("function") or []:
            dep = f.get("dependent_var_ref") or []
            if isinstance(dep, dict):
                dep = [dep]
            if f.get("dependent_var_pts"):
                self.functions[f["dependent_var_pts"]["var_id"]] = f
            for r in dep:
                self.functions[r["var_id"]] = f
        self._math: Dict[str, ET.Element] = {}

    def var_id(self, key: str) -> str:
        if key in self.vars:
            return key
        if key in self.by_name:
            return self.by_name[key]
        raise EvalError(f"no variable with the varID or name {key!r}")

    def evaluate(self, inputs: Dict[str, float]) -> Dict[str, float]:
        """The value of every variable, for the given inputs (varID -> value)."""
        values: Dict[str, float] = dict(inputs)
        busy: set = set()

        def get(vid: str) -> float:
            if vid in values:
                return values[vid]
            if vid not in self.vars:
                raise EvalError(f"the model has no variable {vid!r}")
            if vid in busy:
                raise EvalError(f"the definition of {vid!r} is a loop")
            busy.add(vid)
            v = self.vars[vid]
            if vid in self.functions:
                x = self._function(self.functions[vid], get)
            elif (v.get("calculation") or {}).get("math"):
                x = float(self._apply(self._math_of(vid), get))
            elif v.get("initial_value") is not None:
                x = float(v["initial_value"])
            else:
                raise EvalError(f"the variable {vid!r} has no input, function, calculation or initialValue")
            lo, hi = v.get("min_value"), v.get("max_value")
            if lo is not None:
                x = max(x, float(lo))
            if hi is not None:
                x = min(x, float(hi))
            busy.discard(vid)
            values[vid] = x
            return x

        for vid in self.vars:
            get(vid)
        return values

    # ---------------------------------------------------------------------------------------------------- MathML
    def _math_of(self, vid: str) -> ET.Element:
        if vid not in self._math:
            root = ET.fromstring(self.vars[vid]["calculation"]["math"])
            kids = list(root)
            if len(kids) != 1:
                raise EvalError(f"{vid}: <math> must hold one expression")
            self._math[vid] = kids[0]
        return self._math[vid]

    def _apply(self, e: ET.Element, get) -> float:
        t = _tag(e)
        if t == "ci":
            return get((e.text or "").strip())
        if t == "cn":
            return _cn(e)
        if t == "pi":
            return math.pi
        if t == "exponentiale":
            return math.e
        if t in ("true", "false"):
            return float(t == "true")
        if t == "piecewise":
            return self._piecewise(e, get)
        if t != "apply":
            raise EvalError(f"MathML <{t}> is not supported")
        kids = list(e)
        if not kids:
            raise EvalError("empty <apply>")
        op, args = kids[0], kids[1:]
        name = _tag(op)
        if name == "piecewise" and not args:
            return self._piecewise(op, get)
        if name == "csymbol":
            sym = (op.text or "").strip()
            vals = [self._apply(a, get) for a in args]
            if sym == "atan2" and len(vals) == 2:
                return math.atan2(vals[0], vals[1])
            raise EvalError(f"MathML csymbol {sym!r} is not supported")
        if name in ("and", "or", "xor"):
            vals = [bool(self._apply(a, get)) for a in args]
            if name == "and":
                return float(all(vals))
            if name == "or":
                return float(any(vals))
            return float(sum(vals) % 2 == 1)
        if name == "root":
            degree = 2.0
            rest = []
            for a in args:
                if _tag(a) == "degree":
                    degree = self._apply(list(a)[0], get)
                else:
                    rest.append(a)
            return self._apply(rest[0], get) ** (1.0 / degree)
        if name == "log":
            base = 10.0
            rest = []
            for a in args:
                if _tag(a) == "logbase":
                    base = self._apply(list(a)[0], get)
                else:
                    rest.append(a)
            return math.log(self._apply(rest[0], get), base)
        vals = [self._apply(a, get) for a in args]
        if name == "plus":
            return float(sum(vals))
        if name == "minus":
            return -vals[0] if len(vals) == 1 else vals[0] - vals[1]
        if name == "times":
            return float(np.prod(vals))
        if name == "divide":
            return vals[0] / vals[1]
        if name == "power":
            return vals[0] ** vals[1]
        if name == "quotient":
            return float(math.trunc(vals[0] / vals[1]))
        if name == "rem":
            return math.fmod(vals[0], vals[1])
        if name == "min":
            return min(vals)
        if name == "max":
            return max(vals)
        if name in _UNARY and len(vals) == 1:
            return float(_UNARY[name](vals[0]))
        if name in _RELATIONS and len(vals) == 2:
            return float(_RELATIONS[name](vals[0], vals[1]))
        raise EvalError(f"MathML <{name}> with {len(vals)} arguments is not supported")

    def _piecewise(self, e: ET.Element, get) -> float:
        otherwise = None
        for p in e:
            t = _tag(p)
            if t == "piece":
                value, cond = list(p)
                if self._apply(cond, get):
                    return self._apply(value, get)
            elif t == "otherwise":
                otherwise = list(p)[0]
        if otherwise is None:
            raise EvalError("<piecewise>: no piece is true and there is no <otherwise>")
        return self._apply(otherwise, get)

    # ---------------------------------------------------------------------------------------------------- tables
    def _function(self, f: Dict[str, Any], get) -> float:
        if f.get("independent_var_pts"):
            pts = f["independent_var_pts"]
            pts = pts if isinstance(pts, list) else [pts]
            if len(pts) != 1:
                raise EvalError(f"function {f.get('name')}: inline points of more than one input")
            ip = pts[0]
            x = get(ip["var_id"])
            xs, ys = _numbers(ip["value"]), _numbers(f["dependent_var_pts"]["value"])
            return _interp1(xs, ys, x, ip.get("extrapolate"), ip.get("interpolate"))
        refs = f.get("independent_var_ref") or []
        defn = f.get("function_defn") or {}
        table = defn.get("gridded_table_def")
        if defn.get("gridded_table_ref"):
            gid = defn["gridded_table_ref"]["gt_id"]
            if gid not in self.gtables:
                raise EvalError(f"function {f.get('name')}: no griddedTableDef {gid!r}")
            table = self.gtables[gid]
        if table is None and (defn.get("ungridded_table_def") or defn.get("ungridded_table_ref")):
            return self._ungridded(f, refs, defn, get)
        if table is None:
            raise EvalError(f"function {f.get('name')}: no table")
        grids = [self.bps[b["bp_id"]] for b in table["breakpoint_refs"]]
        if len(grids) != len(refs):
            raise EvalError(f"function {f.get('name')}: {len(refs)} inputs for {len(grids)} breakpoint sets")
        data = _numbers(table["data_table"]["value"])
        shape = tuple(len(g) for g in grids)
        if data.size != int(np.prod(shape)):
            raise EvalError(f"table {table.get('gt_id') or table.get('name')}: {data.size} values, {shape} expected")
        data = data.reshape(shape)
        xs = []
        for r in refs:
            x = get(r["var_id"])
            if r.get("min") is not None:
                x = max(x, float(r["min"]))
            if r.get("max") is not None:
                x = min(x, float(r["max"]))
            xs.append(x)
        return _interpn(grids, data, xs, [r.get("extrapolate") for r in refs], [r.get("interpolate") for r in refs])

    def _ungridded(self, f, refs, defn, get) -> float:
        t = defn.get("ungridded_table_def")
        if defn.get("ungridded_table_ref"):
            t = self.utables[defn["ungridded_table_ref"]["ut_id"]]
        if len(refs) != 1:
            raise EvalError(f"function {f.get('name')}: an ungridded table of {len(refs)} inputs is not supported")
        pts = np.array([_numbers(p["value"]) for p in t["data_point"]])
        order = np.argsort(pts[:, 0])
        return _interp1(pts[order, 0], pts[order, 1], get(refs[0]["var_id"]), refs[0].get("extrapolate"), None)


def _bracket(g: np.ndarray, x: float, extrapolate: Optional[str], interpolate: Optional[str]) -> List[Tuple[int, float]]:
    """(index, weight) pairs of one axis."""
    n = len(g)
    if n == 1:
        return [(0, 1.0)]
    lo_ok = extrapolate in ("min", "both")
    hi_ok = extrapolate in ("max", "both")
    if x <= g[0] and not lo_ok:
        return [(0, 1.0)]
    if x >= g[-1] and not hi_ok:
        return [(n - 1, 1.0)]
    k = int(np.clip(np.searchsorted(g, x, side="right") - 1, 0, n - 2))
    t = (x - g[k]) / (g[k + 1] - g[k])
    if interpolate == "floor":
        return [(k if t < 1.0 else k + 1, 1.0)]
    if interpolate == "ceiling":
        return [(k + 1 if t > 0.0 else k, 1.0)]
    if interpolate == "discrete":
        return [(k if t < 0.5 else k + 1, 1.0)]
    return [(k, 1.0 - t), (k + 1, t)]


def _interpn(grids, data, xs, extrap, interp) -> float:
    axes = [_bracket(g, x, e, i) for g, x, e, i in zip(grids, xs, extrap, interp)]
    total = 0.0

    def walk(level, idx, w):
        nonlocal total
        if level == len(axes):
            total += w * data[tuple(idx)]
            return
        for i, wi in axes[level]:
            if wi != 0.0:
                walk(level + 1, idx + [i], w * wi)

    walk(0, [], 1.0)
    return float(total)


def _interp1(xs, ys, x, extrapolate, interpolate) -> float:
    return _interpn([np.asarray(xs, float)], np.asarray(ys, float), [x], [extrapolate], [interpolate])


@dataclass
class ShotResult:
    name: str
    outputs: List[Tuple[str, float, float, float]] = field(default_factory=list)   # (var, expected, got, tol)
    faults: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.faults


def _signals(block: Any) -> List[Dict[str, Any]]:
    if not block:
        return []
    sig = block.get("signal") if isinstance(block, dict) else block
    return sig if isinstance(sig, list) else [sig]


def run_check_data(d: Dict[str, Any]) -> List[ShotResult]:
    """Run every static shot of the checkData of a model (ADH DAVEfunc form)."""
    model = Model(d)
    shots = (d.get("check_data") or {}).get("static_shot") or []
    out = []
    for shot in shots:
        res = ShotResult(shot.get("name", "?"))
        inputs = {}
        for s in _signals(shot.get("check_inputs")):
            vid = model.var_id(s.get("var_id") or s.get("signal_name"))
            units = model.vars[vid].get("units")
            if s.get("signal_units") and units and s["signal_units"] != units:
                raise EvalError(f"shot {res.name}: input {vid} in {s['signal_units']}, the variable is in {units}")
            inputs[vid] = float(s["signal_value"])
        values = model.evaluate(inputs)
        tols = []
        for s in _signals(shot.get("check_outputs")):
            vid = model.var_id(s.get("var_id") or s.get("signal_name"))
            units = model.vars[vid].get("units")
            if s.get("signal_units") and units and s["signal_units"] != units:
                raise EvalError(f"shot {res.name}: output {vid} in {s['signal_units']}, the variable is in {units}")
            want, got = float(s["signal_value"]), values[vid]
            tol = float(s["tol"]) if s.get("tol") is not None else 0.0
            tols.append(tol)
            res.outputs.append((vid, want, got, tol))
            if not abs(got - want) <= tol:
                res.faults.append(f"{vid} = {got!r}, expected {want!r} +/- {tol}")
        itol = min(tols) if tols else 0.0
        for s in _signals(shot.get("internal_values")):
            vid = model.var_id(s.get("var_id") or s.get("signal_name"))
            want, got = float(s["signal_value"]), values[vid]
            if not abs(got - want) <= max(itol, 1e-9 * abs(want)):
                res.notes.append(f"internal {vid} = {got!r}, listed {want!r}")
        out.append(res)
    return out
