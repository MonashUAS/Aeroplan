"""
The result of a solve, and a snapshot of one iterate.

    Result     the numbers of one solved (or failed) problem: design values, masses, the outputs of every flight condition,
               every constraint with its margin and its cost, the status, the ladder rows. Read and written as JSON.
    Snapshot   a few numbers of one IPOPT iterate (design values, energy, mass, largest violation). The solver gives one to the
               plotter at each iteration. The plotter never calls the solver (plot.py reads a Result, a Snapshot or a model).

A constraint of the report is {value, lo, hi, group, enabled, scale, equality, margin, dual_scaled, cost_Wh_per_unit}.
`margin` is the fraction by which a limit holds: positive holds, negative is violated. `cost_Wh_per_unit` is the energy
(Wh) that one more unit of the limit costs, from the multiplier of IPOPT.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

OK_STATUS = ("ok", "acceptable")


def margin(c: Dict[str, Any]) -> float:
    """Fractional margin of a constraint: positive means it holds."""
    v, lo, hi = c["value"], c["lo"], c["hi"]
    m = []
    if hi is not None and not isinstance(hi, str):
        m.append((hi - v) / max(abs(hi), 1e-9))
    if lo is not None and not isinstance(lo, str):
        m.append((v - lo) / max(abs(lo), 1e-9))
    return min(m) if m else float("nan")


def passes(c: Dict[str, Any]) -> bool:
    """True when a constraint of the report holds: margin >= -1e-6 (inequality) or >= -1e-4 (equality)."""
    return bool(c["margin"] >= (-1e-4 if c.get("equality") else -1e-6))


@dataclass
class Snapshot:
    """One iterate of the solve. `design` has the design values (keys of model.DESIGN_VARS), `mass_kg` and `energy_Wh` the
    objective terms, `violation` the largest scaled violation of an enabled limit (0 when feasible)."""
    iteration: int
    design: Dict[str, float]
    mass_kg: float = float("nan")
    energy_Wh: float = float("nan")
    violation: float = float("nan")
    extra: Dict[str, float] = field(default_factory=dict)


class Result:
    """A report dict with the helpers the notebooks and the plotter need."""

    def __init__(self, data: Dict[str, Any]):
        self.data = data

    def __getitem__(self, k: str) -> Any:
        return self.data[k]

    def get(self, k: str, default: Any = None) -> Any:
        return self.data.get(k, default)

    @property
    def ok(self) -> bool:
        return bool(self.data.get("ok", self.data.get("converged", False)))

    @property
    def design(self) -> Dict[str, float]:
        return self.data["design"]

    @property
    def energy_Wh(self) -> float:
        return self.data["energy_total_Wh"]

    @property
    def mass_kg(self) -> float:
        return self.data["names"]["M"]

    @property
    def constraints(self) -> Dict[str, Dict[str, Any]]:
        return self.data["constraints"]

    def enabled(self) -> Dict[str, Dict[str, Any]]:
        return {k: c for k, c in self.constraints.items() if c["enabled"] and not c["equality"]}

    def worst(self, n: int = 5) -> List[Tuple[str, float]]:
        """The n enabled inequalities with the smallest margin."""
        return sorted(((k, c["margin"]) for k, c in self.enabled().items()), key=lambda r: r[1])[:n]

    def active(self, tol: float = 1e-3) -> List[str]:
        return [k for k, c in self.enabled().items() if c["margin"] < tol]

    def violated(self) -> List[str]:
        return [k for k, c in self.enabled().items() if not passes(c)]

    def energy_by_segment(self) -> Dict[str, float]:
        return dict(self.data["energy_Wh"])

    def mass_by_item(self) -> Dict[str, float]:
        """Mass (kg) of each item of the mass list, summed by name."""
        out: Dict[str, float] = {}
        for it in self.data["items"]:
            out[it["name"]] = out.get(it["name"], 0.0) + it["mass_kg"]
        return out

    def summary(self) -> Dict[str, Any]:
        """A short record for the aircraft file: status, mass, energy, design, the active limits."""
        d = self.data
        return {"case": f"{d['config']}_{d['cells_s']}S", "level": d.get("level_reached", d.get("level")),
                "status": d.get("status_word"), "mass_kg": self.mass_kg, "energy_Wh": self.energy_Wh,
                "energy_nominal_Wh": d["energy_nominal_Wh"], "rotor_diameter_m": d["D_m"], "design": dict(self.design),
                "active": self.active(), "f1_Hz": d["f1_Hz"], "f2_Hz": d["f2_Hz"], "f_hover_1P_Hz": d["f_hover_1P_Hz"]}

    def compact(self) -> Dict[str, Any]:
        """The part of the report that the spoke reads into the aircraft source tree (settings/<aircraft>.json): the design, the
        names, the items, the rotor states, the energy, the structure and control numbers, and each constraint without its
        solver detail. The ladder rows, the multistart log, the slacks and the motor fit are left out."""
        d = self.data
        keep = ("config", "cells_s", "converged", "ok", "error", "status_word", "level", "level_reached", "design", "R_m", "D_m", "names",
                "c_ref_m", "boom_z_m", "rotor_z_m", "spacing_m", "boom_material", "pitch_m", "pitch_note", "energy_Wh", "energy_total_Wh",
                "energy_nominal_Wh", "time_s", "inertia_kg_m2", "control", "cruise", "cda_m2", "P_battery_W", "I_battery_max_A",
                "V_bus_max_V", "f1_Hz", "f1_exact_Hz", "f2_Hz", "f2_no_J_Hz", "boom_J_tip_kg_m2", "f_hover_1P_Hz", "structure", "rotors", "items", "airframe", "placeholders")
        out = {k: d[k] for k in keep if k in d}
        out["case"] = f"{d['config']}_{d['cells_s']}S"
        out["constraints"] = {k: {f: c.get(f) for f in ("value", "lo", "hi", "group", "enabled", "equality", "margin", "cost_Wh_per_unit")
                                  if c.get(f) is not None} for k, c in d["constraints"].items()}
        return out

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.data, indent=1, default=float), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "Result":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(d.get("result", d))
