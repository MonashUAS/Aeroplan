"""AeroSandbox spoke: the initial sizing -> ADH performance record of the air vehicle, the ADH aircraft -> an AeroSandbox model
with the propulsion chain (generate), and the sized quadplane (settings/<aircraft>.json) -> the ADH aircraft.

Files of the tool folder (ADR 0024): `component.py` (components and level functions), `model.py` (one model class for each class of
aircraft, and the jobs of this spoke), `mission.py`, `optimise.py` (solver driver), `result.py`, `plot.py` and `window.py`. They run in
the AeroSandbox Python (tools/aerosandbox/.venv). This file runs in the AeroPlan Python. It does not import aerosandbox. It sends a
job to `model.py` and reads the result, the way the OpenVSP spoke does.

Input (git ignores it): work/aerosandbox/<aircraft>/athena_outputs.txt, the printout of the Athena sizing scripts
(AeroSandbox). One "Name: value" line for each output. The file gives no units.

What ingest writes: one ADH `Discipline` "sizing" in `performance` of node 1.2 AirVehicle. Its tool record
(`ModelDescription`) holds every output in `data_exchange.outputs` as {name, value, units, units_basis}.

Units: the printout has none. `UNITS` below gives each output a unit and says why:
  - "consistency": a relation between the outputs confirms the unit (for example b^2 / S = AR, or the mass sum).
  - "magnitude":   the value fits only one plausible unit for this aircraft. Not proven.
  - "unknown":     no unit can be given. The value is kept with units "unknown".
What generate does (after `python -m aeroplan setup AeroSandbox`, once for each computer): the spoke builds a tool-neutral spec
from the ADH document (wing, tail, fuselage, mass model, propeller installation, motor, ESC, battery). The spec goes to
tools/aerosandbox/model.py in tools/aerosandbox/.venv. Jobs: geometry (three-view, 3D view), polar (AeroBuildup against the
flow5 aero model), cruise_trim (one Opti problem: airframe, Proptimiser BEMT and the Propalyser motor and ESC chain) and
static_check (the chain at full command against the Propalyser table). Files go to work/<aircraft>/asb/. generate
changes no ADH data.

The sizing stage comes before flow5. Its geometry values do not set the flow5 geometry. The datum report lists the
differences.

Quadplane (Rosella): the aircraft has a model file `settings/<aircraft>.json`, written by the sizing notebook
(`notebooks/rosella_sizing.ipynb`, `model.AircraftModel.save`). `ingest` reads it and writes the whole tree. It copies the Currawong
wing, ailerons, empennage and tail boom. It adds the new fuselage, the lift booms (with their material), the cruise propeller and the
lift rotors, the lift propulsion system, the point masses, the roll-up (mass, CG, inertia), the quadplane reference (MRP = the sized
CG), the `sizing` record, the limits as `muas.target` requirements, and the motor outputs 5 and up. See `_ingest_quadplane`. The sizing
runs in the notebook, not in this spoke.

Multirotor (settings `kind: multirotor`): there is no Athena printout. `ingest` seeds the aircraft from the `multirotor`
block of the settings (aeroplan.multirotor.seed: reference, four lift rotors, motor outputs, ground contacts, demo
shapes) and reads `work/<aircraft>/asb/multirotor_results.json`, when it exists, into the body-drag aero dataset
(src/aeroplan/multirotor_aero.py) and the `sizing` performance record of node 1.2 (the EMST results). `generate` runs the
jobs multirotor_drag, emst_segments, emst_endurance and emst_sensitivity (the EMST jobs need the propulsion
system of the Propalyser spoke) and writes that file and `report.md`. With `proptimiser_design` in the settings it also runs
emst_live: hover and climb with the live Proptimiser BEMT (`static_and_axial`, one Propeller for each rotor) for that design
and for each design of `proptimiser_compare`. The Proptimiser design and state files come from
work/<aircraft>/proptimiser/ (copy them by hand). Their sha256 go into the results file. Order: build, generate, build.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from aeroplan import adh_doc, assets, mass_model, multirotor, multirotor_aero, source_tree
from aeroplan.daveml_adh import from_xml
from aeroplan.dml_validate import validate_dml
from aeroplan.frame import flip_array, flip_doc, flip_point, planform_le_x
from aeroplan.geometry import body_adh, body_frames, planform_reference
from aeroplan.muas.requirement import Target, target_requirement
from aeroplan.spokes import Context, set_sources

from . import component

NAME = "AeroSandbox"
FILE = "athena_outputs.txt"
RESULTS = "multirotor_results.json"
G0 = 9.80665                  # m/s^2, standard gravity (weight of the mass model)




# ===================================================================================================== the AeroSandbox Python
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
VENV = HERE / ".venv"
SETTINGS = HERE / "settings"
WORKER = HERE / "model.py"
PYTHON = "3.12"
WORKER_NEEDS = ("aerosandbox==4.2.9", "matplotlib", "plotly", "h5py", "PyYAML")
NOTEBOOK_NEEDS = ("jupyterlab", "ipykernel", "ipywidgets", "anywidget", "nbformat", "nbclient", "nbconvert", "pandas")
KERNEL = "aeroplan-asb"


class AeroSandboxError(RuntimeError):
    pass


def python() -> Path:
    """The AeroSandbox Python: AEROSANDBOX_PYTHON, else tools/aerosandbox/.venv."""
    env = os.environ.get("AEROSANDBOX_PYTHON")
    if env:
        return Path(env)
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def available() -> bool:
    return python().is_file() and WORKER.is_file()


def run(job: Dict[str, Any], timeout: float = 1800) -> Dict[str, Any]:
    """Run one job of model.py in the AeroSandbox Python. Raises AeroSandboxError with the error text of the job. The Python runs
    with -E and -s (no PYTHON variables, no user site) and the script folder on its path, so model.py finds component.py."""
    if not available():
        raise AeroSandboxError("the AeroSandbox Python is not set up: run `python -m aeroplan setup AeroSandbox`")
    with tempfile.TemporaryDirectory(prefix="aeroplan_asb_") as tmp:
        jf, rf = Path(tmp) / "job.json", Path(tmp) / "result.json"
        jf.write_text(json.dumps(job), encoding="utf-8")
        p = subprocess.run([str(python()), "-E", "-s", str(WORKER), str(jf), str(rf)], capture_output=True, text=True,
                           timeout=timeout, cwd=tmp)
        if not rf.is_file():
            raise AeroSandboxError(f"the AeroSandbox worker stopped (exit {p.returncode}): {(p.stderr or p.stdout)[-2000:]}")
        res = json.loads(rf.read_text(encoding="utf-8"))
    if not res.get("ok"):
        raise AeroSandboxError(f"AeroSandbox job {job.get('job')}: {res.get('error')}\n{res.get('trace', '')}")
    return res


def _uv() -> List[str]:
    """The uv command: the `uv` program on the PATH, else the uv module of this Python (installed when it is missing)."""
    found = shutil.which("uv")
    if found:
        return [found]
    try:
        subprocess.run([sys.executable, "-m", "uv", "--version"], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "uv"], check=True)
    return [sys.executable, "-m", "uv"]


def setup_venv(proptimiser: Optional[str] = None, git: Optional[Dict[str, str]] = None,
               log=lambda m: print(m, flush=True)) -> Dict[str, str]:
    """Make tools/aerosandbox/.venv with the packages of WORKER_NEEDS and NOTEBOOK_NEEDS (JupyterLab, the widgets of the window),
    AeroPlan itself (editable, so a notebook reads the source tree live) and Proptimiser. `proptimiser` is a checkout folder.
    Without it, `git` ({url, rev}) names the source. A Proptimiser that cannot be installed is a warning: the airframe jobs and
    the notebooks still work. Returns {folder, python, version}."""
    src = None
    if proptimiser:
        src = str(Path(proptimiser).resolve())
        if not (Path(src) / "pyproject.toml").is_file():
            raise AeroSandboxError(f"{src} is not a Proptimiser folder (no pyproject.toml)")
    elif git and git.get("url") and git.get("rev"):
        src = f"git+{git['url']}@{git['rev']}"
    uv = _uv()
    log(f"Make {VENV} with Python {PYTHON}")
    subprocess.run(uv + ["venv", "--clear", "--python", PYTHON, str(VENV)], check=True)
    vpy = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(uv + ["pip", "install", "--quiet", "--python", str(vpy), *WORKER_NEEDS, *NOTEBOOK_NEEDS], check=True)
    log(f"Install AeroPlan from {REPO} (editable, for the notebooks)")
    subprocess.run(uv + ["pip", "install", "--quiet", "--python", str(vpy), "-e", str(REPO)], check=True)
    subprocess.run([str(vpy), "-m", "ipykernel", "install", "--user", "--name", KERNEL,
                    "--display-name", "AeroPlan AeroSandbox"], check=True, capture_output=True)
    if src is None:
        log("WARNING: no Proptimiser source (--proptimiser <folder>, or url and rev in the settings): "
            "the propeller jobs (cruise_trim, static_check) and the sizing do not work")
    else:
        log(f"Install Proptimiser from {src} (no JAX)")
        r = subprocess.run(uv + ["pip", "install", "--quiet", "--python", str(vpy), src], capture_output=True, text=True)
        if r.returncode:
            log(f"WARNING: Proptimiser did not install, the propeller jobs do not work:\n{r.stderr[-800:]}")
    version = run({"job": "version"}, timeout=300)["version"]
    log(f"Check: {version}")
    return {"folder": str(VENV), "python": str(vpy), "version": version}


def describe_venv() -> str:
    """One line for `aeroplan spokes`: the versions of the AeroSandbox Python, or the setup command."""
    if not available():
        return "AeroSandbox Python not set up: run `python -m aeroplan setup AeroSandbox`"
    try:
        return run({"job": "version"}, timeout=120)["version"]
    except AeroSandboxError as e:
        return f"AeroSandbox Python does not work: {e}"


# ============================================================================================ the Athena printout
UNITS = {
    "Take-off distance": ("m", "magnitude"), "Climb angle": ("deg", "magnitude"), "Glide ratio": ("nd", "consistency"),
    "Max speed": ("m/s", "magnitude"), "Min speed": ("m/s", "magnitude"), "Landing angle": ("deg", "magnitude"),
    "Landing distance": ("m", "magnitude"), "Flight distance": ("unknown", "unknown"),
    "Specific energy consumption": ("unknown", "unknown"), "Payload mass": ("kg", "magnitude"),
    "Payload volume": ("m^3", "magnitude"), "Wing area": ("m^2", "consistency"), "Wing span": ("m", "consistency"),
    "Aspect ratio": ("nd", "consistency"), "C_D": ("nd", "consistency"), "C_D_i": ("nd", "consistency"),
    "C_D_o": ("nd", "consistency"), "C_L": ("nd", "consistency"), "Cruise speed": ("m/s", "magnitude"),
    "Energy consumed": ("unknown", "unknown"), "m_avionics": ("kg", "consistency"), "m_misc": ("kg", "consistency"),
    "m_fuselage": ("kg", "consistency"), "m_wing": ("kg", "consistency"), "m_batteries": ("kg", "consistency"),
    "m_propulsion": ("kg", "consistency"), "m_spars": ("kg", "consistency"), "m_payload_tank": ("kg", "consistency"),
    "m_total": ("kg", "consistency"), "Root chord": ("m", "magnitude"), "MAC length": ("m", "magnitude"),
    "MAC location": ("m", "unknown datum"), "Take off points": ("nd", "magnitude"),
    "Landing points": ("nd", "magnitude"), "Energy efficiency points": ("nd", "magnitude"),
}
_LINE = re.compile(r"^\s*([^:]+?)\s*:\s*([-+0-9.eE]+)\s*$")


def parse(text: str) -> Dict[str, float]:
    """The outputs of an Athena printout. Refuses a line that is not "Name: number"."""
    out: Dict[str, float] = {}
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        m = _LINE.match(line)
        if not m:
            raise ValueError(f"{FILE} line {i}: {line!r} is not 'Name: number'")
        out[m.group(1)] = float(m.group(2))
    return out


def consistency(v: Dict[str, float]) -> List[str]:
    """The relations that confirm the 'consistency' units. A failed relation stops the ingest."""
    rows = []
    ar = v["Wing span"] ** 2 / v["Wing area"]
    if abs(ar - v["Aspect ratio"]) > 1e-3 * v["Aspect ratio"]:
        raise ValueError(f"b^2/S = {ar:.4f} differs from the aspect ratio {v['Aspect ratio']}")
    rows.append(f"b^2/S = {ar:.4f} = AR {v['Aspect ratio']}: S in m^2 and b in m (or both in one other unit)")
    parts = sum(v[k] for k in v if k.startswith("m_") and k != "m_total")
    if abs(parts - v["m_total"]) > 1e-3:
        raise ValueError(f"the mass parts sum to {parts:.4f}, not m_total {v['m_total']}")
    rows.append(f"the mass parts sum to m_total {v['m_total']}")
    if abs(v["C_D_i"] + v["C_D_o"] - v["C_D"]) > 1e-3:
        raise ValueError("C_D_i + C_D_o differs from C_D")
    rows.append("C_D_i + C_D_o = C_D")
    if abs(v["C_L"] / v["C_D"] - v["Glide ratio"]) > 1e-2:
        raise ValueError("C_L / C_D differs from the glide ratio")
    rows.append("C_L / C_D = glide ratio")
    return rows


def _output(name, value, units):
    return {"name": name, "value": float(value), "units": units, "units_basis": "SI model output"}


def _emst_outputs(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    seg = res.get("emst_segments")
    if seg:
        keys = (("rpm", "rpm"), ("thrust_each_N", "N"), ("tilt_deg", "deg"), ("duty", "nd"), ("i_total_A", "A"),
                ("p_shaft_W", "W"), ("p_battery_W", "W"), ("endurance_min", "min"))
        for s in seg["segments"]:
            tag = s["name"] if s["name"] != "forward" else f"forward_{s['speed_m_s']:g}_m_s"
            out += [_output(f"{tag}_{k}", s[k], u) for k, u in keys]
            if s.get("esc_command_equiv") is not None:
                out.append(_output(f"{tag}_esc_command_from_static_map", s["esc_command_equiv"], "nd"))
        f = seg["full_throttle"]
        out += [_output("full_throttle_thrust_total_N", f["thrust_total_N"], "N"),
                _output("thrust_to_weight", f["thrust_to_weight"], "nd")]
    lv = res.get("emst_live")
    if lv:
        keys = (("rpm", "rpm"), ("thrust_each_N", "N"), ("p_shaft_each_W", "W"), ("p_battery_W", "W"), ("i_total_A", "A"),
                ("endurance_min", "min"))
        for design, segs in lv["designs"].items():
            out += [_output(f"{name}_live_{design}_{k}", segs[name][k], u) for name in ("hover", "climb") for k, u in keys]
    sc = res.get("emst_endurance")
    if sc:
        out += [_output("best_endurance_speed_m_s", sc["best_endurance"]["speed_m_s"], "m/s"),
                _output("best_range_speed_m_s", sc["best_range"]["speed_m_s"], "m/s"),
                _output("best_range_km", sc["best_range"]["range_km"], "km")]
    se = res.get("emst_sensitivity")
    if se:
        out += [_output(f"sensitivity_{k}_percent_per_percent", v["percent_per_percent"], "nd")
                for k, v in se["parameters"].items()]
    return out


def _ingest_multirotor(doc: Dict[str, Any], ctx: Context, st: Dict[str, Any]):
    """Seed the multirotor from the settings, then read the results of `generate` when they exist."""
    changes = multirotor.seed(doc, ctx.aircraft, st["multirotor"])
    path = ctx.work / "asb" / RESULTS
    if not path.is_file():
        changes.append(f"no {path.relative_to(ctx.root).as_posix()}: no body-drag aero dataset and no EMST record yet. "
                       f"Run `python -m aeroplan generate AeroSandbox {ctx.aircraft}`, then build again")
        return changes
    res = json.loads(path.read_text(encoding="utf-8"))
    air = adh_doc.node(doc, "1.2")
    ref = air["muas"]["reference"]
    s_ref = ref["s_ref"]["value"]
    if abs(res["inputs"]["s_ref_m2"] - s_ref) > 1e-9:
        raise ValueError(f"{path.name} was made with S_ref {res['inputs']['s_ref_m2']} m^2, the document has {s_ref} m^2: "
                         f"run `aeroplan generate AeroSandbox {ctx.aircraft}` again")
    mp = air["muas"].get("mass_properties")
    if mp and abs(res["inputs"]["mass_kg"] - mp["mass"]["value"]) > 1e-6:
        changes.append(f"WARNING: the results used the mass {res['inputs']['mass_kg']:.4f} kg, the document has "
                       f"{mp['mass']['value']:.4f} kg: run generate again")
    ref_src = ctx.source_ref(path, "multirotor body drag and EMST results")
    d = res["multirotor_drag"]
    src = (f"AeroSandbox AeroBuildup of the demo body box and arm tubes (job multirotor_drag, {d['speed_m_s']:g} m/s, "
           f"Hoerner hand check, AeroBuildup over Hoerner x {d['asb_over_hoerner']['x']:.2f}, y {d['asb_over_hoerner']['y']:.2f}, "
           f"z {d['asb_over_hoerner']['z']:.2f}; rule combine {d['combine']}). Stand-in shapes: fit from the flight log")
    k = st["drag"]["k_rotor_drag_kg"]
    sources = {"S_ref": ("muas.reference s_ref (the frontal area of the demo body box)", True),
               "CDx": (src, True), "CDy": (src, True), "CDz": (src, True),
               "k_rotor_drag": (st["drag"]["k_rotor_drag_source"], True)}
    coefs = multirotor_aero.coefficients(s_ref, d["CD"], k, sources)
    cg = ref["mrp"]["point"]["xyz"]
    xml = multirotor_aero.to_daveml(
        coefs, name=f"{ctx.aircraft.capitalize()} body drag model", author="AeroPlan AeroSandbox spoke", org="MUAS",
        created=str(res["inputs"]["date"]),
        description=f"{ctx.aircraft} multirotor body drag (forces only, body axes FRD, no moments). "
                    "See spec/multirotor_contract.md.")
    errors = validate_dml(xml)
    if errors:
        raise ValueError(f"the body-drag model fails the DAVE-ML 2.0 DTD: {errors[:3]}")
    meta = {"form": "daveml-adh", "fidelity": "L1", "units_system": "SI",
            "model_description": {"generation_tool": "AeroSandbox AeroBuildup + AeroPlan multirotor body drag",
                                  "model_name": f"{ctx.aircraft} body drag",
                                  "description": "Quadratic body drag per axis and a rotor drag term. Placeholder until the "
                                                 "flight log fits it."},
            "mrp": {"xyz": list(cg)}, "placeholder": True,
            "notes": ["Forces only: F = -0.5 rho S C_D v |v| per axis, plus -k_rotor_drag n_sum v on x and y.",
                      "The drag area comes from stand-in shapes. No uncertainty estimate exists (sigma not given)."]}
    if mp:
        meta["analysis_mass_model"] = copy.deepcopy(mp)
    ctx.add_dataset(air, f"aero.{ctx.aircraft}", from_xml(xml), role="aero model (DAVE-ML in ADH form)",
                    dataset_role="aero", derived_from=[ref_src["asset"]], meta=meta)
    changes.append(f"aero dataset: body drag, CDx {coefs['CDx'].value:.3f}, CDy {coefs['CDy'].value:.3f}, "
                   f"CDz {coefs['CDz'].value:.3f} on S {s_ref:.4f} m^2, k_rotor_drag {k:g} kg (all placeholder)")
    outputs = _emst_outputs(res)
    if outputs:
        names = (("rb", "ohm"), ("rw", "ohm"), ("re", "ohm"), ("ia", "A"), ("ip", "A"), ("eta_e", "nd"),
                 ("discharge_fraction", "nd"))
        ins = [{"name": n, "value": v["value"], "units": u, "placeholder": v["placeholder"], "source": v["source"]}
               for (n, u), v in zip(names, st["electrical"].values())]
        sizing = {"name": "sizing", "description": "EMST segment analysis of the multirotor (hover, climb, forward flight "
                  "with the tilt loop), endurance and sensitivities. Rotor load: the CT/CP table of the propulsion dataset.",
                  "tools": [{"model_name": "EMST segment analysis", "generation_tool": "AeroSandbox model (model.py, MultirotorModel)",
                             "description": "Bershadsky, Haviland, Johnson, AIAA 2016-0581, section III.A, eq. (9) to (12). "
                                            "Inputs marked placeholder are stand-ins.",
                             "data_exchange": {"model_identifier": "emst", "inputs": ins, "outputs": outputs}}]}
        air["performance"] = [sizing] + [x for x in air.get("performance") or [] if x.get("name") != "sizing"]
        changes.append(f"sizing: {len(outputs)} EMST outputs")
    else:
        changes.append("no EMST results (no propulsion system when generate ran)")
    set_sources(air, NAME, [ref_src])
    return changes


# ================================================================================ the spec of the fixed-wing and multirotor jobs
def _value(q: Optional[Dict[str, Any]], default: Optional[float] = None) -> Optional[float]:
    return float(q["value"]) if q else default


def _sizing_output(doc: Dict[str, Any], name: str) -> Dict[str, Any]:
    air = adh_doc.node(doc, "1.2")
    for d in air.get("performance") or []:
        if d.get("name") == "sizing":
            for t in d["tools"]:
                for o in t["data_exchange"]["outputs"]:
                    if o["name"] == name:
                        return o
    raise ValueError(f"the sizing record of node 1.2 has no output {name!r}")


def bodies_of(st: Dict[str, Any]) -> List[str]:
    """The ADH items with a body that go into the airplane: `bodies` of the settings, or the older single `body`."""
    if st.get("bodies") is not None:
        return list(st["bodies"])
    return [st["body"]] if st.get("body") else []


def spec_from_doc(doc: Dict[str, Any], st: Dict[str, Any], ctx: Context) -> Dict[str, Any]:
    """The spec of the fixed-wing jobs. The tree is FRD (x forward, z down). AeroSandbox works in x aft, z up: every position
    and direction in the spec is flipped here (aeroplan.frame)."""
    air = adh_doc.node(doc, "1.2")["muas"]
    ref = air["reference"]
    mp = air["mass_properties"]
    prop_item = adh_doc.find(doc, st["propeller"])["muas"]
    inst, psys = prop_item["propeller"], prop_item.get("propulsion_system")
    if psys is None or not psys.get("motor") or not psys.get("battery"):
        raise ValueError(f"{st['propeller']}: muas.propulsion_system has no motor and battery (run the Propalyser spoke)")
    m = psys["motor"]
    if m.get("kappa") is None or m.get("r_tot") is None:
        raise ValueError("the contract B file has no motor chain constants: use a Propalyser stand file of this motor")
    speed = _sizing_output(doc, st["cruise_speed_output"])
    if speed["units"] != "m/s":
        raise ValueError(f"the sizing output {speed['name']!r} has units {speed['units']!r}, not m/s")
    ref_id = next((d["ref"] for d in prop_item.get("datasets", []) if d["role"] == "propulsion"), None)
    if ref_id is None:
        raise ValueError(f"{st['propeller']}: no propulsion dataset (Ct/Cp table)")
    tables = ctx.dataset(ref_id)["prop_ctcp"]["columns"]
    point = [{"tag": p["tag"], "mass_kg": p["mass"]["value"], "xyz": flip_point(p["position"]["xyz"]),
              "placeholder": bool(p.get("placeholder"))} for p in air.get("point_masses") or []]
    mass = {"mass_kg": mp["mass"]["value"], "cg": flip_point(mp["cg"]["xyz"]),
            "inertia": flip_doc(mp["inertia"]) if mp.get("inertia") else None,
            "point_masses": point, "placeholder": bool(mp.get("placeholder"))}
    return {
        "name": doc.get("name", "aircraft"),
        "reference": {"s_m2": ref["s_ref"]["value"], "b_m": ref["b_ref"]["value"], "c_m": ref["c_ref"]["value"],
                      "xyz_ref": flip_point(ref["mrp"]["point"]["xyz"])},
        "surfaces": [component.surface_spec(doc, w) for w in st["wings"]],
        "fuselages": [{"name": b, "frames": [flip_array(f).tolist() for f in body_frames(adh_doc.find(doc, b)["geometry"]["body"])]}
                      for b in bodies_of(st)],
        "mass": mass,
        "propulsion": {
            "hub": flip_point(inst["hub"]["xyz"]), "thrust_axis": flip_point(inst["thrust_axis"]),
            "diameter_m": inst["diameter"]["value"], "design": st["proptimiser_design"],
            "p_max_W": psys["p_max"]["value"], "placeholder": bool(psys.get("placeholder")),
            "motor": {"kv_rad_s_V": m["kv"]["value"], "i0_A": m["i0"]["value"], "kappa": m["kappa"],
                      "r_tot_ohm": m["r_tot"]["value"], "q0_Nm": _value(m.get("q0"), 0.0),
                      "imax_A": _value(m.get("imax_continuous")), "mass_kg": _value(m.get("mass"))},
            "esc": {k: _value(v) for k, v in (psys.get("esc") or {}).items() if isinstance(v, dict)},
            "battery": {"v_nominal_V": psys["battery"]["v_nominal"]["value"], "cells_s": psys["battery"]["cells_s"],
                        "capacity_As": _value(psys["battery"].get("capacity")),
                        "mass_kg": _value(psys["battery"].get("mass"))},
            "tables": {k: list(v) for k, v in tables.items()},
        },
        "flight": {"speed_m_s": speed["value"], "speed_basis": speed["units_basis"], "altitude_m": st["altitude_m"],
                   "weight_N": mp["mass"]["value"] * G0},
    }


def flow5_polar(doc: Dict[str, Any], ctx: Context, alphas_deg: List[float]) -> Optional[Dict[str, Any]]:
    """CL, CD and Cm of the flow5 aero model (DAVE-ML in the ADH) at the angles of attack, or None without the model."""
    from aeroplan.daveml_eval import Model

    air = adh_doc.node(doc, "1.2")["muas"]
    ref_id = next((d["ref"] for d in air.get("datasets", []) if d["role"] == "aero"), None)
    if ref_id is None:
        return None
    model = Model(ctx.dataset(ref_id))
    inputs = {v["var_id"]: 0.0 for v in model.vars.values() if v.get("is_input")}
    out: Dict[str, Any] = {"alpha_deg": list(alphas_deg), "CL": [], "CD": [], "Cm": []}
    for a in alphas_deg:
        v = model.evaluate({**inputs, "alpha": math.radians(a)})
        for key in ("CL", "CD", "Cm"):
            out[key].append(v[key])
    return out


def spec_placeholders(spec: Dict[str, Any]) -> List[str]:
    out = []
    if spec["mass"]["placeholder"]:
        out.append(f"mass model of node 1.2 ({spec['mass']['mass_kg']:.3f} kg, CG, inertia): placeholder")
    out += [f"point mass {p['tag']}: placeholder" for p in spec["mass"]["point_masses"] if p["placeholder"]]
    if spec["propulsion"]["placeholder"]:
        out.append("propulsion system (contract B): placeholder")
    if spec["flight"]["speed_basis"] != "consistency":
        out.append(f"cruise speed {spec['flight']['speed_m_s']:g} m/s: sizing output, unit basis "
                   f"'{spec['flight']['speed_basis']}'")
    out.append("battery: nominal voltage, no internal resistance (no sourced value); the energy is the full capacity "
               "with no reserve")
    out.append("propeller airfoil: Clark-Y is an assumption (the old blade file does not store it)")
    return out


def spec_report(spec: Dict[str, Any], results: Dict[str, Any], hashes: Dict[str, str], ph: List[str]) -> str:
    L = ["# AeroSandbox model of the aircraft", "",
         "Written by `python -m aeroplan generate AeroSandbox <aircraft>`. Nothing here goes back into the ADH data.", ""]
    g = results["geometry"]["geometry"]
    r = spec["reference"]
    L += ["## Geometry (AeroSandbox against the ADH reference)", "", "| Item | AeroSandbox | ADH | Unit |", "|---|---|---|---|",
          f"| Wing area | {g['s_m2']:.4f} | {r['s_m2']:.4f} | m^2 |", f"| Span | {g['b_m']:.4f} | {r['b_m']:.4f} | m |",
          f"| MAC | {g['mac_m']:.4f} | {r['c_m']:.4f} | m |", "",
          "AeroSandbox measures the wing area and span along the dihedral. The ADH reference is the projected value.", ""]
    ref = results["polar"].get("reference")
    if ref:
        L += ["## Polar at the cruise speed, elevator 0 (AeroSandbox AeroBuildup against flow5)", "",
              "| alpha [deg] | CL asb | CL flow5 | CD asb | CD flow5 | Cm asb | Cm flow5 |", "|---|---|---|---|---|---|---|"]
        for row, i in zip(results["polar"]["rows"], range(len(ref["alpha_deg"]))):
            L.append(f"| {row['alpha_deg']:g} | {row['CL']:.3f} | {ref['CL'][i]:.3f} | {row['CD']:.4f} | "
                     f"{ref['CD'][i]:.4f} | {row['Cm']:.3f} | {ref['Cm'][i]:.3f} |")
        L += ["", "The two models are different methods. A gap here is a finding about the models. It does not say which is right.", ""]
    t = results["cruise_trim"]["cruise_trim"]
    L += ["## Cruise trim", "", f"Level flight at {t['speed_m_s']:g} m/s, weight {t['weight_N']:.2f} N.", "",
          "| Item | Value | Unit |", "|---|---|---|"]
    for k, u in (("alpha_deg", "deg"), ("elevator_deg", "deg"), ("rpm", "rpm"), ("duty", "nd"), ("thrust_N", "N"),
                 ("drag_N", "N"), ("L_over_D", "nd"), ("p_shaft_W", "W"), ("p_bat_W", "W"), ("i_motor_A", "A"),
                 ("i_bat_A", "A"), ("chain_efficiency", "nd"), ("endurance_min", "min")):
        v = t.get(k)
        L.append(f"| {k} | {v:.4g} | {u} |" if v is not None else f"| {k} | n/a | {u} |")
    s = results["static_check"]["static_check"]
    L += ["", "## Static check against Propalyser (full command, V = 0)", "",
          "| Item | AeroSandbox | Propalyser | Unit |", "|---|---|---|---|",
          f"| Shaft power | {s['p_shaft_W']:.1f} | {s['p_max_propalyser_W']:.1f} | W |",
          f"| Shaft speed | {s['rpm']:.0f} | {s['rpm_propalyser_table_at_pmax']:.0f} (table speed at p_max) | rpm |",
          f"| Ct0 | {s['ct0_bemt']:.4f} | {s['ct0_table']:.4f} | nd |",
          f"| Cp0 | {s['cp0_bemt']:.4f} | {s['cp0_table']:.4f} | nd |",
          f"| Thrust at the same speed | {s['thrust_N']:.2f} | {s['thrust_table_same_omega_N']:.2f} | N |", "",
          "The Propalyser table is the Proptimiser curve scaled to the static test. The scale factors are in the "
          "Propalyser provenance text.", ""]
    L += ["## Inputs", "", f"Proptimiser design `{spec['propulsion']['design']}`.", ""]
    L += [f"- `{k}` sha256 {v}" for k, v in hashes.items()]
    L += ["", "## Placeholders that the results use", ""] + [f"- {p}" for p in ph]
    pm = sum(p["mass_kg"] for p in spec["mass"]["point_masses"])
    L += ["", f"The point masses add to {pm:.3f} kg. The mass model total is {spec['mass']['mass_kg']:.3f} kg.", ""]
    return "\n".join(L)


def multirotor_spec(doc: Dict[str, Any], st: Dict[str, Any], ctx: Context, drag: Optional[Dict[str, Any]] = None
                    ) -> Dict[str, Any]:
    """The spec of the multirotor jobs, from the ADH document and the settings. `drag` {CDx, CDy, CDz} (the result of
    the multirotor_drag job) fills the body drag of the EMST jobs. `propulsion` is None until the document holds a
    propulsion system and its Ct/Cp dataset (the Propalyser spoke). The tree is FRD: the positions in the spec are flipped to
    x aft, z up for the model."""
    air = adh_doc.node(doc, "1.2")["muas"]
    ref, mp = air["reference"], air.get("mass_properties")
    if ref.get("kind") != "multirotor":
        raise ValueError("muas.reference.kind is not multirotor: build the aircraft first (the AeroSandbox seed)")
    if mp is None:
        raise ValueError("node 1.2 has no muas.mass_properties: run the SpecSheet spoke (aeroplan build) first")
    rotors, shapes, psys_item = [], {}, None
    for _, item, _ in adh_doc.iter_nodes(doc):
        m = item.get("muas") or {}
        pr = m.get("propeller")
        if pr and pr["role"] == "lift":
            rotors.append({"motor": pr["motor"], "instance": m["instance"], "hub": flip_point(pr["hub"]["xyz"]),
                           "thrust_axis": flip_point(pr["thrust_axis"]), "spin": pr["spin"], "diameter_m": pr["diameter"]["value"]})
        for v in m.get("visual") or []:
            if v.get("shape") and v["generator"] in ("box", "tube"):
                shapes[v["part"]] = flip_doc(v["shape"])      # centre, p0, p1: the model is x aft, z up
        if m.get("propulsion_system") and psys_item is None:
            psys_item = m
    rotors.sort(key=lambda r: r["motor"])
    if "body" not in shapes:
        raise ValueError("the document has no visual part `body` (box): the drag job needs the body shape")
    arms = [{"p0": s["p0"], "p1": s["p1"], "radius_m": s["radius_m"]} for k, s in sorted(shapes.items()) if k.startswith("arm_")]
    cfg = st["drag"]
    spec: Dict[str, Any] = {
        "kind": "multirotor", "name": doc.get("name", "aircraft"),
        "reference": {"s_m2": ref["s_ref"]["value"], "b_m": ref["b_ref"]["value"], "c_m": ref["c_ref"]["value"],
                      "xyz_ref": flip_point(ref["mrp"]["point"]["xyz"])},
        "rotors": rotors, "body": {"box": shapes["body"], "arms": arms},
        "mass": {"mass_kg": mp["mass"]["value"], "cg": flip_point(mp["cg"]["xyz"]),
                 "inertia": flip_doc(mp["inertia"]) if mp.get("inertia") else None,
                 "placeholder": bool(mp.get("placeholder"))},
        "drag_job": {"speed_m_s": cfg["speed_m_s"], "altitude_m": cfg["altitude_m"],
                     "box_edge_sections": cfg.get("box_edge_sections", 5), "combine": cfg.get("combine", "max"),
                     "hoerner": {k: v for k, v in cfg["hoerner"].items() if k != "source"}},
        "electrical": {k: v["value"] for k, v in st["electrical"].items()},
        "analysis": dict(st["analysis"]), "propulsion": None, "drag": None}
    if drag is not None:
        spec["drag"] = {"S_ref_m2": ref["s_ref"]["value"], "CDx": drag["CDx"], "CDy": drag["CDy"], "CDz": drag["CDz"],
                        "k_rotor_drag_kg": cfg["k_rotor_drag_kg"]}
    ps = (psys_item or {}).get("propulsion_system")
    if ps:
        m_ = ps.get("motor") or {}
        if m_.get("kappa") is None or m_.get("r_tot") is None:
            raise ValueError("the contract B file has no motor chain constants (kappa, r_tot)")
        ref_id = next((d["ref"] for d in psys_item.get("datasets", []) if d["role"] == "propulsion"), None)
        if ref_id is None:
            raise ValueError("the propulsion system has no propulsion dataset (Ct/Cp table)")
        data = ctx.dataset(ref_id)
        b = ps.get("battery") or {}
        if not b or b.get("capacity") is None:
            raise ValueError("the contract B file has no battery with a capacity")
        spec["propulsion"] = {
            "system_id": ps["system_id"], "diameter_m": ps["diameter"]["value"], "p_max_W": ps["p_max"]["value"],
            "placeholder": bool(ps.get("placeholder")), "basis": ps["basis"],
            "motor": {"kv_rad_s_V": m_["kv"]["value"], "i0_A": m_["i0"]["value"], "kappa": m_["kappa"],
                      "r_tot_ohm": m_["r_tot"]["value"], "q0_Nm": _value(m_.get("q0"), 0.0)},
            "battery": {"v_nominal_V": b["v_nominal"]["value"], "cells_s": b["cells_s"], "cells_p": b["cells_p"],
                        "capacity_As": b["capacity"]["value"]},
            "tables": {k: list(v) for k, v in data["prop_ctcp"]["columns"].items()},
            "throttle_map": {k: list(v) for k, v in data["throttle_map"]["columns"].items()}}
    return spec


def multirotor_placeholders(st: Dict[str, Any], spec: Dict[str, Any]) -> List[str]:
    """The placeholder inputs that the multirotor results use, one line each."""
    out = [f"{k}: {v['value']:g} ({v['source']})" for k, v in st["electrical"].items() if v["placeholder"]]
    d = st["drag"]
    out.append(f"k_rotor_drag: {d['k_rotor_drag_kg']:g} kg ({d['k_rotor_drag_source']})")
    out.append("body drag CDx, CDy, CDz: AeroBuildup of the demo box and arm tubes, stand-in sizes: fit from the flight log")
    out.append("body box, arm tube radius, motor shape, s_ref: demo geometry, stand-in: measure the frame")
    if spec["mass"]["placeholder"]:
        out.append("mass model of node 1.2: the CG and inertia are a point-mass model (placeholder)")
    ps = spec.get("propulsion")
    if ps and ps["placeholder"]:
        out.append(f"propulsion system {ps['system_id']} (contract B, basis {ps['basis']}): placeholder")
    out.append("battery: nominal voltage, full capacity, no reserve; the chain resistance r_tot comes from the contract B file")
    return out


def multirotor_report(spec: Dict[str, Any], results: Dict[str, Any], ph: List[str]) -> str:
    """work/<aircraft>/asb/report.md of the multirotor jobs (ASD-STE100 prose)."""
    d = results["multirotor_drag"]
    L = ["# AeroSandbox multirotor model", "",
         "Written by `python -m aeroplan generate AeroSandbox <aircraft>`. Nothing here goes back into the ADH data "
         "except through `aeroplan build`.", "",
         "## Body drag (AeroBuildup of the box and the arm tubes)", "",
         f"Flow speed {d['speed_m_s']:g} m/s, air density {d['rho_kg_m3']:.4f} kg/m^3, S_ref {d['S_ref_m2']:.4f} m^2.", "",
         "| Axis | C_D A, AeroBuildup (m^2) | C_D A, Hoerner hand check (m^2) | Ratio | Asymmetry (+ and -) | C_D A used (m^2) | C_D on S_ref |",
         "|---|---|---|---|---|---|---|"]
    for ax in "xyz":
        L.append(f"| {ax} | {d['CdA_asb_m2'][ax]:.4f} | {d['hoerner_CdA_m2'][ax]:.4f} | {d['asb_over_hoerner'][ax]:.2f} | "
                 f"{d['asymmetry'][ax]:.1%} | {d['CdA_m2'][ax]:.4f} | {d['CD']['CD' + ax]:.3f} |")
    L += ["", f"The Hoerner column uses the crossflow drag of the bluff shapes (Hoerner, Fluid-Dynamic Drag, 1965, chapter 3). "
          f"AeroBuildup is a slender-body method and has no pressure drag on the flat front face of the box. The rule "
          f"`combine: {d['combine']}` picks the drag area of each axis. The box and arm sizes are stand-ins, so the drag area "
          "is a placeholder.", ""]
    e = results.get("emst_segments")
    if e is None:
        L += ["## EMST", "", "Not run: the document has no propulsion system yet (copy the Propalyser contract B file "
              "into `work/propalyser/<aircraft>/` and build again).", ""]
    else:
        L += ["## EMST segments (Bershadsky, Haviland, Johnson, AIAA 2016-0581, section III.A)", "",
              f"Mass {e['mass_kg']:.3f} kg, weight {e['weight_N']:.2f} N, air density {e['rho_kg_m3']:.4f} kg/m^3, "
              f"{e['n_rotors']} rotors.", "",
              "| Segment | V (m/s) | Climb (m/s) | Tilt (deg) | Thrust each (N) | RPM | Duty | ESC command (map) | P shaft (W) | "
              "P battery (W) | I total (A) | Endurance (min) |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for s in e["segments"]:
            cmd = f"{s['esc_command_equiv']:.3f}" if s.get("esc_command_equiv") is not None else "n/a"
            L.append(f"| {s['name']} | {s['speed_m_s']:g} | {s['climb_rate_m_s']:g} | {s['tilt_deg']:.2f} | "
                     f"{s['thrust_each_N']:.2f} | {s['rpm']:.0f} | {s['duty']:.3f} | {cmd} | {s['p_shaft_W']:.0f} | "
                     f"{s['p_battery_W']:.0f} | {s['i_total_A']:.1f} | {s['endurance_min']:.2f} |")
        f = e["full_throttle"]
        L += ["", f"Full throttle, static: {f['thrust_total_N']:.1f} N in total, thrust to weight {f['thrust_to_weight']:.2f}, "
              f"{f['rpm']:.0f} rpm, {f['i_total_A']:.1f} A.", ""]
    sc = results.get("emst_endurance")
    if sc:
        be, br = sc["best_endurance"], sc["best_range"]
        L += ["## Best speeds", "", f"- Best endurance: {be['speed_m_s']:g} m/s, {be['endurance_min']:.2f} min, tilt {be['tilt_deg']:.2f} deg.",
              f"- Best range: {br['speed_m_s']:g} m/s, {br['range_km']:.2f} km, tilt {br['tilt_deg']:.2f} deg.", ""]
    se = results.get("emst_sensitivity")
    if se:
        L += ["## Sensitivity of the hover endurance (central differences)", "",
              f"Base hover endurance {se['base_endurance_min']:.2f} min, relative step {se['step']:g}.", "",
              "| Parameter | x0 | d(endurance)/dx (min per unit) | % per % |", "|---|---|---|---|"]
        for k, v in se["parameters"].items():
            L.append(f"| {k} | {v['x0']:.4g} | {v['d_endurance_min_per_unit']:.4g} | {v['percent_per_percent']:.3f} |")
        L.append("")
    lv = results.get("emst_live")
    if lv:
        L += ["## Live propeller (Proptimiser BEMT in place of the CT/CP table)", "",
              f"Hover thrust per rotor {lv['table']['hover']['thrust_each_N']:.2f} N, air density {lv['rho_kg_m3']:.4f} kg/m^3, "
              f"{lv['n_rotors']} rotors. Each rotor has its own Propeller. The table row is the maker check: the CT/CP table of the "
              "propulsion dataset at J = 0 with the same electrical chain.", "",
              "| Case | Segment | RPM | P shaft each (W) | P battery (W) | I total (A) | Duty | Endurance (min) | Thrust spread (N) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for seg in ("hover", "climb"):
            t = lv["table"][seg]
            L.append(f"| maker table | {seg} | {t['rpm']:.0f} | {t['p_shaft_each_W']:.1f} | {t['p_battery_W']:.0f} | "
                     f"{t['i_total_A']:.2f} | {t['duty']:.3f} | {t['endurance_min']:.2f} | n/a |")
        for design, segs in lv["designs"].items():
            for seg in ("hover", "climb"):
                t = segs[seg]
                th = [r["thrust_N"] for r in t["rotors"]]
                L.append(f"| {design} | {seg} | {t['rpm']:.0f} | {t['p_shaft_each_W']:.1f} | {t['p_battery_W']:.0f} | "
                         f"{t['i_total_A']:.2f} | {t['duty']:.3f} | {t['endurance_min']:.2f} | {max(th) - min(th):.2g} |")
        fl = results["inputs"].get("proptimiser_files_sha256") or {}
        L += ["", "Files of the live propeller (sha256):"] + [f"- `{k}`: {v}" for k, v in sorted(fl.items())]
        L += ["", "The first design is Fit C: the BEMT blade is fitted to the maker bench table (in sample) and the airfoil is "
              "assumed. The other designs are comparison cases. The live result is a model value, not a measurement.", ""]
    L += ["## Placeholders that the results use", ""] + [f"- {p}" for p in ph]
    L += ["", "The rotor load is the CT/CP table of the propulsion dataset (manufacturer basis). The paper uses a NACA 0015 BEMT, "
          "and names this as its largest error source (section III.A.9). Rm and Re act on the current of one motor, "
          "Rb and Rw on the bus current (see the comment block in `tools/aerosandbox/model.py`).", ""]
    return "\n".join(L)


# ======================================================================================================== quadplane
RHO0 = 1.225                       # kg/m3, the air of the Proptimiser tables (component.RHO0)
LIFT_SYSTEM = "rosella_lift"
#: view values of the demo rotor discs (drawing only, no sizing meaning): thickness (m) and alpha
DISC_THICKNESS_M, DISC_ALPHA = 0.004, 0.3
#: the copied Currawong nodes. Each copy keeps its child nodes (ailerons under the wing, stabilizer under the empennage).
COPIED = ("1.2.2.3", "1.2.2.4")
#: segments of the energy record (names in the sizing result)
SEGMENTS = ("vtol_takeoff_climb", "transitions", "fw_climb", "transit_laps_rtl", "survey", "deploy_hover", "landing",
            "reserve")
#: ArduPilot SERVOn_FUNCTION of the motor outputs (motor1 to motor8 are 33 to 40, motor9 to motor12 are 82 to 85)
MOTOR_FUNCTION = {**{k: 32 + k for k in range(1, 9)}, **{k: 73 + k for k in range(9, 13)}}
#: where each point mass of the sizing result comes from (model.QuadplaneModel.design, section "mass list")
ORIGIN = {
    "wing": "kept from the Currawong wing mass (WINGS point masses, weighed)",
    "tail": "kept from the Currawong tail mass (TAIL-S point masses, weighed)",
    "tail_boom": "kept from the Currawong tail boom (TAIL-BOOM point mass, weighed)",
    "avionics_flight": "kept from the Currawong avionics (AVIONICS-REST point mass: servos, PDB, BMS, Cube, Herelink, Here4, wires)",
    "avionics_projects": "component avionics, projects_mass_kg (stand-in for the project equipment)",
    "fuselage": "shell area of the new fuselage times the Currawong mass per area (FUSELAGE-REST, weighed, over the area of the same body rule at the Currawong length)",
    "payload_cargo": "component cargo (aircraft/redback 1.2.17 cargo), released at the deployment",
    "landing_gear": "component landing_gear (stand-in for VTOL skids)",
    "cruise_motor": "kept from the Currawong nose motor (X5220), moved with the nose propeller hub",
    "cruise_esc": "kept from the Currawong cruise ESC, moved with the nose propeller hub",
    "cruise_prop": "kept from the Currawong cruise propeller, moved with the nose propeller hub",
    "cruise_rest": "kept from the Currawong propulsion rest mass, moved with the nose propeller hub",
    "battery": "AIAA 2016-0581 Eq. 4 scaled to the NXE 6S 4500 pack (component battery), cells and capacity from the sizing",
    "boom": "carbon tube: density times the tube section times the boom length (component boom_material)",
    "boom_clamp": "component boom, clamp_kg (stand-in)",
    "lift_front": "motor (fit on data/motor_survey.csv), carbon propeller (Eq. 5), ESC (fit on data/esc_survey.csv) and mount, at the front end of a boom",
    "lift_rear": "motor (fit on data/motor_survey.csv), carbon propeller (Eq. 5), ESC (fit on data/esc_survey.csv) and mount, at the rear end of a boom",
    "cables": "copper area from the peak current times the run lengths (model.py), with insulation factor (stand-in)",
}


class ModelFile:
    """settings/<aircraft>.json: the components of a model, and the compact result of its last solve. The spoke reads numbers
    out of it. It does not need the model classes (they need aerosandbox)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.d = json.loads(self.path.read_text(encoding="utf-8"))
        if self.d.get("format") != "aeroplan-asb-model/1":
            raise ValueError(f"{self.path.name}: format {self.d.get('format')!r}, not 'aeroplan-asb-model/1'")
        self.c = self.d["components"]

    def param(self, comp: str, key: str) -> Dict[str, Any]:
        return self.c[comp]["params"][key]

    def v(self, comp: str, key: str) -> Any:
        return self.param(comp, key)["value"]

    def e(self, comp: str, key: str) -> Dict[str, Any]:
        """{value, source, placeholder} of a param."""
        p = self.param(comp, key)
        return {"value": p["value"], "source": p.get("source", ""), "placeholder": bool(p.get("placeholder"))}

    @property
    def result(self) -> Dict[str, Any]:
        return self.d.get("result") or {}


def quad_settings(mf: ModelFile) -> Dict[str, Any]:
    """The numbers of the model file that `_ingest_quadplane` reads, as a nested dict."""
    return {"base": mf.v("airframe", "base"), "rotors": {"coaxial": {"spacing_over_D": mf.v("rotor", "coaxial_spacing_over_D")}},
            "fuselage": {"width_m": mf.e("fuselage", "width_m"), "height_m": mf.e("fuselage", "height_m")},
            "material": {"design_choice": mf.c["boom_material"]["name"]},
            "proptimiser_design": mf.v("rotor", "design"), "proptimiser_reference_radius_m": mf.v("rotor", "reference_radius_m"),
            "bershadsky": {"esc_peak_factor": mf.e("esc", "peak_factor")},
            "electrical": {"cell_nominal_V": mf.e("battery", "cell_nominal_V")},
            "limits": {"mtow_kg": mf.e("limits", "mtow_kg"), "thrust_to_weight": mf.e("limits", "thrust_to_weight"),
                       "reserve_hover_s": mf.e("mission", "reserve_hover_s"), "load_factor": mf.e("limits", "load_factor"),
                       "safety_factor": mf.e("limits", "safety_factor"),
                       "static_margin_target": mf.e("airframe", "static_margin_target"),
                       "battery_usable_fraction": mf.e("battery", "usable_fraction")}}


#: the limits that become `muas.target` requirements of node 1.2: key, component, param, bound, units (angles in rad)
TARGETS = (("mtow", "limits", "mtow_kg", "max", "kg"), ("thrust_to_weight_full_throttle", "limits", "thrust_to_weight", "min", "nd"),
           ("load_factor_boom", "limits", "load_factor", "target", "nd"), ("safety_factor_boom", "limits", "safety_factor", "min", "nd"),
           ("reserve_hover", "mission", "reserve_hover_s", "min", "s"), ("static_margin", "airframe", "static_margin_target", "target", "nd"),
           ("battery_usable_fraction", "battery", "usable_fraction", "max", "nd"), ("battery_c_rate", "battery", "c_rate_max", "max", "1/hour"),
           ("yaw_control_power", "control", "yaw_rad_s2", "min", "rad/s^2"), ("boom_tip_slope", "boom", "tip_slope_max_deg", "max", "deg"),
           ("boom_r_over_t", "boom", "r_over_t_max", "max", "nd"), ("boom_min_wall", "boom", "min_wall_m", "min", "m"),
           ("boom_resonance_margin", "boom", "resonance_margin", "min", "nd"), ("rotor_tip_mach", "rotor", "tip_mach_max", "max", "nd"),
           ("rotor_tip_clearance", "rotor", "tip_clearance_m", "min", "m"), ("esc_duty", "esc", "duty_max", "max", "nd"))


def _targets(mf: ModelFile) -> List[Dict[str, Any]]:
    """The ADH requirements (category sizing, `muas.target`) of the limits of the model."""
    out = []
    for key, comp, par, bound, units in TARGETS:
        p = mf.param(comp, par)
        value = float(p["value"])
        if units == "deg":
            value, units = math.radians(value), "rad"
        t = Target(key=key, value=value, bound=bound, units=units, source=p.get("source") or f"{comp}.{par} of settings/{mf.path.name}",
                   placeholder=bool(p.get("placeholder")))
        out.append(target_requirement(t, "sizing", f"Sizing limit {key} of the {mf.path.stem} model ({comp}.{par})."))
    return out


def _quad_result(ctx: Context):
    """(path, compact result, case name, model file) of settings/<aircraft>.json."""
    path = SETTINGS / f"{ctx.aircraft}.json"
    if not path.is_file():
        raise ValueError(f"{path.relative_to(ctx.root).as_posix()} is missing: run the sizing notebook "
                         f"(tools/aerosandbox/notebooks/{ctx.aircraft}_sizing.ipynb) first")
    mf = ModelFile(path)
    rep = mf.result
    if not rep.get("converged"):
        raise ValueError(f"{path.name}: the sizing result is missing or did not converge ({rep.get('error')}). The tree takes a "
                         "converged result only")
    return path, rep, rep.get("case", ctx.aircraft), mf


def _q(value: float, units: str) -> Dict[str, Any]:
    return {"value": float(value), "units": units}


def _pos(xyz) -> Dict[str, Any]:
    return {"frame": "design", "xyz": [float(c) for c in xyz], "units": "m"}


def _clean_copy(item: Dict[str, Any]) -> Dict[str, Any]:
    """A copy of a Currawong node (or subcomponent) for another aircraft: no mass roll-up, no raw-file pointers (CAD
    meshes, flow5 files, skin), no geometry tool. The Currawong CAD views are left out. The ADH shapes stay."""
    it = copy.deepcopy(item)
    m = it.get("muas")
    if m is not None:
        for k in ("mass_properties", "point_masses", "sources", "datasets", "skin", "geometry_tool", "propulsion_system",
                  "provenance"):
            m.pop(k, None)
        vis = [v for v in m.get("visual") or [] if "mesh" not in v]
        if vis:
            m["visual"] = vis
        else:
            m.pop("visual", None)
    if "wbs_no" in it:
        for k in adh_doc.child_keys(it):
            it[k] = _clean_copy(it[k])
    if it.get("subcomponents"):
        it["subcomponents"] = [_clean_copy(s) for s in it["subcomponents"]]
    return it


def _graft(doc: Dict[str, Any], wbs: str, node: Dict[str, Any]) -> None:
    """Put a copied WBS node (with its child nodes) in the document in place of the node of the same number."""
    dst = adh_doc.node(doc, wbs, create=True)
    dst.clear()
    dst.update(node)


def _fuselage_frames(mf: ModelFile, x_hub: float) -> List[np.ndarray]:
    """The frames of the new fuselage in the AeroSandbox frame (x aft): the rule of component.Fuselage.frames, with the hub x of
    the result and the pod tail end `x_tail_m` of the model file."""
    fus = component.Fuselage("fuselage", **{k: component.Param.from_json(v) for k, v in mf.c["fuselage"]["params"].items()})
    return fus.frames(float(x_hub), fus.num("x_tail_m"))


def _own_inertia(name: str, m: float, names: Dict[str, float], fuselage_length: float, tail_boom_length: float):
    """The own inertia of the items that model.QuadplaneModel gives one (same rules as QuadplaneModel.design, section "mass list")."""
    if name == "tail_boom":
        k = tail_boom_length ** 2 / 12.0
        return {"ixx": 0.0, "iyy": m * k, "izz": m * k}
    if name == "fuselage":
        k = fuselage_length ** 2 / 12.0
        return {"ixx": 0.0, "iyy": m * k, "izz": m * k}
    if name == "battery":
        return {"ixx": m * 0.02 / 12.0, "iyy": m * 0.13 / 12.0, "izz": m * 0.13 / 12.0}
    if name == "boom":
        k = names["L_boom"] ** 2 / 12.0
        return {"ixx": 0.0, "iyy": m * k, "izz": m * k}
    return None


def _rotors(rep: Dict[str, Any], st: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every lift rotor: ArduPilot motor number, hub, thrust axis, spin, in the design frame (FRD). The sizing result is x aft,
    z up: the numbers are computed in that frame and flipped at the end. H4: motors 5 to 8 in the Quad X order of
    multirotor.QUAD_X. H8: the same four stations, motors 5 to 8 on the upper rotors and 9 to 12 on the lower rotors."""
    n, d = rep["names"], rep["design"]
    z_hub = {it["name"]: it["z"] for it in rep["items"]}
    D = 2.0 * rep["R_m"]
    out = []
    for q, (pos, turn) in multirotor.QUAD_X.items():
        sx, sy = multirotor.SIGNS[pos]
        end = "lift_front" if sx > 0 else "lift_rear"        # FRD: the front rotors have x > 0
        x = n["x_f"] if sx > 0 else n["x_r"]
        # the cant is one tilt about the radial axis (CG to hub), so the tilt force is tangential and gives a yaw
        # moment of T sin(cant) rho. Its sign follows the spin: a cw rotor (seen from above) pushes the airframe
        # nose-left (+z) by its reaction torque, so its tilt force does the same. The tilts cancel in hover.
        rx, ry = x - rep["airframe"]["x_cg_m"], sy * d["y_b"]
        rho, s_tilt = math.hypot(rx, ry), 1.0 if turn == "cw" else -1.0
        axis = [-s_tilt * math.sin(d["cant"]) * ry / rho, s_tilt * math.sin(d["cant"]) * rx / rho, math.cos(d["cant"])]
        levels = [("upper", 0.0, 4 + q, turn)]
        if rep["config"] == "H8":
            levels.append(("lower", -float(st["rotors"]["coaxial"]["spacing_over_D"]) * D, 8 + q,
                           "cw" if turn == "ccw" else "ccw"))
        for tag, dz, motor, t in levels:
            out.append({"motor": motor, "position": pos, "level": tag, "turn_ardupilot": t,
                        "spin": multirotor.spin_from_ardupilot(t),
                        "hub": flip_point([x, sy * d["y_b"], z_hub[end] + dz]), "axis": flip_point(axis)})
    return sorted(out, key=lambda r: r["motor"])


def _lift_table(ctx: Context, st: Dict[str, Any]):
    """The BEMT samples of the scaled lift blade as a table (tables/lift_samples.json of the sizing), or (None, why)."""
    path = ctx.work / "tables" / "lift_samples.json"
    if not path.is_file():
        return None, f"{path.relative_to(ctx.root).as_posix()} is missing"
    d = json.loads(path.read_text(encoding="utf-8"))
    if d["key"].get("design") != st["proptimiser_design"]:
        return None, f"the BEMT samples are for {d['key'].get('design')}, the settings name {st['proptimiser_design']}"
    R0 = float(st["proptimiser_reference_radius_m"])
    cols: Dict[str, List[float]] = {k: [] for k in ("omega_rad_s", "v_x_m_s", "scale", "J", "CT", "CP", "T_N", "Q_Nm")}
    for w, V, s, T, Q in d["samples"]:
        n_, D = w / (2.0 * math.pi), 2.0 * R0 * s
        row = (w, V, s, V / (n_ * D), T / (RHO0 * n_ ** 2 * D ** 4), Q * w / (RHO0 * n_ ** 3 * D ** 5), T, Q)
        for k, v in zip(cols, row):
            cols[k].append(float(v))
    units = {"omega_rad_s": "rad/s", "v_x_m_s": "m/s", "scale": "nd", "J": "nd", "CT": "nd", "CP": "nd", "T_N": "N",
             "Q_Nm": "N*m"}
    return {"lift_bemt": {"columns": cols, "units": units}}, path


def _blade_count(ctx: Context, st: Dict[str, Any]) -> int:
    """N of the Proptimiser design file in work/<aircraft>/proptimiser/designs/, else 2 (the Redback FLUXER blade)."""
    import yaml

    f = ctx.work / "proptimiser" / "designs" / f"{st['proptimiser_design']}.yaml"
    if f.is_file():
        return int((yaml.safe_load(f.read_text(encoding="utf-8")).get("blade") or {}).get("N", 2))
    return 2


def _sizing_discipline(rep: Dict[str, Any], case: str, st: Dict[str, Any], tw: float) -> Dict[str, Any]:
    n, d = rep["names"], rep["design"]
    o = []

    def out(name, value, units):
        o.append({"name": name, "value": float(value), "units": units, "units_basis": "SI model output"})

    out("take_off_mass", n["M"], "kg")
    out("energy_total", rep["energy_total_Wh"], "Wh")
    out("energy_nominal_battery", rep["energy_nominal_Wh"], "Wh")
    for k in SEGMENTS:
        out(f"energy_{k}", rep["energy_Wh"][k], "Wh")
        out(f"time_{k}", rep["time_s"][k], "s")
    out("cells_s", rep["cells_s"], "nd")
    out("battery_capacity", d["cap_Ah"], "A*h")
    out("rotor_diameter", rep["D_m"] if "D_m" in rep else rep["D_in"] * 0.0254, "m")   # old result files hold D_in
    out("rotor_scale_over_reference", d["scale"], "nd")
    out("motor_kv", d["kv"], "rpm/V")
    out("motor_peak_torque", d["q_cap"], "N*m")
    out("motor_peak_current", n["I_pk"], "A")
    out("thrust_to_weight_at_full_throttle", tw, "nd")
    out("boom_outer_radius", d["r_boom"], "m")
    out("boom_wall", d["t_boom"], "m")
    out("boom_length", n["L_boom"], "m")
    out("boom_y", d["y_b"], "m")
    out("boom_clamp_x", -n["x_c"], "m")                 # FRD: x forward
    out("boom_dx", -d["dx"], "m")                        # FRD: forward of the wing root mid-chord
    out("rotor_cant", d["cant"], "rad")
    out("boom_f1", rep["f1_Hz"], "Hz")
    out("boom_f2", rep["f2_Hz"], "Hz")
    out("hover_1P", rep["f_hover_1P_Hz"], "Hz")
    out("control_roll", rep["control"]["roll"], "rad/s^2")
    out("control_pitch", rep["control"]["pitch"], "rad/s^2")
    out("control_yaw", rep["control"]["yaw"], "rad/s^2")
    out("control_required_roll_pitch", rep["control"]["alpha_req"], "rad/s^2")
    out("neutral_point_x", -rep["airframe"]["neutral_point_m"], "m")
    out("cg_x", -rep["airframe"]["x_cg_m"], "m")
    out("cruise_speed_laps", n["V_lap"], "m/s")
    out("cruise_speed_survey", n["V_map"], "m/s")
    out("stall_speed", n["Vs"], "m/s")
    for k, r in rep["rotors"].items():
        out(f"rotor_{k}_rpm", r["rpm"], "rpm")
        out(f"rotor_{k}_thrust", r["T_N"], "N")
        out(f"rotor_{k}_shaft_power", r["P_shaft_W"], "W")
        out(f"rotor_{k}_current", r["I_A"], "A")
    for tag, key in (("laps", "lap"), ("survey", "map")):      # the nose propeller at the two cruise speeds (shaft power = Q omega)
        c = rep["cruise"][key]
        out(f"cruise_{tag}_rpm", c["omega"] * 30.0 / math.pi, "rpm")
        out(f"cruise_{tag}_thrust", c["thrust"], "N")
        out(f"cruise_{tag}_shaft_power", c["Q"] * c["omega"], "W")
    ins = []
    for key, units in (("mtow_kg", "kg"), ("thrust_to_weight", "nd"), ("reserve_hover_s", "s"), ("load_factor", "nd"),
                       ("safety_factor", "nd"), ("static_margin_target", "nd"), ("battery_usable_fraction", "nd")):
        e = st["limits"][key]
        ins.append({"name": key, "value": float(e["value"]), "units": units,
                    "placeholder": bool(e.get("placeholder", False)), "source": e["source"]})
    act = [k for k, c in rep["constraints"].items() if c["enabled"] and not c["equality"] and c["margin"] < 1e-3]
    desc = (f"Rosella sizing, case {case} ({rep['config']}, {rep['cells_s']}S), level {rep.get('level_reached', rep.get('level'))}. "
            "Minimum mission energy under the limits of the settings. Active constraints: " + (", ".join(act) or "none") + ". "
            f"{len(rep.get('placeholders') or [])} settings values are stand-ins (the result file lists them).")
    return {"name": "sizing", "description": desc,
            "tools": [{"model_name": "Rosella quadplane propulsion sizing",
                       "generation_tool": "AeroSandbox (tools/aerosandbox/model.py, QuadplaneModel) with the Proptimiser BEMT",
                       "description": "Bershadsky, Haviland, Johnson, AIAA 2016-0581, with a geometric prop scale. The record is an "
                                      "estimate. Every input marked placeholder is a stand-in.",
                       "data_exchange": {"model_identifier": "rosella", "inputs": ins, "outputs": o}}]}


def _ingest_quadplane(doc: Dict[str, Any], ctx: Context):
    """Write the Rosella quadplane from the sizing result and the Currawong base (ADR 0022).

    Writes: copies of the Currawong wing, ailerons and empennage (stabilizer, tail boom). The new fuselage 1.2.2.2 (body
    from the rule of component.Fuselage). Two lift booms as subcomponents of 1.2.2 (`muas.tube`). 1.2.3.9: the cruise propeller and
    the lift rotors (`muas.propeller` role lift, motor 5 and up). 1.2.3: the lift propulsion system and its BEMT table.
    1.2: point masses, mass properties (roll-up with the own inertia of the long parts), `reference` (kind quadplane, MRP =
    the sized CG), initial conditions and the `sizing` record. 1.2.5.10: the autopilot (surface outputs of the base, motor
    outputs 5 and up). Every estimate has `placeholder: true` and names its source."""
    res_path, rep, case, mf = _quad_result(ctx)
    st = quad_settings(mf)
    base = source_tree.read(ctx.root / "aircraft" / st["base"])
    ref = ctx.source_ref(res_path, f"Rosella model file and sizing result {case}")
    n, d, changes = rep["names"], rep["design"], []
    cfg = rep["config"]

    def copy_ref(inst):
        return {**ref, "note": f"copy of aircraft/{st['base']} {inst}"}

    # ---- copies of the base airframe (wing, ailerons, empennage with the stabilizer and the tail boom)
    for wbs in COPIED:
        _graft(doc, wbs, _clean_copy(adh_doc.node(base.doc, wbs)))
    for inst in ("wing_main", "htail", "fin", "tail_boom"):
        it = adh_doc.find(doc, inst)
        m = it["muas"]
        if m.get("planform"):
            m["visual"] = [{"part": "wing" if inst == "wing_main" else inst, "generator": "planform",
                            "source": f"full lifting surface from the ADH planform of {inst} (copied from aircraft/{st['base']}, no CAD in Rosella)",
                            "placeholder": True}]
        set_sources(it, NAME, [copy_ref(inst)])
    tb = adh_doc.find(doc, "tail_boom")["muas"]["tube"]
    tb["source"] = f"Copy of aircraft/{st['base']} tail_boom. " + tb["source"]
    tb["placeholder"] = True
    changes.append(f"copied from {st['base']}: wing_main, ailerons, empennage (htail, fin, elevator, rudder, tail_boom)")

    # ---- the new fuselage
    tail_fr = body_frames(adh_doc.find(doc, "tail_boom")["geometry"]["body"])
    Lt = float(tail_fr[0][0, 0] - tail_fr[-1][0, 0])                        # tail boom length (x falls to the aft end, FRD)
    asb_frames = _fuselage_frames(mf, rep["airframe"]["x_nose_hub_m"])    # AeroSandbox frame (x aft)
    frames = [flip_array(f) for f in asb_frames]                           # design frame (FRD)
    Lf = float(asb_frames[-1][0, 0] - asb_frames[0][0, 0])
    fus = adh_doc.node(doc, "1.2.2.2", create=True)
    for k in [k for k in fus if k not in ("wbs_no", "name")]:
        del fus[k]
    fus["description"] = "Rosella fuselage: a superellipse body from the nose to the pod tail end (new, sized for the battery bay)"
    fus["geometry"] = {"body": body_adh(frames)}
    fm = adh_doc.muas(fus, "fuselage")
    fm["fidelity"] = "L1"
    fm["visual"] = [{"part": "fuselage", "generator": "body", "material": "body",
                     "source": "body lofted from the ADH body cross sections (superellipse rule of component.Fuselage). Width and "
                               f"height are stand-ins ({st['fuselage']['width_m']['value']} x {st['fuselage']['height_m']['value']} m).",
                     "placeholder": True}]
    set_sources(fus, NAME, [ref])
    changes.append(f"fuselage: {len(frames)} frames, x {frames[0][0, 0]:.3f} to {frames[-1][0, 0]:.3f} m (placeholder size)")

    # ---- lift booms: subcomponents of 1.2.2 with muas.tube
    frame = adh_doc.node(doc, "1.2.2", create=True)
    adh_doc.muas(frame, "airframe")
    z_b = float(next(i["z"] for i in rep["items"] if i["name"] == "boom"))
    half = 0.5 * n["L_boom"]
    r_o, t = d["r_boom"], d["t_boom"]
    mat = st["material"]["design_choice"]
    for side, nm in ((-1, "left"), (1, "right")):
        y = side * d["y_b"]
        p0, p1 = flip_point([n["x_c"] - half, y, z_b]), flip_point([n["x_c"] + half, y, z_b])    # forward end first (FRD)
        item = {"name": f"Lift boom {nm}",
                "description": f"Lift boom, {nm} side: a carbon tube clamped to the wing, a rotor at each end"}
        m = adh_doc.muas(item, f"boom_{nm}")
        m["fidelity"] = "L1"
        m["tube"] = {"radius": _q(r_o, "m"), "inner_radius": _q(r_o - t, "m"), "material": f"{mat.replace('_', '-')} carbon tube",
                     "p0": p0, "p1": p1, "placeholder": _tube_placeholder(mf), "material_data": _tube_material(mf),
                     "source": f"{case} sizing, boom component of tools/aerosandbox/settings/{ctx.aircraft}.json. Outer radius: "
                               f"{mf.param('boom', 'r_o').get('source', '')}. Wall: {mf.param('boom', 't').get('source', '')}"}
        m["visual"] = [{"part": f"boom_{nm}", "generator": "tube", "material": "boom",
                        "shape": {"p0": p0, "p1": p1, "radius_m": r_o},
                        "source": "Boom of the sizing result (outer radius, length).", "placeholder": True}]
        set_sources(item, NAME, [ref])
        adh_doc.put_subcomponent(frame, item)
    changes.append(f"booms: 2 tubes, OD {2000 * r_o:.2f} mm, wall {1000 * t:.2f} mm, length {1000 * n['L_boom']:.0f} mm, "
                   f"y +/-{d['y_b']:.3f} m")

    # ---- 1.2.3.9: the cruise propeller (copy) and the lift rotors
    prop_node = adh_doc.node(doc, "1.2.3.9", create=True)
    base_cruise = adh_doc.find(base.doc, "prop_cruise")
    cruise = _clean_copy(base_cruise)
    cm = cruise["muas"]
    hub = list(base_cruise["muas"]["propeller"]["hub"]["xyz"])
    hub[0] = -rep["airframe"]["x_nose_hub_m"]                              # FRD: x forward
    cm["propeller"]["hub"] = _pos(hub)
    cm["fidelity"] = "L1"
    ps = copy.deepcopy(base_cruise["muas"]["propulsion_system"])
    ps.update({"source": copy_ref("prop_cruise"), "placeholder": True})
    ps["warnings"] = list(ps.get("warnings") or []) + [
        f"Copied from aircraft/{st['base']} prop_cruise: the Currawong nose motor and propeller. The hub x follows the sized CG."]
    cm["propulsion_system"] = ps
    cm["visual"] = [{"part": "propeller_cruise", "generator": "disc", "material": "rotor",
                     "shape": {"centre": hub, "axis": list(cm["propeller"]["thrust_axis"]),
                               "radius_m": 0.5 * cm["propeller"]["diameter"]["value"],
                               "thickness_m": DISC_THICKNESS_M, "alpha": DISC_ALPHA},
                     "source": "Demo disc of the cruise propeller diameter (no CAD).", "placeholder": True}]
    prop_node.clear()
    prop_node.update(cruise)
    bref = assets.item_dataset(base_cruise, "propulsion")
    if bref:
        be = assets.entry(base.doc, bref["ref"])
        aid = assets.register_dataset(ctx.acft, be["name"], base.datasets[be["id"]], tool=be["tool"], role=be["role"],
                                      dataset_role="propulsion", meta=copy.deepcopy(be["dataset"]),
                                      built_against=f"{ctx.aircraft}@{ctx.acft.version}",
                                      note=f"Copy of the dataset of aircraft/{st['base']} (Currawong nose propeller).")
        assets.set_item_dataset(prop_node, "propulsion", aid)
    rotors = _rotors(rep, st)
    D = 2.0 * rep["R_m"]
    for r in rotors:
        item = {"name": f"Lift rotor {r['motor']}",
                "description": f"Lift rotor, ArduPilot motor {r['motor']}, {r['position'].replace('_', ' ')}"
                               + (f", {r['level']} of the coaxial pair" if cfg == "H8" else "")}
        m = adh_doc.muas(item, f"prop_lift_{r['motor']}")
        m["fidelity"] = "L1"
        m["propeller"] = {"role": "lift", "hub": _pos(r["hub"]), "thrust_axis": r["axis"], "spin": r["spin"],
                          "diameter": _q(D, "m"), "motor": r["motor"], "system": LIFT_SYSTEM}
        m["visual"] = [{"part": f"rotor_{r['motor']}", "generator": "disc", "material": "rotor",
                        "shape": {"centre": r["hub"], "axis": r["axis"], "radius_m": 0.5 * D, "thickness_m": DISC_THICKNESS_M,
                                  "alpha": DISC_ALPHA},
                        "source": "Demo rotor disc of the sized diameter (no CAD). Turns about the thrust axis through the hub.",
                        "placeholder": True}]
        set_sources(item, NAME, [ref])
        adh_doc.put_subcomponent(prop_node, item)
    changes.append(f"rotors: cruise prop + {len(rotors)} lift ({cfg}), D {D:.4f} m ({1000 * D:.1f} mm), motors "
                   f"{rotors[0]['motor']} to {rotors[-1]['motor']}, cant {math.degrees(d['cant']):.2f} deg")

    # ---- 1.2.3 propulsion: the lift system and its BEMT table
    prop = adh_doc.node(doc, "1.2.3", create=True)
    for k in [k for k in prop if k not in adh_doc.child_keys(prop)]:       # keep the child node 1.2.3.9
        del prop[k]
    prop.update({"wbs_no": "1.2.3", "name": "Propulsion", "description": "Rosella propulsion: the Currawong nose propeller "
                                                                         "(cruise) and the sized lift rotors"})
    pm_ = adh_doc.muas(prop, "propulsion")
    p_max = max(r["P_shaft_W"] for k, r in rep["rotors"].items() if k.startswith("MAX"))
    blades = _blade_count(ctx, st)
    warn = [f"Estimate from the {case} sizing. Motor, ESC and battery are sized values, not maker parts.",
            "Propeller inertia: a rod of the propeller mass and length D (stand-in).",
            f"Blade count {blades}: from the Proptimiser design {st['proptimiser_design']}.",
            "Each lift rotor tilts about its radial axis (CG to hub) by the cant. The tilt sign follows the spin, so the tilts "
            "cancel in hover. the sizing gives the cant size only.",
            ("H8: motors 5 to 8 are the upper rotors, 9 to 12 the lower rotors of each station, counter-rotating, spaced "
             f"{st['rotors']['coaxial']['spacing_over_D']} D. The ArduPilot frame class and motor order are a stand-in: check them."
             if cfg == "H8" else
             "H4: motors 5 to 8 follow the ArduPilot Quad X order (front right, rear left, front left, rear right).")]
    pm_["propulsion_system"] = {
        "system_id": LIFT_SYSTEM, "basis": "sizing estimate", "p_max": _q(p_max, "W"), "diameter": _q(D, "m"),
        "blades": blades, "ixx": _q(n["m_prop"] * D ** 2 / 12.0, "kg*m^2"),
        "model": f"Rosella lift rotor: {st['proptimiser_design']} scaled to {D:.4f} m (Proptimiser scale {d['scale']:.4f})",
        "motor": {"model": "sized motor (not a maker part)", "kv": _q(d["kv"], "rpm/V"), "r": _q(n["rm"], "ohm"),
                  "i0": _q(n["i0"], "A"), "mass": _q(n["m_motor"], "kg"), "imax_continuous": _q(n["I_pk"], "A")},
        "esc": {"model": "sized ESC (not a maker part)",
                "imax_continuous": _q(float(st["bershadsky"]["esc_peak_factor"]["value"]) * n["I_pk"], "A"),
                "vmax": _q(rep["cells_s"] * 4.2, "V")},
        "battery": {"model": "sized pack (not a maker part)", "cells_s": rep["cells_s"], "cells_p": 1,
                    "capacity": _q(d["cap_Ah"], "A*h"),
                    "v_nominal": _q(rep["cells_s"] * float(st["electrical"]["cell_nominal_V"]["value"]), "V"),
                    "mass": _q(n["m_batt"], "kg")},
        "warnings": warn, "source": ref, "placeholder": True}
    table, why = _lift_table(ctx, st)
    if table is None:
        pm_["propulsion_system"]["warnings"].append("No BEMT table of the lift blade: " + str(why))
        changes.append("no lift BEMT table (open gap): " + str(why))
    else:
        meta = {"form": "tables", "fidelity": "L1", "units_system": "SI", "placeholder": True,
                "model_description": {"generation_tool": "Proptimiser BEMT (NeuralFoil sections) via tools/aerosandbox/model.py (QuadplaneModel)",
                                      "model_name": f"{st['proptimiser_design']} scaled",
                                      "description": "CT and CP samples of the lift blade at the scales and shaft speeds of the "
                                                     "sizing table (hover and 2.5 m/s climb)"},
                "notes": [f"Sea-level density {RHO0} kg/m3. CT = T/(rho n^2 D^4), CP = Q omega/(rho n^3 D^5), n in rev/s, "
                          "D = 2 R_ref scale. A scaled copy of a measured blade: a model value, not a measurement.",
                          "Not the Aerolink propulsion table (no throttle map): the dataset role is other."]}
        aid = assets.register_dataset(ctx.acft, "propulsion.rosella_lift_bemt", table, tool=NAME,
                                      role="BEMT samples of the scaled lift blade", dataset_role="other", meta=meta,
                                      derived_from=[ref["asset"]], built_against=f"{ctx.aircraft}@{ctx.acft.version}")
        assets.set_item_dataset(prop, "other", aid)
        changes.append(f"lift system {LIFT_SYSTEM}: P_max {p_max:.0f} W, "
                       f"{len(table['lift_bemt']['columns']['J'])} BEMT samples (dataset)")
    set_sources(prop, NAME, [ref])

    # ---- 1.2 point masses, mass properties, reference, sizing
    air = adh_doc.node(doc, "1.2", create=True)
    am = adh_doc.muas(air, f"{ctx.aircraft}_airvehicle")
    counts: Dict[str, int] = {}
    pms, items = [], []
    for it in rep["items"]:
        counts[it["name"]] = counts.get(it["name"], 0) + 1
        xyz = flip_point([it["x"], it["y"], it["z"]])                          # the sizing result is x aft, z up
        pms.append({"tag": f"{it['name']}_{counts[it['name']]}", "mass": _q(it["mass_kg"], "kg"), "position": _pos(xyz),
                    "placeholder": True, "source": f"{case} sizing, item {it['name']}: {ORIGIN[it['name']]}"})
        row = {"mass_kg": it["mass_kg"], "xyz": xyz}
        own = _own_inertia(it["name"], it["mass_kg"], n, Lf, Lt)
        if own:
            row["inertia_own"] = own
        items.append(row)
    roll = mass_model.rollup(items)
    if abs(roll["mass_kg"] - n["M"]) > 1e-6:
        raise ValueError(f"the items sum to {roll['mass_kg']:.6f} kg, the result says {n['M']:.6f} kg")
    cg = roll["cg"]
    rin = rep["inertia_kg_m2"]
    am["point_masses"] = pms
    am["mass_properties"] = {
        "mass": _q(roll["mass_kg"], "kg"), "cg": _pos(cg),
        "inertia": {"axes": "parallel_to_design", "products_convention": "+integral(xy dm)", "units": "kg*m^2", **roll["inertia"]},
        "source": "estimate", "placeholder": True,
        "notes": [f"Roll-up of the {len(pms)} point masses of the {case} sizing result (mass_model.rollup). The sizing owns the "
                  "mass model until a SpecSheet exists (ADR 0022).",
                  "Own inertia added for tail_boom, fuselage, battery and the two lift booms (the rules of model.QuadplaneModel). Every "
                  "other item is a point mass.",
                  f"The sizing result gives Ixx {rin['ixx']:.4f}, Iyy {rin['iyy']:.4f}, Izz {rin['izz']:.4f} kg m^2. Its Ixx is about "
                  "y = 0 and z = 0, not about the CG height. This roll-up is about the CG.",
                  f"The sizing CG x is {-rep['airframe']['x_cg_m']:.6f} m (FRD: the static margin target ahead of the neutral "
                  "point)."]}
    base_ref = adh_doc.node(base.doc, "1.2")["muas"]["reference"]
    cg_pt = _pos(cg)
    am["reference"] = {
        "design_frame": base_ref["design_frame"], "body_frame": "FRD", "euler": "3-2-1/NED", "kind": "quadplane",
        "s_ref": copy.deepcopy(base_ref["s_ref"]), "b_ref": copy.deepcopy(base_ref["b_ref"]),
        "c_ref": copy.deepcopy(base_ref["c_ref"]), "nominal_cg": cg_pt,
        "mrp": {"definition": "nominal_cg", "config_id": f"{ctx.aircraft}.nominal", "point": dict(cg_pt)},
        "surface_signs": copy.deepcopy(base_ref.get("surface_signs") or {}),
        "placeholder_fields": ["nominal_cg", "mrp"],
        "notes": [f"Quadplane. S, b and c: the Currawong wing (copied from aircraft/{st['base']}). The design frame has the wing "
                  "root leading edge at x = 0.",
                  "MRP = the sized CG of the mass model. It lies ahead of the neutral point (vortex lattice) by the static margin "
                  "target times c_ref. It is a sizing value (placeholder)."]}
    am["initial_conditions"] = {"rate_frame": "local_NED", "latitude_type": "geodetic", "attitude_sequence": "3-2-1", "units": "SI",
                                "values": {"speed_mps": float(n["V_lap"]), "altitude_m": 0.0}, "placeholder": True}
    t_full = 0.5 * len(rotors) * (rep["rotors"]["MAX_f"]["T_N"] + rep["rotors"]["MAX_r"]["T_N"])
    tw = t_full / (n["M"] * G0)
    sizing = _sizing_discipline(rep, case, st, tw)
    air["performance"] = [sizing] + [x for x in air.get("performance") or [] if x.get("name") != "sizing"]
    set_sources(air, NAME, [ref])
    changes.append(f"mass: {roll['mass_kg']:.3f} kg, CG x {cg[0]:.4f} m (MRP), Ixx {roll['inertia']['ixx']:.3f} Iyy "
                   f"{roll['inertia']['iyy']:.3f} Izz {roll['inertia']['izz']:.3f} kg m^2 (placeholder)")
    changes.append(f"sizing: {len(sizing['tools'][0]['data_exchange']['outputs'])} outputs, energy "
                   f"{rep['energy_total_Wh']:.0f} Wh, T/W {tw:.2f}")

    # ---- the limits of the model as requirements of node 1.2
    reqs = [r for r in air.get("requirements") or [] if not str(r.get("name", "")).startswith("sizing:")] + _targets(mf)
    air["requirements"] = reqs
    changes.append(f"requirements: {len(reqs)} sizing targets (limits of the model file)")

    # ---- 1.2.5.10 autopilot: the surface outputs of the base, the motor outputs 5 and up
    ap = adh_doc.node(doc, "1.2.5.10", create=True)
    apm = adh_doc.muas(ap, "autopilot")
    base_ap = adh_doc.node(base.doc, "1.2.5.10")["muas"]["autopilot"]
    outs = [copy.deepcopy(o) for o in base_ap["outputs"] if o["function"] in ("aileron", "elevator", "throttle", "rudder")]
    for r in rotors:
        k = r["motor"]
        outs.append({"channel": k, "function": f"motor{k}", "targets": [f"prop_lift_{k}"], "placeholder": True,
                     "source": f"ArduPlane quadplane (Q_ENABLE): output {k} drives lift motor {k} (SERVO{k}_FUNCTION "
                               f"{MOTOR_FUNCTION[k]}). The ESC end points come with the maker part: the lift motors and ESCs "
                               "are sized values."})
    apm["autopilot"] = {"firmware": "ArduPlane", "outputs": outs,
                        "notes": [f"Quadplane {cfg}: outputs 1 to 4 are the Currawong surfaces and throttle (copied). Lift motors "
                                  f"{rotors[0]['motor']} to {rotors[-1]['motor']} on the outputs of the same number. Frame class and "
                                  "motor order: see the warnings of the lift propulsion system."]}
    changes.append(f"autopilot: ArduPlane, outputs 1 to 4 (copied) and motor{rotors[0]['motor']} to motor{rotors[-1]['motor']}")
    return changes


def _tube_placeholder(mf: ModelFile) -> bool:
    """A boom tube is a stand-in while its radius or wall is a free design variable or a stand-in. A fixed, sourced size (a bought
    tube) is not."""
    return any(bool(mf.param("boom", k).get("free") or mf.param("boom", k).get("placeholder")) for k in ("r_o", "t"))


def _tube_material(mf: ModelFile) -> Dict[str, Any]:
    """The material of the boom tube (`muas.tube.material_data`): the numbers the beam formulas of the sizing use."""
    m = mf.c["boom_material"]["params"]
    return {"name": mf.c["boom_material"]["name"], "youngs_modulus": _q(m["E_Pa"]["value"], "Pa"),
            "youngs_modulus_compression": _q(m["E_c_Pa"]["value"], "Pa"), "density": _q(m["density_kg_m3"]["value"], "kg/m^3"),
            "tensile_strength": _q(m["tensile_strength_Pa"]["value"], "Pa"),
            "compressive_strength": _q(m["compressive_strength_Pa"]["value"], "Pa"),
            "source": f"material component {mf.c['boom_material']['name']} of settings/{mf.path.name}: " + m["E_Pa"].get("source", ""),
            "placeholder": any(bool(p.get("placeholder")) for p in m.values())}


def ingest(doc: Dict[str, Any], ctx: Context):
    if (SETTINGS / f"{ctx.aircraft}.json").is_file():
        return _ingest_quadplane(doc, ctx)
    st = ctx.settings()
    if st.get("kind") == "multirotor":
        return _ingest_multirotor(doc, ctx, st)
    path = ctx.work / FILE
    if not path.is_file():
        return None
    values = parse(path.read_text(encoding="utf-8"))
    unknown = sorted(set(values) - set(UNITS))
    if unknown:
        raise ValueError(f"{FILE}: outputs with no unit rule in tools/aerosandbox/spoke.py UNITS: {unknown}")
    checks = consistency(values)
    outputs = [{"name": k, "value": v, "units": UNITS[k][0], "units_basis": UNITS[k][1]} for k, v in values.items()]
    air = adh_doc.node(doc, "1.2", create=True)
    adh_doc.muas(air, f"{ctx.aircraft}_airvehicle")
    sizing = {"name": "sizing", "description": "Initial sizing of the aircraft (the first design stage). "
                                               "Unit checks: " + "; ".join(checks),
              "tools": [{"model_name": "Athena initial sizing", "generation_tool": "AeroSandbox (Athena sizing scripts)",
                         "description": "Printout of the sizing scripts. The printout gives no units: see units_basis "
                                        "of each output (AeroPlan tools/aerosandbox/spoke.py).",
                         "data_exchange": {"model_identifier": "athena", "inputs": [], "outputs": outputs}}]}
    perf = [d for d in air.get("performance") or [] if d.get("name") != "sizing"]
    air["performance"] = [sizing] + perf
    set_sources(air, NAME, [ctx.source_ref(path, "initial sizing outputs (Athena)")])
    return [f"sizing: {len(outputs)} outputs, {sum(u[1] == 'unknown' for u in UNITS.values())} without a known unit"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _generate_multirotor(doc: Dict[str, Any], ctx: Context, st: Dict[str, Any]) -> List[Path]:
    """The multirotor jobs: body drag, then (with a propulsion system in the document) the EMST jobs."""
    out = ctx.work / "asb"
    out.mkdir(parents=True, exist_ok=True)
    spec = multirotor_spec(doc, st, ctx)
    drag = run({"job": "multirotor_drag", "spec": spec})["multirotor_drag"]
    results: Dict[str, Any] = {"multirotor_drag": drag}
    spec = multirotor_spec(doc, st, ctx, drag=drag["CD"])
    if spec["propulsion"] is None:
        print("AeroSandbox: the document has no propulsion system (Propalyser contract B file missing): "
              "body drag only, no EMST results")
    else:
        for job in ("emst_segments", "emst_endurance", "emst_sensitivity"):
            results[job] = run({"job": job, "spec": spec})[job]
    files = {}
    if spec["propulsion"] is not None and st.get("proptimiser_design"):
        names = [st["proptimiser_design"]] + list(st.get("proptimiser_compare") or [])
        home = ctx.work / "proptimiser"
        for name in names:
            for f in (home / "designs" / f"{name}.yaml", home / "propellers" / f"{name}.state.json"):
                if not f.is_file():
                    raise ValueError(f"{f} is missing: copy the Proptimiser design and state file by hand")
                files[f.name] = _sha(f)
        spec["live"] = {"home": str(home), "designs": names}
        results["emst_live"] = run({"job": "emst_live", "spec": spec})["emst_live"]
    ph = multirotor_placeholders(st, spec)
    results["inputs"] = {"s_ref_m2": spec["reference"]["s_m2"], "mass_kg": spec["mass"]["mass_kg"],
                         "date": date.today().isoformat(), "placeholders": ph,
                         "propulsion_system": (spec["propulsion"] or {}).get("system_id"),
                         "proptimiser_files_sha256": files}
    res_file = out / RESULTS
    res_file.write_text(json.dumps(results, indent=1), encoding="utf-8")
    report = out / "report.md"
    report.write_text(multirotor_report(spec, results, ph), encoding="utf-8")
    seg = results.get("emst_segments")
    if seg:
        h = seg["segments"][0]
        print(f"AeroSandbox: hover {h['rpm']:.0f} rpm, {h['p_battery_W']:.0f} W, {h['i_total_A']:.1f} A, "
              f"endurance {h['endurance_min']:.1f} min")
    for design, segs in (results.get("emst_live") or {}).get("designs", {}).items():
        h = segs["hover"]
        print(f"AeroSandbox: live {design} hover {h['rpm']:.0f} rpm, {h['p_shaft_each_W']:.0f} W shaft each, "
              f"{h['p_battery_W']:.0f} W, {h['i_total_A']:.1f} A, endurance {h['endurance_min']:.1f} min")
    print(f"AeroSandbox: CDx {drag['CD']['CDx']:.3f}, CDy {drag['CD']['CDy']:.3f}, CDz {drag['CD']['CDz']:.3f}")
    return [report, res_file]


def generate(doc: Dict[str, Any], ctx: Context) -> List[Path]:
    """Build the AeroSandbox model of the aircraft and run the jobs. Files go to work/<aircraft>/asb/."""
    if (SETTINGS / f"{ctx.aircraft}.json").is_file():
        raise ValueError(f"{ctx.aircraft} is a sized quadplane: its model runs in the notebook "
                         f"(tools/aerosandbox/notebooks/{ctx.aircraft}_sizing.ipynb), not in generate")
    st = ctx.settings()
    if st.get("kind") == "multirotor":
        return _generate_multirotor(doc, ctx, st)
    spec = spec_from_doc(doc, st, ctx)
    home = ctx.work / "proptimiser"
    design = home / "designs" / f"{st['proptimiser_design']}.yaml"
    state = home / "propellers" / f"{st['proptimiser_design']}.state.json"
    for f in (design, state):
        if not f.is_file():
            raise ValueError(f"{f} is missing: copy the Proptimiser design and state file by hand")
    spec["propulsion"]["proptimiser_home"] = str(home)
    out = ctx.work / "asb"
    out.mkdir(parents=True, exist_ok=True)
    alphas = st["alpha_deg"]
    results = {
        "geometry": run({"job": "geometry", "spec": spec, "out_dir": str(out), "main_wing": st["wings"][0]}),
        "polar": run({"job": "polar", "spec": spec, "out_dir": str(out), "alpha_deg": alphas,
                             "reference": flow5_polar(doc, ctx, alphas)}),
        "cruise_trim": run({"job": "cruise_trim", "spec": spec}),
        "static_check": run({"job": "static_check", "spec": spec}),
    }
    results["polar"]["reference"] = flow5_polar(doc, ctx, alphas)
    ref = planform_reference(adh_doc.find(doc, st["wings"][0])["muas"]["planform"])
    g = results["geometry"]["geometry"]
    for key, name in (("s_m2", "area_m2"), ("b_m", "span_m"), ("mac_m", "mac_m")):
        print(f"AeroSandbox: {key} {g[key]:.5f} (planform {ref[name]:.5f})")
    np_file = _write_neutral_point(doc, ctx, st, spec)
    hashes = {design.name: _sha(design), state.name: _sha(state)}
    results_file = out / "results.json"
    results_file.write_text(json.dumps({k: {a: b for a, b in v.items() if a != "ok"} for k, v in results.items()},
                                       indent=1), encoding="utf-8")
    report = out / "report.md"
    report.write_text(spec_report(spec, results, hashes, spec_placeholders(spec)), encoding="utf-8")
    return [report, results_file, np_file] + [Path(f) for r in results.values() for f in r.get("files", [])]


def _tree_hash(tree: Path) -> str:
    """sha256 of every JSON file of the tree (names and bytes, sorted)."""
    h = hashlib.sha256()
    for f in sorted(tree.rglob("*.json")):
        h.update(f.relative_to(tree).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def _write_neutral_point(doc: Dict[str, Any], ctx: Context, st: Dict[str, Any], spec: Dict[str, Any]) -> Path:
    """work/aerosandbox/<aircraft>/neutral_point.json: the neutral point of the tree (job neutral_point), the wing root leading edge
    x (ADR 0023: it must be 0), a hash of the tree files and the date. The SpecSheet spoke reads this file for the battery trim.
    Run generate again after a change of the wing, tail or c_ref."""
    res = run({"job": "neutral_point", "spec": spec})["neutral_point"]
    # the job runs in the AeroSandbox frame (x aft): the file holds the design frame (FRD, x forward)
    res = {**res, "x_np_m": -res["x_np_m"], "x_ref_m": -res["x_ref_m"], "frame": "design (FRD: x forward)"}
    wing = adh_doc.find(doc, st["wings"][0])["muas"]["planform"]
    wing_le_x = float(planform_le_x(wing["position"]["xyz"][0], wing["sections"][0]["x_offset"]))
    path = ctx.work / "neutral_point.json"
    path.write_text(json.dumps({"aircraft": ctx.aircraft, **res, "wing_root_le_x_m": wing_le_x,
                                "tree_sha256": _tree_hash(ctx.root / "aircraft" / ctx.aircraft), "date": date.today().isoformat()},
                               indent=2) + chr(10), encoding="utf-8")
    print(f"AeroSandbox: wing root leading edge x = {wing_le_x:+.4f} m (must be 0, ADR 0023)")
    print(f"AeroSandbox: neutral point x_np = {res['x_np_m']:+.4f} m, mac = {res['mac_m']:.4f} m -> {path.relative_to(ctx.root).as_posix()}")
    return path


def setup(ctx: Context, proptimiser: Optional[str] = None) -> Dict[str, str]:
    """Make the AeroSandbox Python for this machine (see setup_venv)."""
    return setup_venv(proptimiser, ctx.settings().get("proptimiser_git"))


def describe() -> str:
    return describe_venv()

