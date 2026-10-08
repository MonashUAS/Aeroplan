"""Flow5 adapter: a sweep folder in, point datasets out (brief section 7, step 8; P4).

Input: one folder written by an Aerolink `sweep run` (flow5 7.57): polar text files (`*.csv`, fixed-width text,
no commas), `results.json`, and the plane XML that flow5 analysed (`plane_with_body.xml`).
Output for each polar: `manifest.json` (AeroPointManifest) and `points.parquet`.

Facts used here, and where each comes from. Nothing else is assumed.

- The polar layout (header block, welded first row, declared row count): read from the files, same traps as in
  the Aerolink CLAUDE.md.
- The Cl and Cn columns use flow5 axes (x aft, z up) and have the opposite sign of the aeronautical moments.
  Source: Aerolink `flow5/polar.py` docstring ("verified on 7.57 with a dihedral wing"). NOT re-verified here.
- Moments are about the CoG of the polar header. Source: Aerolink CLAUDE.md ("derivatives about the CoG").
  NOT confirmed against flow5 documentation. See docs/source/currawong/missing_data.md, item M-05.
- Control deflection = lo + Ctrl * (hi - lo), with lo and hi from the first nonzero `Range_k` header line.
  Source: Aerolink `control_derivatives`. The sign of a positive flow5 flap is NOT verified.
- No uncertainty estimate exists in the source. Every dataset gets status "unavailable" (NASA-STD-7009B [M&S 33] c).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..config import canonical_json
from ..muas.dataset import AeroPointManifest
from .base import Adapter

_GREEK = {"α": "alpha", "β": "beta", "φ": "phi"}
_COUNT = re.compile(r"Nbr\. of data points\s*=\s*(\d+)")
_RANGE = re.compile(r"^\s*(Range_\d+):\s+([-+\d.eE]+),\s+([-+\d.eE]+)")
_SPEED = re.compile(r"Freestream speed\s*=\s*([-+\d.eE]+)\s*m/s")

#: polar column -> (id, name, units, axis_system, sign, is_moment)
OUTPUTS = {
    "CL": ("CL", "liftCoefficient", "nd", "wind", "lift positive up", False),
    "CD": ("CD", "dragCoefficient", "nd", "wind", "drag positive aft", False),
    "CY": ("CY", "sideForceCoefficient", "nd", "wind", "flow5 sign, not verified", False),
    "Cm": ("Cm", "pitchingMomentCoefficient", "nd", "design", "nose-up positive (flow5 axes: rotation about +y)", True),
    "Cl": ("Cl", "rollingMomentCoefficient", "nd", "design",
           "flow5 axes (x aft, z up): OPPOSITE sign of aeronautical roll. Stored as written by flow5", True),
    "Cn": ("Cn", "yawingMomentCoefficient", "nd", "design",
           "flow5 axes (x aft, z up): OPPOSITE sign of aeronautical yaw. Stored as written by flow5", True),
}
CONTROL_NAMES = {"elevator": "elevatorDeflection", "aileron": "aileronDeflection", "rudder": "rudderDeflection"}


class PolarError(ValueError):
    """The polar file is malformed or incomplete."""


@dataclass
class Polar:
    path: Path
    columns: List[str]
    data: np.ndarray
    ranges: List[Tuple[str, float, float]]
    declared: Optional[int]
    speed: Optional[float]

    def col(self, name: str) -> np.ndarray:
        try:
            return self.data[:, self.columns.index(name)]
        except ValueError:
            raise PolarError(f"{self.path.name}: no column {name!r}") from None


def _num(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _label(s: str) -> str:
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s.strip())
    return _GREEK.get(s, s)


def parse_polar_text(text: str, path: Path = Path("polar")) -> Polar:
    """Parse one flow5 polar. Refuses a file whose row count differs from the count the file declares."""
    lines = text.split("\n")
    head_i = next((i for i, ln in enumerate(lines) if "Ctrl" in ln and "CL" in ln and "CD" in ln), None)
    if head_i is None:
        raise PolarError(f"{path.name}: no polar table header")
    declared = speed = None
    ranges: List[Tuple[str, float, float]] = []
    for ln in lines[:head_i]:
        if m := _COUNT.search(ln):
            declared = int(m.group(1))
        if m := _RANGE.match(ln):
            ranges.append((m.group(1), float(m.group(2)), float(m.group(3))))
        if m := _SPEED.search(ln):
            speed = float(m.group(1))
    rows = [ln.split() for ln in lines[head_i + 1:] if ln.split() and all(_num(t) for t in ln.split())]
    width = len(rows[0]) if rows else None
    head = lines[head_i]
    tokens = [(m.start(), m.group()) for m in re.finditer(r"\S+", head)]
    k = len(tokens)
    while k > 0 and _num(tokens[k - 1][1]):  # the first data row sits on the label line
        k -= 1
    tail = tokens[k:]
    if width is not None and len(tail) > width:
        tail = tokens[len(tokens) - width:]
    label_end = tail[0][0] if tail else len(head)
    columns = [_label(x) for x in re.split(r"\s{2,}", head[:label_end].strip()) if x]
    body = ([[float(t[1]) for t in tail]] if tail else []) + [[float(t) for t in r] for r in rows]
    if any(len(r) != len(columns) for r in body):
        raise PolarError(f"{path.name}: {len(columns)} labels but rows of {sorted({len(r) for r in body})} values")
    if declared is not None and declared != len(body):
        raise PolarError(f"{path.name}: {len(body)} points found, {declared} declared. Refusing a partial polar")
    return Polar(path, columns, np.array(body, dtype=float).reshape(len(body), len(columns)), ranges, declared, speed)


def control_range(polar: Polar) -> Tuple[float, float, bool]:
    """The deflection range of a T6 polar: (lo, hi, antisymmetric).

    Every nonzero `Range_k` must equal the first one or be its exact reverse (the two ailerons move in
    opposite directions, so the second range runs from +15 to -15). The first nonzero range is the reference.
    `antisymmetric` is True when a reversed range exists.
    """
    nz = [(lo, hi) for _, lo, hi in polar.ranges if lo != hi]
    if not nz:
        raise PolarError(f"{polar.path.name}: no nonzero Range in the header")
    lo, hi = nz[0]
    for r in nz[1:]:
        if r not in ((lo, hi), (hi, lo)):
            raise PolarError(f"{polar.path.name}: ranges {nz} are neither equal nor reversed")
    return lo, hi, any(r == (hi, lo) for r in nz[1:])


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Flow5SweepAdapter(Adapter):
    name = "flow5"
    produces = ("aero_point",)

    def __init__(self, config_id: str, mass_properties_sha256: Optional[str] = None):
        self.config_id = config_id
        self.mass_sha = mass_properties_sha256

    def ingest(self, source: Path, out_dir: Path) -> List[Path]:
        src, out = Path(source), Path(out_dir)
        results = json.loads((src / "results.json").read_text(encoding="utf-8"))
        inp = results["inputs"]
        plane = src / "plane_with_body.xml"
        if not plane.is_file():
            raise FileNotFoundError(f"{plane} is missing: the geometry hash needs the analysed plane")
        written: List[Path] = []
        for csv in sorted(src.glob("*.csv")):
            polar = parse_polar_text(csv.read_text(encoding="utf-8", errors="replace"), csv)
            if csv.stem == "t7_reference":
                continue  # one trim point, kept as a raw check value, not a dataset
            written += self._write(polar, csv, results, inp, plane, out)
        return written

    def _write(self, polar: Polar, csv: Path, results: dict, inp: dict, plane: Path, out: Path) -> List[Path]:
        stem = csv.stem
        control = stem if stem in CONTROL_NAMES else None
        finite = np.isfinite(polar.data).all(axis=1)
        dropped = int((~finite).sum())
        d = {c: polar.col(c)[finite] for c in polar.columns}
        n = int(finite.sum())
        if n == 0:
            raise PolarError(f"{csv.name}: no finite rows")

        def fixed(col: str) -> float:
            v = d[col]
            if not np.allclose(v, v[0], rtol=0, atol=1e-9):
                raise PolarError(f"{csv.name}: column {col} varies but the sweep type says it is fixed")
            return float(v[0])

        speed = fixed("V") if "V" in d else polar.speed
        if speed is None:
            raise PolarError(f"{csv.name}: no speed in the table or the header")
        cols: Dict[str, np.ndarray] = {}
        inputs = []
        notes = [
            "Fixed-width flow5 7.57 text polar, one row for each operating point. No repeats exist.",
            "Only the six force and moment coefficients are ingested. The viscous, induced and pressure parts stay in the raw file.",
        ]
        for col, name, units in (("alpha", "angleOfAttack", "deg"), ("beta", "angleOfSideslip", "deg"),
                                 ("phi", "bankAngle", "deg")):
            v = d[col]
            cols[col] = v
            lo, hi = float(v.min()), float(v.max())
            inputs.append({"name": name, "id": col, "units": units,
                           **({"range": [lo, hi]} if hi > lo else {"fixed": lo})})
        cols["V"] = np.full(n, speed)
        inputs.append({"name": "trueAirspeed", "id": "V", "units": "m/s", "fixed": speed})
        term = "static"
        if control:
            lo, hi, anti = control_range(polar)
            cols["Ctrl"] = d["Ctrl"]
            cols["delta"] = lo + d["Ctrl"] * (hi - lo)
            inputs.append({"name": CONTROL_NAMES[control], "id": "delta", "units": "deg",
                           "range": [float(cols["delta"].min()), float(cols["delta"].max())]})
            term = "control"
            if anti:
                notes.append("Two flaps move in opposite directions (the second Range runs from "
                             f"{hi:g} to {lo:g}). Deflection is that of the first flap.")
            notes.append(
                f"Deflection = {lo:g} + Ctrl * ({hi:g} - ({lo:g})) in degrees (Aerolink convention). "
                "The sign of a positive flow5 flap is NOT verified. Aerolink flips its fit so that the elevator "
                "Cmde is negative. Treat the sign as unconfirmed (missing data M-06).")
        outputs = []
        for col, (oid, oname, units, axis, sign, is_moment) in OUTPUTS.items():
            cols[oid] = d[col]
            outputs.append({"name": oname, "id": oid, "units": units, "axis_system": axis,
                            "sign": sign, "is_moment": is_moment})
        if dropped:
            notes.append(f"{dropped} row(s) with non-finite values were dropped (flow5 lost points).")
        if "viscous" in stem:
            notes.append("Viscous analysis. Inviscid and viscous sets are both ingested as candidates. "
                         "The choice for the composed model is open (missing data M-09).")

        ds_id = f"aero.flow5.{stem}.{self.config_id}"
        created = results.get("created_utc", "")
        manifest = AeroPointManifest(
            dataset_id=ds_id, role="nominal", term=term, config_id=self.config_id,
            geometry_hash=sha256_file(plane), fidelity="L2", source_tool="flow5",
            inputs=inputs, outputs=outputs,
            reference={"s_ref_m2": inp["S"], "b_ref_m": inp["b"], "c_ref_m": inp["cbar"],
                       "mrp": {"config_id": self.config_id, "point": {"xyz": inp["cg"]},
                               **({"mass_properties_sha256": self.mass_sha} if self.mass_sha else {})}},
            uncertainty={"status": "unavailable", "scope": "result",
                         "basis": "No uncertainty estimate exists in the source. flow5 is deterministic, the sweep has no repeats, "
                                  "and Aerolink records only a linearity residual and a self-consistency check."},
            processing={"binning": "none: flow5 operating points", "n_raw": len(polar.data), "n_points": n},
            provenance={"tool": "flow5", "tool_version": str(results.get("flow5", "unknown")),
                        "author": "unknown (not recorded in the source)",
                        "created": created.replace("+00:00", "") or datetime(1970, 1, 1).isoformat(),
                        "input_sha256": sha256_file(csv), "geometry_hash": sha256_file(plane),
                        "config_id": self.config_id, "method": f"{polar.path.name} from sweep {results.get('name')}"},
            notes=notes,
        )
        ds_dir = out / ds_id
        ds_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(cols).to_parquet(ds_dir / "points.parquet", index=False)
        (ds_dir / "manifest.json").write_text(canonical_json(json.loads(manifest.model_dump_json())), encoding="utf-8")
        return [ds_dir / "manifest.json", ds_dir / "points.parquet"]
