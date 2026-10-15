"""flow5 sweep runner: write the flow5 script and the polar XML files, run flow5 headless in two passes, check the runs
against each other and write the sweep folder that `ingest` reads (results.json holds the validation).

Hand port (2026-10-15) of the retired Aerolink runner (Aerolink 3ece436^: src/aerolink/sweep.py, flow5/script.py,
flow5/polar.py). The flow5 script dialect comes from there. Facts that shape the code (NOT re-verified here):
  - A script runs only planes read from `plane_definition_xml_dir`. The `.fl5` project is loaded for its foils
    (flap hinges live in the project foils).
  - flow5 skips unknown XML elements without a message. The tests parse the XML back.
  - The script ranges (T12, T5, T6, T7) apply to every polar of that type in the script.
  - Pass 1 is the T7 run (trim point and stability derivatives). Pass 2 is T1, T5 and T6 at the trim speed and angle.

Validation (the runs against each other, no GUI export):
    CL_trim = W / (q S)    T7 Cma = dCm/dalpha of T1    T7 Cnb = dCn/dbeta of T5    T7 NP_x = NP of T1
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

import numpy as np

from aeroplan.adapters.flow5 import Polar, PolarError, parse_polar_text
from aeroplan.adapters.flow5_geometry import read_plane, read_t7_scalars

METHODS = ("LLT", "VLM1", "VLM2", "QUADS", "TRIUNIFORM", "TRILINEAR")
POLAR_TYPES = {"T1": "FIXEDSPEEDPOLAR", "T5": "BETAPOLAR", "T6": "CONTROLPOLAR", "T7": "STABILITYPOLAR"}
G, RHO = 9.81, 1.225                                    # flow5 uses g = 9.81 and rho = 1.225
TOLERANCE = {"CL_trim": 0.01, "Cma": 0.05, "Cnb": 0.05}  # relative
NP_TOLERANCE_M = 0.003
_UNITS = """  <Units>
    <meter_to_length_unit>1.0</meter_to_length_unit>
    <kg_to_mass_unit>1.0</kg_to_mass_unit>
    <ms_to_speed_unit>1.0</ms_to_speed_unit>
    <m2_to_area_unit>1.0</m2_to_area_unit>
    <kgm2_to_inertia_unit>1.0</kgm2_to_inertia_unit>
  </Units>"""
_FATAL = ("Error reading script", "not an xml readable script", "Error making directories",
          "Could not open the project file", "Error reading the project file", "failed to load the file",
          "foils not found", "missing foil", "error reading the plane analysis file",
          "Unsuccessful attempt to trim", "no operating points defined")
_LOST = ("Error generating the operating point", "OTF failures")   # XFoil fails near stall: a warning
# polar column of each control derivative. Positive direction: elevator trailing edge down (Cmde < 0), aileron rolls
# right (Clda > 0), rudder trailing edge left (CYdr > 0).
CONTROL_COEFS = {"elevator": {"CLde": "CL", "Cmde": "Cm"}, "aileron": {"Clda": "Cl", "Cnda": "Cn"},
                 "rudder": {"CYdr": "CY", "Cldr": "Cl", "Cndr": "Cn"}}
POSITIVE_DIRECTION = {"elevator": ("Cmde", -1.0), "aileron": ("Clda", 1.0), "rudder": ("CYdr", 1.0)}
_FLOW5_AXES = ("Cl", "Cn")      # polar columns whose sign flips to reach aeronautical axes


class Flow5Error(RuntimeError):
    """flow5 is missing, crashed or rejected the script, or the sweep inputs are not usable."""


# ------------------------------------------------------------------------------------------------ script and polars
@dataclass
class PolarSpec:
    """One plane polar (analysis) as xflPlanePolar XML. SI units, angles in degrees."""

    name: str
    plane: str
    kind: str                                   # T1, T5, T6 or T7
    ref_area: float
    ref_span: float
    ref_chord: float
    mass: float
    cg: Tuple[float, float, float]
    inertia: Tuple[float, float, float, float]  # Ixx, Iyy, Izz, Ixz about the CoG
    speed: Optional[float] = None
    alpha_deg: Optional[float] = None
    method: str = "TRIUNIFORM"
    thin_surfaces: bool = True
    fuselage_moments: bool = True
    viscous: bool = False
    wake: Tuple[int, float, float] = (5, 1.1, 30.0)   # panels, progression, length in chords
    angle_ranges: List[List[Tuple[float, float]]] = field(default_factory=list)  # T6: wing -> [tilt, flap1, ...]


def _flag(v: bool) -> str:
    return "true" if v else "false"


def polar_xml(p: PolarSpec) -> str:
    if p.method not in METHODS:
        raise Flow5Error(f"unknown method {p.method!r}; flow5 would silently use VLM2. Use one of {METHODS}")
    if p.kind not in POLAR_TYPES:
        raise Flow5Error(f"unknown polar type {p.kind!r}; use one of {tuple(POLAR_TYPES)}")
    nx, prog, length = p.wake
    body = [
        f"    <Polar_Name>{escape(p.name)}</Polar_Name>",
        f"    <Plane_Name>{escape(p.plane)}</Plane_Name>",
        f"    <Type>{POLAR_TYPES[p.kind]}</Type>",
        f"    <Method>{p.method}</Method>",
        f"    <Include_Fuse_Moments>{_flag(p.fuselage_moments)}</Include_Fuse_Moments>",
        f"    <Thin_Surfaces>{_flag(p.thin_surfaces)}</Thin_Surfaces>",
        (f"    <Wake><FlatPanelWake>true</FlatPanelWake><NX>{nx}</NX><ProgressionFactor>{prog}</ProgressionFactor>"
         f"<LengthFactor>{length}</LengthFactor></Wake>"),
        # CUSTOM is the only reference mode that works in script mode (PLANFORM and PROJECTED give zeros)
        ("    <Reference_Dimensions><Reference_Dimensions>CUSTOM</Reference_Dimensions>"
         f"<Reference_Area>{p.ref_area}</Reference_Area><Reference_Span_Length>{p.ref_span}</Reference_Span_Length>"
         f"<Reference_Chord_Length>{p.ref_chord}</Reference_Chord_Length>"
         "<Include_Other_Wing_Area>false</Include_Other_Wing_Area></Reference_Dimensions>"),
        (f"    <Viscous_Analysis><Is_Viscous_Analysis>{_flag(p.viscous)}</Is_Viscous_Analysis>"
         f"<XFoil_OnTheFly>{_flag(p.viscous)}</XFoil_OnTheFly><From_CL>{_flag(p.kind != 'T6')}</From_CL>"
         "<NCrit>9</NCrit></Viscous_Analysis>"),
        # false: use the inertia below. true makes flow5 compute its own, which is zero for centreline masses
        "    <Use_plane_inertia>false</Use_plane_inertia>",
    ]
    if p.kind in ("T1", "T5") and p.speed is not None:
        body.append(f"    <Fixed_Velocity>{p.speed}</Fixed_Velocity>")
    if p.kind == "T5" and p.alpha_deg is not None:
        body.append(f"    <Fixed_AOA>{p.alpha_deg}</Fixed_AOA>")
    body.append(
        f"    <Inertia><Mass>{p.mass}</Mass><CoG>{p.cg[0]}, {p.cg[1]}, {p.cg[2]}</CoG>"
        f"<CoG_Ixx>{p.inertia[0]}</CoG_Ixx><CoG_Iyy>{p.inertia[1]}</CoG_Iyy>"
        f"<CoG_Izz>{p.inertia[2]}</CoG_Izz><CoG_Ixz>{p.inertia[3]}</CoG_Ixz></Inertia>")
    if p.kind == "T6":
        body += _control_ranges(p)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE flow5>\n<xflPlanePolar version="1.0">\n{_UNITS}\n'
            "  <Polar>\n" + "\n".join(body) + "\n  </Polar>\n</xflPlanePolar>\n")


def _control_ranges(p: PolarSpec) -> List[str]:
    if p.speed is None or p.alpha_deg is None:
        raise Flow5Error(f"the T6 polar {p.name!r} needs speed and alpha_deg")
    wings = []
    for iw, ranges in enumerate(p.angle_ranges):    # flow5 reads the wing number from one trailing digit
        items = "".join(f"<Range_{k}>{lo} {hi}</Range_{k}>" for k, (lo, hi) in enumerate(ranges))
        wings.append(f"<Wing_{iw}>{items}</Wing_{iw}>")
    return [
        (f"    <Operating_range><Adjusted_velocity>false</Adjusted_velocity><Velocity>{p.speed} {p.speed}</Velocity>"
         f"<Alpha>{p.alpha_deg} {p.alpha_deg}</Alpha><Beta>0 0</Beta></Operating_range>"),
        (f"    <Inertia_range><Mass>{p.mass} {p.mass}</Mass><CoG_x>{p.cg[0]} {p.cg[0]}</CoG_x>"
         f"<CoG_z>{p.cg[2]} {p.cg[2]}</CoG_z></Inertia_range>"),
        "    <Angle_range>" + "".join(wings) + "</Angle_range>",
    ]


@dataclass
class ScriptSpec:
    project_name: str                           # flow5 writes <out>/<project_name>/<plane>/<polar>.csv
    out_dir: Path
    plane_dir: Path
    polar_dir: Path
    load_project: Optional[Path] = None
    ranges: Dict[str, Tuple[float, float, float]] = field(default_factory=dict)   # T12/T5/T6/T7 -> start, end, step
    derivatives: bool = False
    threads: int = 4


def script_xml(s: ScriptSpec) -> str:
    def d(tag: str, path: Path) -> str:
        return f"      <{tag}>{escape(Path(path).resolve().as_posix())}</{tag}>\n"

    load = (f"    <load_project_file>{escape(s.load_project.resolve().as_posix())}</load_project_file>\n"
            if s.load_project else "")
    # 12 significant digits: "%g" rounds a T6 step of 1/6 to 0.166667, and 6 steps then pass the end of the range
    rng = "".join(f"      <{k}_Range>{a:.12g}, {b:.12g}, {c:.12g}</{k}_Range>\n" for k, (a, b, c) in s.ranges.items())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xflscript>
<xflscript version="1.0">
  <Metadata>
    <make_project_file>true</make_project_file>
    <project_file_name>{escape(s.project_name)}</project_file_name>
{load}    <polar_text_output_format>csv</polar_text_output_format>
    <MultiThreading><Allow_Multithreading>true</Allow_Multithreading><max_threads>{s.threads}</max_threads></MultiThreading>
    <Directories>
{d('output_dir', s.out_dir)}{d('plane_definition_xml_dir', s.plane_dir)}{d('plane_analysis_xml_dir', s.polar_dir)}    </Directories>
  </Metadata>
  <Plane_analysis>
    <Plane_Analysis_Output>
      <make_polars_text_file>true</make_polars_text_file>
      <make_oppoints>true</make_oppoints>
      <make_oppoints_text_file>true</make_oppoints_text_file>
      <export_oppoint_Cp>false</export_oppoint_Cp>
      <export_stl_mesh>false</export_stl_mesh>
      <Compute_derivatives>{_flag(s.derivatives)}</Compute_derivatives>
    </Plane_Analysis_Output>
    <Plane_Definition_Files><Process_All_Files>true</Process_All_Files></Plane_Definition_Files>
    <Plane_Analysis_Files><Process_All_Files>true</Process_All_Files></Plane_Analysis_Files>
    <Plane_Analysis_Data>
{rng}    </Plane_Analysis_Data>
  </Plane_analysis>
</xflscript>
"""


def script_ranges(sr: Dict[str, Any], runs: List[Dict[str, Any]]) -> Dict[str, Tuple[float, float, float]]:
    """The script ranges of the polar types that `runs` use. flow5 steps a range from its start while the value stays at
    or below its end, so the T6 end is 1 plus a thousandth of a step: the last control point runs."""
    r = sr.get("ranges", {})
    types = {x["type"] for x in runs}
    out: Dict[str, Tuple[float, float, float]] = {}
    if "T1" in types:
        out["T12"] = tuple(r["alpha_deg"])
    if "T5" in types:
        out["T5"] = tuple(r["beta_deg"])
    if "T6" in types:
        step = 1.0 / (int(r["control_points"]) - 1)
        out["T6"] = (0.0, 1.0 + step * 1e-3, step)
    if "T7" in types:
        out["T7"] = (0.0, 0.0, 1.0)
    return out


# --------------------------------------------------------------------------------------------------------- flow5 run
def find_flow5(given: Optional[str] = None) -> Path:
    """flow5.exe: the given path, FLOW5_EXE, the PATH, then the newest `flow5*` folder in Program Files."""
    for cand in (given, os.environ.get("FLOW5_EXE")):
        if cand:
            p = Path(cand)
            if p.is_file():
                return p
            raise Flow5Error(f"{p} is not a file")
    on_path = shutil.which("flow5")
    if on_path:
        return Path(on_path)
    roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")), Path.home() / "Applications", Path("/opt")]
    found = [e for r in roots if r.is_dir() for f in r.glob("flow5*") for e in (f / "flow5.exe", f / "flow5") if e.is_file()]
    if not found:
        raise Flow5Error("flow5 not found. Set FLOW5_EXE or give --flow5 <path to flow5.exe>")

    def key(p: Path):
        m = re.search(r"(\d+)\.(\d+)", p.parent.name)
        return tuple(int(v) for v in m.groups()) if m else (0, 0)
    return sorted(found, key=key)[-1]


def flow5_version(exe: Path) -> str:
    out = subprocess.run([str(exe), "-v"], capture_output=True, text=True, timeout=60, check=False)
    m = re.search(r"\d+\.\d+(?:\.\d+)?", out.stdout + out.stderr)
    return m.group() if m else "unknown"


@dataclass
class RunResult:
    returncode: int
    seconds: float
    log: str
    pairs: Optional[int] = None
    problems: List[str] = field(default_factory=list)
    lost: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.problems


def diagnose(log: str, returncode: int) -> RunResult:
    """Read the flow5 log: fatal lines, lost points and the number of analysis pairs."""
    m = re.search(r"Made (\d+) valid analysis pairs \(plane", log)
    res = RunResult(returncode, 0.0, log, int(m.group(1)) if m else None)
    for ln in log.splitlines():
        s = ln.strip()
        if any(k in s for k in _FATAL):
            if s not in res.problems:
                res.problems.append(s)
        elif any(k in s for k in _LOST):
            res.lost.append(s)
    if "Errors encountered" in log and not res.lost and not res.problems:
        res.problems.append("flow5 reported errors without naming a cause; read the log")
    if returncode != 0:
        res.problems.append(f"flow5 exited with code {returncode}")
    return res


def run_script(exe: Path, script: Path, timeout: float) -> RunResult:
    """Run `flow5 -p -s script`, save the log next to the script and diagnose it."""
    t0 = time.monotonic()
    try:
        proc = subprocess.run([str(exe), "-p", "-s", str(script)], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise Flow5Error(f"flow5 did not finish within {timeout:g} s: give a larger --timeout") from exc
    res = diagnose(proc.stdout + proc.stderr, proc.returncode)
    res.seconds = time.monotonic() - t0
    script.with_suffix(".log").write_text(res.log, encoding="utf-8")
    return res


# ----------------------------------------------------------------------------------------------------- polar results
def std(polar: Polar, name: str) -> np.ndarray:
    """A polar column with aeronautical signs (Cl and Cn flip from flow5 axes)."""
    c = polar.col(name)
    return -c if name in _FLOW5_AXES else c


def fit_slope(x: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    """Least-squares slope of y on x, and the worst residual as a fraction of the y span."""
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 3:
        raise PolarError("a slope needs at least 3 finite points")
    slope, offset = np.polyfit(x, y, 1)
    span = float(np.ptp(y))
    resid = float(np.max(np.abs(y - (slope * x + offset)))) / span if span > 0 else 0.0
    return float(slope), resid


def control_derivatives(polar: Polar, control: str, lo_deg: float, hi_deg: float) -> Dict[str, Dict[str, float]]:
    """Fit the control derivatives of one T6 polar. Deflection = lo + Ctrl (hi - lo) in degrees. Result: per rad, in
    JSBSim signs ({key: {value, linearity}}). The sign of the set follows POSITIVE_DIRECTION."""
    if control not in CONTROL_COEFS:
        raise PolarError(f"unknown control {control!r}; use one of {', '.join(CONTROL_COEFS)}")
    if lo_deg == hi_deg:
        raise PolarError("the reference flap range has zero span")
    delta = np.radians(lo_deg + polar.col("Ctrl") * (hi_deg - lo_deg))
    raw = {k: fit_slope(delta, std(polar, col)) for k, col in CONTROL_COEFS[control].items()}
    key, want = POSITIVE_DIRECTION[control]
    flip = -1.0 if raw[key][0] * want < 0 else 1.0
    if abs(raw[key][0]) < 1e-3:
        raise PolarError(f"{polar.path.name}: {key} = {raw[key][0]:.2e}. The control did nothing: check the surface and flap numbers")
    return {k: {"value": flip * s, "linearity": r} for k, (s, r) in raw.items()}


def drag_increment(polar: Polar, lo_deg: float, hi_deg: float, k_induced: float) -> float:
    """Elevator drag per rad of |deflection| beyond the induced drag of its lift change (>= 0)."""
    delta = np.radians(lo_deg + polar.col("Ctrl") * (hi_deg - lo_deg))
    cl, cd = polar.col("CL"), polar.col("CD")
    i0 = int(np.argmin(np.abs(delta)))
    extra = (cd - cd[i0]) - k_induced * (cl ** 2 - cl[i0] ** 2)
    moving = np.abs(delta) > np.radians(1.0)
    return max(0.0, float(np.mean(extra[moving] / np.abs(delta[moving])))) if moving.any() else 0.0


def _row(quantity: str, t7: float, check: float, tol: float, kind: str = "rel") -> Dict[str, Any]:
    diff = abs(t7 - check) if kind == "abs" else abs(t7 / check - 1.0) if check else float("inf")
    return {"quantity": quantity, "t7": t7, "check": check, "diff": diff, "tolerance": tol, "ok": bool(diff <= tol)}


def validate(op: Dict[str, float], polars: Dict[str, Polar], inp: Dict[str, Any], body_frames: int,
             elements: Dict[str, Optional[int]]) -> Dict[str, Any]:
    """The T7 trim against lift = weight, the T1 alpha polar and the T5 beta polar."""
    rows = []
    q = 0.5 * RHO * op["VInf"] ** 2
    rows.append(_row("CL_trim", op["CL"], inp["mass"] * G / (q * inp["S"]), TOLERANCE["CL_trim"]))
    alpha = next((p for k, p in polars.items() if k.startswith("T1")), None)
    if alpha is not None:
        a = np.radians(alpha.col("alpha"))
        near = np.abs(a - math.radians(op["alpha"])) <= math.radians(4.0)
        if near.sum() >= 3:
            cma, _ = fit_slope(a[near], alpha.col("Cm")[near])
            cla, _ = fit_slope(a[near], alpha.col("CL")[near])
            rows.append(_row("Cma", op["Cma"], cma, TOLERANCE["Cma"]))
            rows.append(_row("NP_x", op["NP_x"], inp["cg"][0] - inp["cbar"] * cma / cla, NP_TOLERANCE_M, "abs"))
    beta = next((p for k, p in polars.items() if k.startswith("T5")), None)
    if beta is not None:
        cnb, _ = fit_slope(np.radians(beta.col("beta")), std(beta, "Cn"))
        rows.append(_row("Cnb", op["Cnb"], cnb, TOLERANCE["Cnb"]))
    if body_frames:
        n = elements.get("t7")
        rows.append({"quantity": "body meshed", "t7": n, "check": None, "diff": None, "tolerance": None,
                     "ok": n is not None})
    return {"ok": all(r["ok"] for r in rows), "rows": rows, "mode": "self-consistency"}


def _alpha_summary(p: Polar, op: Dict[str, float]) -> Dict[str, Any]:
    a = np.radians(p.col("alpha"))
    near = np.abs(a - math.radians(op["alpha"])) <= math.radians(4.0)
    cla, _ = fit_slope(a[near], p.col("CL")[near])
    cma, _ = fit_slope(a[near], p.col("Cm")[near])
    k, cd0 = np.polyfit(p.col("CL")[near] ** 2, p.col("CD")[near], 1)
    return {"alpha_deg": [float(p.col("alpha").min()), float(p.col("alpha").max())], "points": int(len(a)),
            "CLa": cla, "Cma": cma, "K": float(k), "CD0": float(cd0), "CL_last": float(p.col("CL")[-1]),
            "t7": {"CLa": -op["CZa"], "Cma": op["Cma"]}}


def _beta_summary(p: Polar, op: Dict[str, float]) -> Dict[str, Any]:
    b = np.radians(p.col("beta"))
    out: Dict[str, Any] = {k: fit_slope(b, std(p, col))[0] for k, col in (("CYb", "CY"), ("Clb", "Cl"), ("Cnb", "Cn"))}
    out["t7"] = {"CYb": op["Cyb"], "Clb": op["Clb"], "Cnb": op["Cnb"]}
    return out


def _plausibility(results: Dict[str, Any]) -> None:
    d = {k: v["value"] for k, v in results["derivatives"].items()}
    for key, want, why in (("CLde", 1, "trailing edge down adds lift"), ("Cnda", -1, "adverse yaw"),
                           ("Cndr", -1, "rudder trailing edge left yaws the nose left")):
        if key in d and d[key] * want < 0:
            results["warnings"].append(f"{key} = {d[key]:+.4f} has the wrong sign for {why}: check the polar")


# --------------------------------------------------------------------------------------------------------- the sweep
def _op_file(plane_dir: Path, plane: str, polar: str) -> Path:
    """The op-point text file of a polar. flow5 copies files into every polar folder, so check the first two lines."""
    for f in sorted((plane_dir / polar).glob("*.csv")):
        head = f.read_text(encoding="utf-8", errors="replace").splitlines()[:2]
        if len(head) == 2 and head[0].strip() == plane and head[1].strip() == polar:
            return f
    raise Flow5Error(f"no op-point file for polar {polar!r}: the trim probably failed")


def _elements(log: str) -> Optional[int]:
    m = re.findall(r"Counted (\d+) elements", log)
    return int(m[-1]) if m else None


def _load_runs(sr: Dict[str, Any], plane_names: List[str], only: Optional[List[str]]) -> List[Dict[str, Any]]:
    runs = list(sr.get("runs") or [])
    names = [r["name"] for r in runs]
    if not runs or len(set(names)) != len(names):
        raise Flow5Error("flow5/settings sweep_runner.runs must hold runs with unique names")
    for r in runs:
        if r["type"] not in POLAR_TYPES:
            raise Flow5Error(f"run {r['name']!r}: type must be one of {tuple(POLAR_TYPES)}")
        if r["type"] == "T6":
            if not {"control", "surface", "flaps"} <= r.keys():
                raise Flow5Error(f"run {r['name']!r}: a T6 run needs control, surface and flaps")
            if r["surface"] not in plane_names:
                raise Flow5Error(f"run {r['name']!r}: the plane has no surface {r['surface']!r} (it has {plane_names})")
    if only:
        unknown = set(only) - set(names)
        if unknown:
            raise Flow5Error(f"unknown runs: {sorted(unknown)}")
        runs = [r for r in runs if r["name"] in only]
    return runs


def _angle_ranges(run: Dict[str, Any], flaps_per_wing: Dict[int, int], plane_names: List[str]) -> List[List[Tuple[float, float]]]:
    """The T6 Angle_range table: for each wing a tilt entry then the flaps. Only this run's flaps move."""
    iw_run = plane_names.index(run["surface"])
    table = []
    for iw in range(len(plane_names)):
        row = [(0.0, 0.0)] * (1 + flaps_per_wing.get(iw, 0))
        if iw == iw_run:
            for k, sign in run["flaps"].items():
                s = float(sign) * float(run.get("max_deg", 15.0))
                row[int(k)] = (-s, s)
        table.append(row)
    return table


def _reference_range(run: Dict[str, Any]) -> Tuple[float, float]:
    """The deflection range (deg) of the first flap of a T6 run."""
    first = min(run["flaps"], key=int)
    s = float(run["flaps"][first]) * float(run.get("max_deg", 15.0))
    return -s, s


def _polar_specs(runs: List[Dict[str, Any]], all_runs: List[Dict[str, Any]], sr: Dict[str, Any], inp: Dict[str, Any],
                 plane: str, plane_names: List[str], speed: Optional[float], alpha_deg: Optional[float]) -> List[PolarSpec]:
    opt = sr.get("polar", {})
    common = dict(plane=plane, ref_area=inp["S"], ref_span=inp["b"], ref_chord=inp["cbar"], mass=inp["mass"],
                  cg=tuple(inp["cg"]), inertia=tuple(inp["inertia"]), method=opt.get("method", "TRIUNIFORM"),
                  thin_surfaces=opt.get("thin_surfaces", True), fuselage_moments=opt.get("fuselage_moments", True),
                  wake=(opt.get("wake_panels", 5), opt.get("wake_progression", 1.1), opt.get("wake_chords", 30.0)))
    flaps_per_wing: Dict[int, int] = {}      # one flap table for all T6 runs
    for r in all_runs:
        if r["type"] == "T6":
            iw = plane_names.index(r["surface"])
            flaps_per_wing[iw] = max(flaps_per_wing.get(iw, 0), *(int(k) for k in r["flaps"]))
    out = []
    for r in runs:
        kw: Dict[str, Any] = dict(common, name=r["name"], kind=r["type"], viscous=r.get("viscous", False))
        if r["type"] == "T1":
            kw["speed"] = speed
        elif r["type"] == "T5":
            kw.update(speed=speed, alpha_deg=alpha_deg)
        elif r["type"] == "T6":
            kw.update(speed=speed, alpha_deg=alpha_deg, angle_ranges=_angle_ranges(r, flaps_per_wing, plane_names))
        out.append(PolarSpec(**kw))
    return out


def _write_pass(work: Path, plane_name: str, plane_text: str, name: str, project: Optional[Path], sr: Dict[str, Any],
                runs: List[Dict[str, Any]], polars: List[PolarSpec]) -> Path:
    """A fresh folder with the plane XML, the polar XML files and script.xml of one flow5 pass."""
    if work.exists():
        shutil.rmtree(work)
    (work / "planes").mkdir(parents=True)
    (work / "polars").mkdir()
    (work / "planes" / f"{plane_name}.xml").write_text(plane_text, encoding="utf-8")
    for p in polars:
        (work / "polars" / f"{p.name}.xml").write_text(polar_xml(p), encoding="utf-8")
    script = work / "script.xml"
    script.write_text(script_xml(ScriptSpec(
        project_name=name, out_dir=work / "out", plane_dir=work / "planes", polar_dir=work / "polars",
        load_project=project, ranges=script_ranges(sr, runs), derivatives=any(r["type"] == "T7" for r in runs))),
        encoding="utf-8")
    return script


def run(*, plane_xml: Path, inputs: Dict[str, Any], sr: Dict[str, Any], name: str, dest: Path, work_root: Path,
        project: Optional[Path] = None, only: Optional[List[str]] = None, exe: Optional[Path] = None,
        timeout: float = 3600.0, dry_run: bool = False, keep: bool = False,
        trim_hint: Optional[Tuple[float, float]] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run the sweep and write the sweep folder `dest` (plane_with_body.xml, polars, T7 op point, scripts, results.json).

    `inputs`: S, b, cbar, mass, cg, inertia (Ixx, Iyy, Izz, Ixz). `dry_run` writes the XML files into `work_root` and
    starts no flow5; pass 2 uses `trim_hint` (speed m/s, alpha deg) when it is given and skips the runs that need a trim
    otherwise. Returns the results dict (a dry run returns {"dry_run": True, "script": [...]}).
    """
    plane_text = Path(plane_xml).read_text(encoding="utf-8")
    plane = read_plane(plane_xml)
    names = [w.name for w in plane.wings]
    all_runs = _load_runs(sr, names, None)
    runs = _load_runs(sr, names, only)
    frames = plane_text.lower().count("<frame>") if "<body>" in plane_text.lower() else 0
    t7_runs = [r for r in runs if r["type"] == "T7"]
    other = [r for r in runs if r["type"] != "T7"]
    work_root = Path(work_root)
    if work_root.exists():
        shutil.rmtree(work_root)
    results: Dict[str, Any] = {
        "name": name, "plane": plane.name, "body_frames": frames, "derivatives": {}, "summaries": {}, "warnings": [],
        "validation": None, "failed": {}, "inputs": {k: (list(v) if isinstance(v, (list, tuple)) else v) for k, v in inputs.items()},
        "plane_sha256": hashlib.sha256(plane_text.encode()).hexdigest(), "passes": [], **(extra or {})}
    if dry_run:
        scripts = []
        if t7_runs:
            specs = _polar_specs(t7_runs, all_runs, sr, inputs, plane.name, names, None, None)
            scripts.append(_write_pass(work_root / "pass1_t7", plane.name, plane_text, name, project, sr, t7_runs, specs))
        if other:
            sp, al = trim_hint or (None, None)
            todo = other if trim_hint else [r for r in other if r["type"] == "T1"]
            specs = _polar_specs(todo, all_runs, sr, inputs, plane.name, names, sp, al)
            scripts.append(_write_pass(work_root / "pass2", plane.name, plane_text, name, project, sr, todo, specs))
        return {"dry_run": True, "script": [str(s) for s in scripts], "trim_hint": trim_hint}

    exe = exe or find_flow5()
    t0 = datetime.now(timezone.utc)
    op: Optional[Dict[str, float]] = None
    elements: Dict[str, Optional[int]] = {}
    collected: Dict[str, Polar] = {}

    def do_pass(label: str, sub: str, todo: List[Dict[str, Any]], speed, alpha) -> Tuple[Path, List[PolarSpec], RunResult]:
        specs = _polar_specs(todo, all_runs, sr, inputs, plane.name, names, speed, alpha)
        script = _write_pass(work_root / sub, plane.name, plane_text, name, project, sr, todo, specs)
        res = run_script(exe, script, timeout)
        if not res.ok or res.pairs != len(specs):
            raise Flow5Error(f"flow5 made {res.pairs} of {len(specs)} analyses (read {script.with_suffix('.log')}):\n  "
                             + "\n  ".join(res.problems or ["no cause in the log"]))
        n = _elements(res.log)
        results["passes"].append({"pass": label, "seconds": round(res.seconds, 1), "elements": n, "lost": len(res.lost)})
        return work_root / sub / "out" / name / plane.name, specs, res

    if t7_runs:
        out, specs, res = do_pass("T7", "pass1_t7", t7_runs, None, None)
        elements["t7"] = results["passes"][-1]["elements"]
        for p in specs:
            try:
                op = read_t7_scalars(_op_file(out, plane.name, p.name))
                results["summaries"][p.name] = {"alpha_deg": op["alpha"], "V": op["VInf"], "CL": op["CL"], "Cma": op["Cma"],
                                                "Cnb": op["Cnb"], "NP_x": op["NP_x"], "CoG_x": op["CoG_x"]}
                collected[f"T7:{p.name}"] = parse_polar_text((out / f"{p.name}.csv").read_text(encoding="utf-8", errors="replace"),
                                                             out / f"{p.name}.csv")
            except (PolarError, Flow5Error, OSError, KeyError, ValueError) as err:
                results["failed"][p.name] = str(err)
    if op is not None:
        speed, alpha_deg = op["VInf"], op["alpha"]
    elif trim_hint:
        speed, alpha_deg = trim_hint
        results["warnings"].append("no T7 trim in this sweep: the other runs fly at the trim hint (the trim of the settings sweep)")
    else:
        raise Flow5Error("no T7 trim (the T7 run failed or was not asked) and no trim hint: the other runs have no speed and angle")

    if other:
        out, specs, res = do_pass("T1 T5 T6", "pass2", other, speed, alpha_deg)
        elements["pass2"] = results["passes"][-1]["elements"]
        for r, p in zip(other, specs):
            try:
                _collect_run(r, p, op, inputs, out, results, collected, sr)
            except (PolarError, Flow5Error, OSError, KeyError, ValueError) as err:   # one failed run must not discard the others
                results["failed"][p.name] = str(err)
    if op is not None:
        results["validation"] = validate(op, collected, inputs, frames, elements)
    _plausibility(results)
    now = datetime.now(timezone.utc)
    results.update(flow5=flow5_version(exe), seconds=round((now - t0).total_seconds(), 1),
                   lost_points=sum(p["lost"] for p in results["passes"]), created_utc=now.isoformat(timespec="seconds"),
                   script_sha256=hashlib.sha256(json.dumps(sr, sort_keys=True, default=str).encode()).hexdigest()[:16],
                   speed=speed, alpha_deg=alpha_deg)
    _publish(sr, work_root, plane.name, results, Path(dest), plane_text)
    if not keep:
        for w in work_root.glob("pass*"):
            shutil.rmtree(w / "out", ignore_errors=True)
    return results


def _collect_run(r: Dict[str, Any], p: PolarSpec, op: Optional[Dict[str, float]], inp: Dict[str, Any], out: Path,
                 results: Dict[str, Any], collected: Dict[str, Polar], sr: Dict[str, Any]) -> None:
    csv = out / f"{p.name}.csv"
    if not csv.is_file():
        raise Flow5Error(f"flow5 wrote no polar for run {p.name!r} (expected {csv})")
    polar = parse_polar_text(csv.read_text(encoding="utf-8", errors="replace"), csv)
    if len(polar.data) == 0:
        raise PolarError(f"run {p.name!r}: the polar has no points")
    collected[f"{r['type']}:{p.name}"] = polar
    if r["type"] == "T1":
        if op is not None:
            results["summaries"][p.name] = _alpha_summary(polar, op)
    elif r["type"] == "T5":
        if op is not None:
            results["summaries"][p.name] = _beta_summary(polar, op)
    else:
        want = int(sr["ranges"]["control_points"])
        if len(polar.data) < want:
            results["warnings"].append(f"{p.name}: {len(polar.data)} of {want} control points ran")
        lo, hi = _reference_range(r)
        fits = control_derivatives(polar, r["control"], lo, hi)
        if r["control"] == "elevator":
            k = next((s["K"] for s in results["summaries"].values() if "K" in s), 0.0)
            fits["CDde"] = {"value": drag_increment(polar, lo, hi, k), "linearity": 0.0}
        for key, fit in fits.items():
            results["derivatives"][key] = {**fit, "run": p.name}
            if fit["linearity"] > 0.1:
                results["warnings"].append(f"{key}: response is not linear ({fit['linearity']:.0%} residual)")


def _publish(sr: Dict[str, Any], work_root: Path, plane: str, results: Dict[str, Any], dest: Path, plane_text: str) -> None:
    """Copy the polars, the T7 op point, the scripts and results.json into the sweep folder."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    (dest / "plane_with_body.xml").write_text(plane_text, encoding="utf-8")
    t7_names = {r["name"] for r in sr["runs"] if r["type"] == "T7"}
    for work in sorted(work_root.glob("pass*")):
        out = work / "out" / results["name"] / plane
        for polar_file in sorted((work / "polars").glob("*.xml")):
            n = polar_file.stem
            shutil.copy(polar_file, dest / f"{n}.xml")
            if n in results["failed"] or not (out / f"{n}.csv").is_file():
                continue
            shutil.copy(out / f"{n}.csv", dest / f"{n}.csv")
            if n in t7_names:
                shutil.copy(_op_file(out, plane, n), dest / f"{n}_opoint.txt")
        shutil.copy(work / "script.xml", dest / f"script_{work.name}.xml")
        if (work / "script.log").is_file():
            shutil.copy(work / "script.log", dest / f"script_{work.name}.log")
    if (dest / "script_pass1_t7.xml").is_file():
        shutil.copy(dest / "script_pass1_t7.xml", dest / "script.xml")
    (dest / "results.json").write_text(json.dumps(results, indent=2, default=float) + "\n", encoding="utf-8")


def format_result(res: Dict[str, Any]) -> str:
    """The text report: passes, the validation table, the derivatives, warnings and failed runs."""
    if res.get("dry_run"):
        return "dry run: wrote " + ", ".join(res["script"])
    lines = [f"flow5 {res['flow5']}: {res['seconds']} s, plane {res['plane']} ({res['body_frames']} fuselage frames), "
             f"{res['lost_points']} lost points, trim {res['speed']:.2f} m/s at {res['alpha_deg']:.2f} deg"]
    for p in res["passes"]:
        lines.append(f"  pass {p['pass']}: {p['seconds']} s, {p['elements']} mesh elements")
    v = res.get("validation")
    if v:
        lines.append("Validation (the runs against each other): " + ("PASS" if v["ok"] else "FAIL"))
        for r in v["rows"]:
            t7 = f"{r['t7']:10.5f}" if isinstance(r["t7"], float) else f"{r['t7']!s:>10s}"
            ck = f"{r['check']:10.5f}" if isinstance(r["check"], float) else f"{r['check']!s:>10s}"
            lines.append(f"  {r['quantity']:12s} T7 {t7}  check {ck}  {'ok' if r['ok'] else 'OUT'}")
    for k, d in sorted(res["derivatives"].items()):
        lines.append(f"  {k:5s} {d['value']:+9.4f} per rad  (run {d['run']}, nonlinearity {d['linearity']:.1%})")
    lines += [f"  WARNING: {w}" for w in res["warnings"]]
    lines += [f"  FAILED {n}: {why}" for n, why in res["failed"].items()]
    return "\n".join(lines)
