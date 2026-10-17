"""
Faster derivatives for the Rosella BEMT rotor states (trial, setting solver.bemt_kernel: fast).

Proptimiser PropellerModel.add_to builds one full MX graph for each rotor state. At L4 there are 10 copies, and CasADi
spends 99.7 % of the solve time on their Jacobian and Hessian. This file keeps the Proptimiser code as it is and changes
only how Rosella calls it. Two parts, which can be used apart:

  shared  One cas.Function for each blade model (inputs: inflow ratios, omega, V, scale), built once with CSE and
          called at every state. The identity matrices E_r and M_psi (n_psi = 1) and the station selector become sparse,
          so the derivatives stay block diagonal for each station.
  nf      The NeuralFoil MLP for ONE point as an SX Function (about 100 k nodes), called with map() over the points.
          The 18 section inputs of a station are constants. Nothing builds an SX graph of the whole BEMT state: that
          needs about 10 M nodes for each copy and more than 18 GB.

MODE is "shared", "nf" or "both". The environment variable AEROPLAN_FAST_BEMT sets it for a trial.
Units: SI. Angles are radians.
"""
import copy
import dataclasses
import os
from types import SimpleNamespace

import casadi as cas
import numpy as np

MODE = os.environ.get("AEROPLAN_FAST_BEMT", "shared")

_KERNEL = {}      # (id(interpolator)) -> SX point function
_MODEL = {}       # (id(model), mode) -> patched model
_SHARED = {}      # (id(patched model), thrust scale) -> (Function, n unknowns)


def _sparse(matrix):
    """A sparse DM of a dense 0/1 matrix (zeros are not stored)."""
    return cas.sparsify(cas.DM(np.asarray(matrix, dtype=float)))


def _point_kernel(nfi):
    """
    SX Function (alpha, re, xc) -> (CL, CD, CM, log confidence) of ONE point for the NeuralFoil interpolator nfi.
    xc (18) is the constant part of the network input: upper weights, lower weights, LE weight, 50 * TE thickness.
    The body is NeuralFoilInterpolator.raw for one row.
    """
    key = id(nfi)
    if key in _KERNEL:
        return _KERNEL[key]
    a, re, xc = cas.SX.sym("alpha"), cas.SX.sym("re"), cas.SX.sym("xc", 18)
    x = cas.vertcat(xc, cas.sin(2 * a), cas.cos(a), 1 - cas.cos(a) ** 2, (cas.log(re) - 12.5) / 3.5, 0.0, 1.0, 1.0).T
    n_in = nfi.N_inputs
    p = nfi.nn_params
    mean = nfi._scaled_input_distribution["mean_inputs_scaled"]
    inv_cov = nfi._scaled_input_distribution["inv_cov_inputs_scaled"]

    def net(v):
        for n, i in enumerate(nfi.layer_indices):
            v = cas.mtimes(v, p[f"net.{i}.weight"].T) + p[f"net.{i}.bias"].reshape(1, -1)
            if n < len(nfi.layer_indices) - 1:
                v = v / (1.0 + cas.exp(-v))
        return v

    def mahal(v):
        d = v - mean.reshape(1, -1)
        return cas.sum2(cas.mtimes(d, inv_cov) * d)

    xf = cas.mtimes(x, nfi._mirror)
    y, yf = net(x), net(xf)
    logit = ((y[0] - mahal(x) / (2 * n_in)) + (yf[0] - mahal(xf) / (2 * n_in))) / 2
    cl = (y[1] - yf[1]) / 2 / 2
    cd = cas.exp(((y[2] + yf[2]) / 2 - 2) * 2)
    cm = (y[3] - yf[3]) / 2 / 20
    logc = -(cas.fmax(-logit, 0.0) + cas.log1p(cas.exp(-cas.fabs(logit))))
    _KERNEL[key] = cas.Function("nf_point", [a, re, xc], [cl, cd, cm, logc])
    return _KERNEL[key]


class MappedInterpolator:
    """The airfoil interpolator of Proptimiser with `raw` on a mapped SX kernel when the inputs are CasADi expressions."""

    def __init__(self, nfi):
        self._nfi = nfi

    def __getattr__(self, name):
        return getattr(self._nfi, name)

    def raw(self, alpha, re, kulfan, xp=None):
        if getattr(xp, "name", "") != "casadi" or not isinstance(alpha, (cas.MX, cas.SX)):
            return self._nfi.raw(alpha, re, kulfan, xp)
        kern = _point_kernel(self._nfi)
        k = np.asarray(kulfan, dtype=float)
        n = k.shape[0]
        xc = np.concatenate([k[:, 8:16], k[:, 0:8], k[:, 16:17], k[:, 17:18] * 50.0], axis=1).T      # (18, n)
        out = kern.map(n)(alpha.T, re.T if isinstance(re, (cas.MX, cas.SX)) else np.reshape(re, (1, -1)), xc)
        return tuple(o.T for o in out)

    def __call__(self, *args, **kw):
        return type(self._nfi).__call__(self, *args, **kw)


def patched_model(model, mode=None):
    """A copy of the PropellerModel with sparse selector matrices (mode shared, both) and the mapped SX NeuralFoil (nf, both)."""
    mode = mode or MODE
    key = (id(model), mode)
    if key in _MODEL:
        return _MODEL[key]
    m = copy.copy(model)
    base = model._base
    changes = {}
    if mode in ("shared", "both"):
        changes.update(E_r=_sparse(np.asarray(base.E_r)), M_psi=_sparse(np.asarray(base.M_psi)))
        m._embed = _sparse(model._embed)
    if mode in ("nf", "both"):
        changes["airfoil_interp"] = MappedInterpolator(base.airfoil_interp)
    m._base = dataclasses.replace(base, **changes)
    _MODEL[key] = (m, model)         # keep the original alive so that id() stays unique
    return _MODEL[key]


def _shared_function(m, ts):
    key = (id(m), ts)
    if key not in _SHARED:
        n = m.n_solved * m.n_aero
        lam, w, V, s = cas.MX.sym("lam", n), cas.MX.sym("w"), cas.MX.sym("V"), cas.MX.sym("s")
        e = m.expressions(cas.reshape(lam, m.n_solved, m.n_aero), w, V, 0.0, ts, scale=s)
        f = cas.Function("bemt", [lam, w, V, s], [cas.vec(e.residual), e.thrust_N, e.torque_Nm, e.shaft_power_W],
                         {"cse": True})
        _SHARED[key] = (f, n)
    return _SHARED[key]


def add_to(model, opti, omega, V, thrust_scale_N, scale=1.0, mode=None):
    """The same as model.add_to(opti, omega, V, 0.0, thrust_scale_N, scale=scale), with the changes above."""
    mode = mode or MODE
    m = patched_model(model, mode)[0]
    if mode == "nf":
        return m.add_to(opti, omega, V, 0.0, thrust_scale_N, scale=scale)
    f, n = _shared_function(m, thrust_scale_N)
    flat = opti.variable(init_guess=np.ones(n))
    res, T, Q, P = f(flat, omega, V, scale)
    opti.subject_to(res == 0)
    return SimpleNamespace(thrust_N=T, torque_Nm=Q, shaft_power_W=P, variable=flat)
