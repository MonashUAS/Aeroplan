"""AeroSandbox spoke: the initial sizing -> ADH performance record of the air vehicle, and the ADH aircraft ->
an AeroSandbox model with the propulsion chain (generate).

Input (git ignores it): work/aerosandbox/<aircraft>/athena_outputs.txt, the printout of the Athena sizing scripts
(AeroSandbox). One "Name: value" line for each output. The file gives no units.

What ingest writes: one ADH `Discipline` "sizing" in `performance` of node 1.2 AirVehicle. Its tool record
(`ModelDescription`) holds every output in `data_exchange.outputs` as {name, value, units, units_basis}.

Units: the printout has none. `UNITS` below gives each output a unit and says why:
  - "consistency": a relation between the outputs confirms the unit (for example b^2 / S = AR, or the mass sum).
  - "magnitude":   the value fits only one plausible unit for this aircraft. Not proven.
  - "unknown":     no unit can be given. The value is kept with units "unknown".
What generate does (after `python -m aeroplan setup AeroSandbox`, once for each computer): spec.py builds a tool-neutral spec
from the ADH document (wing, tail, fuselage, mass model, propeller installation, motor, ESC, battery). The spec goes to
tools/aerosandbox/asb_worker.py in tools/aerosandbox/.venv. Jobs: geometry (three-view, 3D view), polar (AeroBuildup against the
flow5 aero model), cruise_trim (one Opti problem: airframe, Proptimiser BEMT and the Propalyser motor and ESC chain) and
static_check (the chain at full command against the Propalyser table). Files go to work/<aircraft>/asb/. generate
changes no ADH data.

The sizing stage comes before flow5. Its geometry values do not set the flow5 geometry. The datum report lists the
differences.

Multirotor (settings `kind: multirotor`): there is no Athena printout. `ingest` seeds the aircraft from the `multirotor`
block of the settings (aeroplan.multirotor.seed: reference, four lift rotors, motor outputs, ground contacts, demo
shapes) and reads `work/<aircraft>/asb/multirotor_results.json`, when it exists, into the body-drag aero dataset
(src/aeroplan/multirotor_aero.py) and the `sizing` performance record of node 1.2 (the EMST results). `generate` runs the
worker jobs multirotor_drag, emst_segments, emst_endurance and emst_sensitivity (the EMST jobs need the propulsion
system of the Propalyser spoke) and writes that file and `report.md`. With `proptimiser_design` in the settings it also runs
emst_live: hover and climb with the live Proptimiser BEMT (`static_and_axial`, one Propeller for each rotor) for that design
and for each design of `proptimiser_compare`. The Proptimiser design and state files come from
work/<aircraft>/proptimiser/ (copy them by hand). Their sha256 go into the results file. Order: build, generate, build.
"""
from __future__ import annotations

import copy
import re
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from aeroplan import adh_doc, multirotor, multirotor_aero
from aeroplan.daveml_adh import from_xml
from aeroplan.dml_validate import validate_dml
from aeroplan.geometry import planform_reference
from aeroplan.spokes import Context, set_sources

from . import runner, spec as asb_spec

NAME = "AeroSandbox"
FILE = "athena_outputs.txt"
RESULTS = "multirotor_results.json"

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
                  "tools": [{"model_name": "EMST segment analysis", "generation_tool": "AeroSandbox worker (asb_worker.py)",
                             "description": "Bershadsky, Haviland, Johnson, AIAA 2016-0581, section III.A, eq. (9) to (12). "
                                            "Inputs marked placeholder are stand-ins.",
                             "data_exchange": {"model_identifier": "emst", "inputs": ins, "outputs": outputs}}]}
        air["performance"] = [sizing] + [x for x in air.get("performance") or [] if x.get("name") != "sizing"]
        changes.append(f"sizing: {len(outputs)} EMST outputs")
    else:
        changes.append("no EMST results (no propulsion system when generate ran)")
    set_sources(air, NAME, [ref_src])
    return changes


def ingest(doc: Dict[str, Any], ctx: Context):
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
    spec = asb_spec.multirotor_spec(doc, st, ctx)
    drag = runner.run({"job": "multirotor_drag", "spec": spec})["multirotor_drag"]
    results: Dict[str, Any] = {"multirotor_drag": drag}
    spec = asb_spec.multirotor_spec(doc, st, ctx, drag=drag["CD"])
    if spec["propulsion"] is None:
        print("AeroSandbox: the document has no propulsion system (Propalyser contract B file missing): "
              "body drag only, no EMST results")
    else:
        for job in ("emst_segments", "emst_endurance", "emst_sensitivity"):
            results[job] = runner.run({"job": job, "spec": spec})[job]
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
        results["emst_live"] = runner.run({"job": "emst_live", "spec": spec})["emst_live"]
    ph = asb_spec.multirotor_placeholders(st, spec)
    results["inputs"] = {"s_ref_m2": spec["reference"]["s_m2"], "mass_kg": spec["mass"]["mass_kg"],
                         "date": date.today().isoformat(), "placeholders": ph,
                         "propulsion_system": (spec["propulsion"] or {}).get("system_id"),
                         "proptimiser_files_sha256": files}
    res_file = out / RESULTS
    res_file.write_text(json.dumps(results, indent=1), encoding="utf-8")
    report = out / "report.md"
    report.write_text(asb_spec.multirotor_report(spec, results, ph), encoding="utf-8")
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
    st = ctx.settings()
    if st.get("kind") == "multirotor":
        return _generate_multirotor(doc, ctx, st)
    spec = asb_spec.spec_from_doc(doc, st, ctx)
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
        "geometry": runner.run({"job": "geometry", "spec": spec, "out_dir": str(out), "main_wing": st["wings"][0]}),
        "polar": runner.run({"job": "polar", "spec": spec, "out_dir": str(out), "alpha_deg": alphas,
                             "reference": asb_spec.flow5_polar(doc, ctx, alphas)}),
        "cruise_trim": runner.run({"job": "cruise_trim", "spec": spec}),
        "static_check": runner.run({"job": "static_check", "spec": spec}),
    }
    results["polar"]["reference"] = asb_spec.flow5_polar(doc, ctx, alphas)
    ref = planform_reference(adh_doc.find(doc, st["wings"][0])["muas"]["planform"])
    g = results["geometry"]["geometry"]
    for key, name in (("s_m2", "area_m2"), ("b_m", "span_m"), ("mac_m", "mac_m")):
        print(f"AeroSandbox: {key} {g[key]:.5f} (planform {ref[name]:.5f})")
    hashes = {design.name: _sha(design), state.name: _sha(state)}
    results_file = out / "results.json"
    results_file.write_text(json.dumps({k: {a: b for a, b in v.items() if a != "ok"} for k, v in results.items()},
                                       indent=1), encoding="utf-8")
    report = out / "report.md"
    report.write_text(asb_spec.report(spec, results, hashes, asb_spec.placeholders(spec)), encoding="utf-8")
    return [report, results_file] + [Path(f) for r in results.values() for f in r.get("files", [])]


def setup(ctx: Context, proptimiser: Optional[str] = None) -> Dict[str, str]:
    """Make the AeroSandbox Python for this machine (see runner.setup)."""
    return runner.setup(proptimiser, ctx.settings().get("proptimiser_git"))


def describe() -> str:
    return runner.describe()
