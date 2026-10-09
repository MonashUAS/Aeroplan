"""AeroSandbox spoke: the initial sizing -> ADH performance record of the air vehicle.

Input (git ignores it): AeroSandbox/work/<aircraft>/athena_outputs.txt, the printout of the Athena sizing scripts
(AeroSandbox). One "Name: value" line for each output. The file gives no units.

What ingest writes: one ADH `Discipline` "sizing" in `performance` of node 1.2 AirVehicle. Its tool record
(`ModelDescription`) holds every output in `data_exchange.outputs` as {name, value, units, units_basis}.

Units: the printout has none. `UNITS` below gives each output a unit and says why:
  - "consistency": a relation between the outputs confirms the unit (for example b^2 / S = AR, or the mass sum).
  - "magnitude":   the value fits only one plausible unit for this aircraft. Not proven.
  - "unknown":     no unit can be given. The value is kept with units "unknown".
The sizing stage comes before flow5. Its geometry values do not set the flow5 geometry. The datum report lists the
differences.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from aeroplan import adh_doc
from aeroplan.spokes import Context, set_sources

NAME = "AeroSandbox"
FILE = "athena_outputs.txt"

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


def ingest(doc: Dict[str, Any], ctx: Context):
    path = ctx.work / FILE
    if not path.is_file():
        return None
    values = parse(path.read_text(encoding="utf-8"))
    unknown = sorted(set(values) - set(UNITS))
    if unknown:
        raise ValueError(f"{FILE}: outputs with no unit rule in AeroSandbox/spoke.py UNITS: {unknown}")
    checks = consistency(values)
    outputs = [{"name": k, "value": v, "units": UNITS[k][0], "units_basis": UNITS[k][1]} for k, v in values.items()]
    air = adh_doc.node(doc, "1.2", create=True)
    adh_doc.muas(air, f"{ctx.aircraft}_airvehicle")
    sizing = {"name": "sizing", "description": "Initial sizing of the aircraft (the first design stage). "
                                               "Unit checks: " + "; ".join(checks),
              "tools": [{"model_name": "Athena initial sizing", "generation_tool": "AeroSandbox (Athena sizing scripts)",
                         "description": "Printout of the sizing scripts. The printout gives no units: see units_basis "
                                        "of each output (AeroPlan AeroSandbox/spoke.py).",
                         "data_exchange": {"model_identifier": "athena", "inputs": [], "outputs": outputs}}]}
    perf = [d for d in air.get("performance") or [] if d.get("name") != "sizing"]
    air["performance"] = [sizing] + perf
    set_sources(air, NAME, [ctx.source_ref(path, "initial sizing outputs (Athena)")])
    return [f"sizing: {len(outputs)} outputs, {sum(u[1] == 'unknown' for u in UNITS.values())} without a known unit"]
