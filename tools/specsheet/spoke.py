"""SpecSheet spoke: the Master Specification Sheet (weight log and CG sheet) -> the ADH mass model.

Input: the workbook named in tools/specsheet/settings/<aircraft>.yaml (an xlsx in the repository; a download of the Google
Sheet later). The spoke reads the cached cell values with openpyxl (data_only), so the workbook must have been saved
by a spreadsheet program.

Weight log (`weights_sheet`): a group in column A is one subassembly. The row with "Subassembly weight override" in
column F is the weighed mass of the whole subassembly (the rule of the sheet). The other rows with a mass are the
itemised parts. The sheet "unitemised" lines are not used: the spoke takes the weighed total less the mapped parts.
Position sheet (`positions_sheet`): column F is the distance from the wing root leading edge in mm, positive
forward. x_design = -F / 1000. The sheet has no y or z, so y = 0 and z = 0 (stand-ins, see the notes written).

CSV mode (settings `format: csv`, or a workbook that ends in `.csv`): the input is the weight log alone, exported from
the sheet as CSV (same columns A to F as the xlsx weight log; the header row is the row with "Component" in column B).
The row of column A that ends the log is named by `total_row` (default "Total"). There is no position sheet. Positions
come from placement rules in the settings (`placement`: weight log row -> rule): `hub` puts one point mass of the
per-item weight at each lift rotor hub (the item count must equal the number of hubs), `half_arm` puts it half way
along the arm (half the hub vector), and every other mass of a subassembly (its weighed total less the placed rows)
is one point mass at `origin_m`. The hubs are read from `muas.propeller.hub` of the ADH items in `hubs` (the AeroSandbox
seed writes them, so the spoke runs after it). `mrp: from_mass` sets the MRP and the nominal CG of the reference data to the
rolled-up CG. `sanity` names an estimate sheet whose MTOW row is only compared with the weight log: it is never truth.

What ingest writes, for each subassembly: `muas.mass_properties` (mass, CG) and `muas.point_masses` on its ADH item
(the landing gear is a subcomponent of 1.2.2: no WBS number of its own). On 1.2 AirVehicle: the flat list of all point
masses, the roll-up (mass, CG, inertia) and the source pointer. `reference` is not changed. The MRP stays the CoG of
the flow5 T7 analysis, because the aero model is about that point. The datum check warns until a new flow5 sweep
(`aeroplan sweep flow5`) of the new mass model.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aeroplan import adh_doc, mass_model
from aeroplan.spokes import Context, set_sources

NAME = "SpecSheet"
OVERRIDE = "subassembly weight override"
SKIP_PREFIX = ("component sum", "unitemised", "override")
TOTAL_TOL_KG = 1e-6


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def classify(text: Optional[str]) -> Dict[str, Any]:
    """Source text of column F -> mass source (weighed, cad, estimate) and whether the value is a stand-in."""
    t = (text or "").strip().lower()
    if t.startswith("weighed"):
        return {"source": "weighed", "placeholder": False}
    if t.startswith("determined from cad"):
        return {"source": "cad", "placeholder": False}
    if t.startswith("calculated from"):
        return {"source": "estimate", "placeholder": False}
    return {"source": "estimate", "placeholder": True}       # "I made it up", "Not Weighed", no text


class _Cell:
    def __init__(self, value):
        self.value = value


class CsvSheet:
    """A CSV file as a worksheet for read_weights: `cell(r, c).value` (1-based), `max_row`, `title`. A cell that reads as a
    number is a float, an empty cell is None."""

    def __init__(self, path: Path):
        with open(path, encoding="utf-8-sig", newline="") as fh:
            self.rows = list(csv.reader(fh))
        self.title = Path(path).name
        self.max_row = len(self.rows)

    def cell(self, r: int, c: int) -> _Cell:
        row = self.rows[r - 1] if 0 < r <= len(self.rows) else []
        text = row[c - 1].strip() if 0 < c <= len(row) else ""
        if not text:
            return _Cell(None)
        try:
            return _Cell(float(text))
        except ValueError:
            return _Cell(text)

    def first_data_row(self) -> int:
        """The row after the header row (the row with "Component" in column B)."""
        for r in range(1, self.max_row + 1):
            if self.cell(r, 2).value == "Component":
                return r + 1
        raise ValueError(f"{self.title}: no header row with 'Component' in column B")


def read_weights(ws, first_row: int = 9, total_label: str = "total") -> Dict[str, Any]:
    """The weight log: {"groups": {name: {total_g, total_row, parts, unweighed}}, "total_g"}. The log ends at the row
    whose column A is `total_label` (case does not matter)."""
    groups: Dict[str, Dict[str, Any]] = {}
    cur: Optional[str] = None
    sheet_total = None
    for r in range(first_row, ws.max_row + 1):
        a, b, f = ws.cell(r, 1).value, ws.cell(r, 2).value, ws.cell(r, 6).value
        if isinstance(a, str) and a.strip():
            if a.strip().lower() == total_label.lower():
                sheet_total = _num(ws.cell(r, 3).value)
                break
            cur = a.strip()
            groups[cur] = {"total_g": None, "total_row": None, "parts": [], "unweighed": []}
        if cur is None or not isinstance(b, str) or not b.strip():
            continue
        g, e = groups[cur], _num(ws.cell(r, 5).value)
        if isinstance(f, str) and f.strip().lower() == OVERRIDE:
            if g["total_g"] is not None:
                raise ValueError(f"{ws.title}: group {cur!r} has two rows with {OVERRIDE!r}")
            g["total_g"], g["total_row"] = e or 0.0, r
        elif b.strip().lower().startswith(SKIP_PREFIX):
            continue
        elif e:
            g["parts"].append({"row": r, "name": b.strip(), "mass_g": e, "text": f, "each_g": _num(ws.cell(r, 3).value),
                               "qty": _num(ws.cell(r, 4).value), **classify(f)})
        else:
            g["unweighed"].append(b.strip())
    if sheet_total is None:
        raise ValueError(f"{ws.title}: no '{total_label}' row in column A")
    for name, g in groups.items():
        if g["total_g"] is None:
            raise ValueError(f"{ws.title}: group {name!r} has no row with {OVERRIDE!r}")
    return {"groups": groups, "total_g": sheet_total}


def read_positions(ws) -> Dict[str, Dict[str, Dict[str, float]]]:
    """The position sheet: {group: {row name: {x_mm, mass_g, row}}}. Column A names the group, column B the row."""
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    cur = None
    for r in range(3, ws.max_row + 1):
        a, b = ws.cell(r, 1).value, ws.cell(r, 2).value
        if isinstance(a, str) and a.strip():
            cur = a.strip()
        x, m = _num(ws.cell(r, 6).value), _num(ws.cell(r, 5).value)
        if cur and isinstance(b, str) and b.strip() and x is not None and m is not None:
            out.setdefault(cur, {})[b.strip()] = {"x_mm": x, "mass_g": m, "row": r}
    return out


def is_csv(path: Path, st: Dict[str, Any]) -> bool:
    return st.get("format") == "csv" or Path(path).suffix.lower() == ".csv"


def read_workbook(path: Path, st: Dict[str, Any]) -> Dict[str, Any]:
    if is_csv(path, st):
        ws = CsvSheet(path)
        w = read_weights(ws, ws.first_data_row(), st.get("total_row", "total"))
        total = sum(g["total_g"] for g in w["groups"].values())
        if abs(total - w["total_g"]) / 1000.0 > TOTAL_TOL_KG:
            raise ValueError(f"{path.name}: the subassembly totals add to {total:.4f} g, the sheet {st.get('total_row', 'Total')} "
                             f"row says {w['total_g']:.4f} g")
        w["positions"] = {}
        return w
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    for key in ("weights_sheet", "positions_sheet"):
        if st[key] not in wb.sheetnames:
            raise ValueError(f"{path.name}: no sheet {st[key]!r} (sheets: {wb.sheetnames})")
    w = read_weights(wb[st["weights_sheet"]])
    w["positions"] = read_positions(wb[st["positions_sheet"]])
    total = sum(g["total_g"] for g in w["groups"].values())
    if abs(total - w["total_g"]) / 1000.0 > TOTAL_TOL_KG:
        raise ValueError(f"{path.name}: the subassembly totals add to {total:.4f} g, the sheet Total row says "
                         f"{w['total_g']:.4f} g")
    return w


def _x(row: Dict[str, float], datum: float = 0.0) -> float:
    """Design x (m, aft) of a sheet row. The sheet measures from the wing root leading edge, positive forward, so
    x = datum - F/1000 with datum = the design x of that leading edge (settings `datum_x_m`)."""
    return datum - row["x_mm"] / 1000.0


def _weighted_x(rows: List[Dict[str, float]], datum: float = 0.0) -> float:
    return sum(_x(r, datum) * r["mass_g"] for r in rows) / sum(r["mass_g"] for r in rows)


DATUM_TOL_M = 1e-3


def _root_le_x(doc: Dict[str, Any], st: Dict[str, Any]) -> Optional[float]:
    """Design x of the root leading edge of the wing that the sheet measures from (settings `datum_wing`)."""
    try:
        pf = adh_doc.find(doc, st.get("datum_wing", "wing_main"))["muas"]["planform"]
    except (KeyError, ValueError):
        return None
    s0 = pf["sections"][0]
    return float(pf["position"]["xyz"][0] + s0["x_offset"])


def _tag(*parts: str) -> str:
    return "-".join(p.upper().replace(" ", "_") for p in parts)


def build_point_masses(data: Dict[str, Any], st: Dict[str, Any],
                       planform_of: Callable[[str], Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry for each subassembly: {group, cfg, point_masses[{tag, mass_kg, xyz, source, placeholder}]}."""
    ws_name, pos_name = st["weights_sheet"], st["positions_sheet"]
    datum = float(st["datum_x_m"])
    stands_in: Dict[str, float] = {}
    out = []
    for gname, cfg in st["subassemblies"].items():
        if gname not in data["groups"]:
            raise ValueError(f"the weight log has no group {gname!r}")
        g = data["groups"][gname]
        if not g["total_g"]:
            continue
        rows = data["positions"].get(cfg.get("cg_group", ""), {})
        for ex in cfg.get("exclude_rows", []):
            rows = {k: v for k, v in rows.items() if k != ex}
        mapped = cfg.get("components", {})
        for comp, row in mapped.items():
            if row not in rows:
                raise ValueError(f"settings {gname}: position row {row!r} for {comp!r} is not in the position sheet")
        pms: List[Dict[str, Any]] = []
        used = 0.0
        for row in dict.fromkeys(mapped.values()):                       # mapped rows in settings order
            parts = [p for p in g["parts"] if mapped.get(p["name"]) == row]
            if not parts:
                continue
            m_g = sum(p["mass_g"] for p in parts)
            used += m_g
            texts = "; ".join(f"row {p['row']} {p['name']} ({p['text'] or 'no source stated'})" for p in parts)
            pms.append({"tag": _tag(gname, row), "mass_kg": m_g / 1000.0, "xyz": [_x(rows[row], datum), 0.0, 0.0],
                        "placeholder": any(p["placeholder"] for p in parts),
                        "source": f"{ws_name}: {texts}. x: {pos_name} {cfg['cg_group']}/{row}. y = 0, z = 0: "
                                  "not in the sheet (stand-in)"})
        rest_g = g["total_g"] - used
        if rest_g < -1e-9:
            raise ValueError(f"{gname}: the mapped parts ({used:.3f} g) weigh more than the subassembly ({g['total_g']:.3f} g)")
        if rest_g > 1e-9:
            free = {k: v for k, v in rows.items() if k not in set(mapped.values())} or rows
            if free:
                x_rest, x_src = _weighted_x(list(free.values()), datum), f"{pos_name} {cfg['cg_group']}: " + ", ".join(free)
            elif cfg.get("position_from") in stands_in:
                x_rest = stands_in[cfg["position_from"]]
                x_src = f"stand-in: the x of {cfg['position_from']} (the position sheet has no {gname} rows)"
            else:
                raise ValueError(f"{gname}: no position rows (cg_group) and no position_from")
            stands_in[gname] = x_rest
            others = [p["name"] for p in g["parts"] if p["name"] not in mapped]
            what = (f"{ws_name}: {gname} weighed total (row {g['total_row']}) less the mapped parts. "
                    f"Itemised in the rest: {', '.join(others) or 'none'}. Not weighed: {', '.join(g['unweighed']) or 'none'}. "
                    f"x: mass-weighted mean of {x_src}")
            placeholder = any(p["placeholder"] for p in g["parts"] if p["name"] not in mapped) or not rows
            if cfg.get("distribute"):
                strips = mass_model.distribute_on_planform(rest_g / 1000.0, planform_of(cfg["distribute"]),
                                                           int(st.get("strips_per_side", 6)), x_rest)
                for i, s in enumerate(strips, 1):
                    pms.append({"tag": _tag(gname, f"S{i}"), "mass_kg": s["mass_kg"], "xyz": s["xyz"],
                                "placeholder": placeholder,
                                "source": f"{what}. Spread over the planform of {cfg['distribute']} in strips of "
                                          "equal area density, shifted in x to the mean above"})
            else:
                pms.append({"tag": _tag(gname, "REST"), "mass_kg": rest_g / 1000.0, "xyz": [x_rest, 0.0, 0.0],
                            "placeholder": placeholder, "source": f"{what}. y = 0, z = 0: not in the sheet (stand-in)"})
        else:
            stands_in[gname] = _weighted_x(list(rows.values()), datum) if rows else 0.0
        out.append({"group": gname, "cfg": cfg, "point_masses": pms})
    return out


def _slug(*parts: str) -> str:
    return "-".join(re.sub(r"[^A-Z0-9]+", "_", p.upper()).strip("_") for p in parts)


def rotor_hubs(doc: Dict[str, Any], instances: List[str]) -> List[Dict[str, Any]]:
    """[{motor, instance, xyz}] of the lift rotors in `instances` (muas.propeller.hub), in the order of the list."""
    out = []
    for inst in instances:
        try:
            pr = adh_doc.find(doc, inst)["muas"]["propeller"]
        except (KeyError, TypeError):
            raise ValueError(f"settings hubs: {inst!r} has no muas.propeller (the AeroSandbox seed writes it: build with "
                             "the AeroSandbox spoke before SpecSheet)") from None
        out.append({"motor": pr.get("motor") or len(out) + 1, "instance": inst, "xyz": [float(c) for c in pr["hub"]["xyz"]]})
    return out


def build_point_masses_csv(data: Dict[str, Any], st: Dict[str, Any], hubs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry for each subassembly: {group, cfg, point_masses}. A row with a placement rule (`hub`, `half_arm`) gets one
    point mass for each hub from its per-item weight. The rest of the weighed subassembly total is one point mass at
    `origin_m`."""
    place, origin = st["placement"], [float(c) for c in st.get("origin_m", [0.0, 0.0, 0.0])]
    rules_src = st.get("placement_source", "the placement rules of the settings")
    sheet = Path(st["workbook"]).name
    known = {p["name"] for g in data["groups"].values() for p in g["parts"]}
    for row, rule in place.items():
        if rule not in ("hub", "half_arm"):
            raise ValueError(f"settings placement: {row!r} has the rule {rule!r} (use hub or half_arm)")
        if row not in known:
            raise ValueError(f"settings placement: the weight log has no row {row!r}")
    out = []
    for gname, cfg in st["subassemblies"].items():
        if gname not in data["groups"]:
            raise ValueError(f"the weight log has no group {gname!r}")
        g = data["groups"][gname]
        if not g["total_g"]:
            continue
        pms: List[Dict[str, Any]] = []
        used = 0.0
        for part in g["parts"]:
            rule = place.get(part["name"])
            if rule is None:
                continue
            if part["qty"] != len(hubs) or part["each_g"] is None:
                raise ValueError(f"{gname}/{part['name']}: quantity {part['qty']} is not the number of hubs {len(hubs)}")
            if abs(part["each_g"] * part["qty"] - part["mass_g"]) > 1e-9:
                raise ValueError(f"{gname}/{part['name']}: {part['each_g']} g x {part['qty']} is not {part['mass_g']} g")
            for h in hubs:
                f = 1.0 if rule == "hub" else 0.5
                where = ("at the hub" if rule == "hub" else "half way along the arm (half the hub vector)")
                pms.append({"tag": _slug(part["name"], f"M{h['motor']}"), "mass_kg": part["each_g"] / 1000.0,
                            "xyz": [f * c for c in h["xyz"]], "placeholder": part["placeholder"],
                            "source": f"{sheet} row {part['row']} {part['name']} ({part['text'] or 'no source stated'}), "
                                      f"{part['each_g']:g} g for one arm. Placed {where} of {h['instance']} "
                                      f"(muas.propeller.hub): {rules_src}"})
            used += part["mass_g"]
        rest_g = g["total_g"] - used
        if rest_g < -1e-9:
            raise ValueError(f"{gname}: the placed rows ({used:.3f} g) weigh more than the subassembly ({g['total_g']:.3f} g)")
        if rest_g > 1e-9:
            others = [p["name"] for p in g["parts"] if p["name"] not in place]
            pms.append({"tag": _slug(gname, "REST"), "mass_kg": rest_g / 1000.0, "xyz": list(origin), "placeholder": True,
                        "source": f"{sheet}: {gname} weighed total (row {g['total_row']}) less the placed rows. Itemised in "
                                  f"the rest: {', '.join(others) or 'none'}. Not weighed: {', '.join(g['unweighed']) or 'none'}. "
                                  f"At the origin {origin}: {rules_src} (stand-in: the real positions are not in the sheet)"})
        out.append({"group": gname, "cfg": cfg, "point_masses": pms})
    return out


def _sanity(path: Path, spec: Dict[str, Any], mass_kg: float) -> str:
    """Compare the weight log mass with the MTOW row of an estimate sheet. The estimate is never truth."""
    ws = CsvSheet(path)
    for r in range(1, ws.max_row + 1):
        if ws.cell(r, spec.get("label_col", 1)).value == spec["row"] and isinstance(ws.cell(r, spec["col"]).value, float):
            est = ws.cell(r, spec["col"]).value
            return (f"sanity check only: {path.name} row {spec['row']} says {est:g} kg (an estimate sheet, not truth), "
                    f"the weight log says {mass_kg:.4f} kg, difference {mass_kg - est:+.4f} kg")
    return f"sanity check: {path.name} has no row {spec['row']!r} with a number in column {spec['col']}"


def _pm_adh(p: Dict[str, Any]) -> Dict[str, Any]:
    return {"tag": p["tag"], "mass": {"value": p["mass_kg"], "units": "kg"}, "position": {"xyz": list(p["xyz"])},
            "source": p["source"], "placeholder": bool(p["placeholder"])}


def _item(doc: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    parent = adh_doc.node(doc, cfg["node"], create=True)
    sub = cfg.get("subcomponent")
    if sub is None:
        adh_doc.muas(parent, cfg["instance"])
        return parent
    for s in parent.get("subcomponents") or []:
        if (s.get("muas") or {}).get("instance") == sub["instance"]:
            return s
    comp = {"name": sub["name"], "description": f"{sub['name']} (mass model of the Master Specification Sheet)"}
    adh_doc.muas(comp, sub["instance"])
    return adh_doc.put_subcomponent(parent, comp)


def ingest(doc: Dict[str, Any], ctx: Context):
    st = ctx.settings()
    if not st:
        return None
    path = ctx.root / st["workbook"]
    if not path.is_file():
        return None
    data = read_workbook(path, st)
    if is_csv(path, st):
        return _ingest_csv(doc, ctx, st, path, data)
    subs = build_point_masses(data, st, lambda inst: adh_doc.find(doc, inst)["muas"]["planform"])
    changes, flat = [], []
    le = _root_le_x(doc, st)
    if le is not None and abs(le - float(st["datum_x_m"])) > DATUM_TOL_M:
        changes.append(f"WARNING: the sheet datum (wing root leading edge) is x = {float(st['datum_x_m']):+.4f} m in the "
                       f"settings, but the wing_main root leading edge is at x = {le:+.4f} m in the document. "
                       "Every sheet position is off by the difference until you change datum_x_m or the wing")
    for s in subs:
        pms = s["point_masses"]
        roll = mass_model.rollup(pms)
        item = _item(doc, s["cfg"])
        item["muas"]["point_masses"] = [_pm_adh(p) for p in pms]
        item["muas"]["mass_properties"] = {
            "mass": {"value": roll["mass_kg"], "units": "kg"}, "cg": {"xyz": roll["cg"]}, "source": "estimate",
            "placeholder": True,
            "notes": [f"Mass: the weighed subassembly total of the sheet ({s['group']}). CG: the x of the position "
                      "sheet, y = 0 and z = 0 are stand-ins."]}
        flat += pms
        changes.append(f"{s['group']}: {roll['mass_kg']:.4f} kg, CG x {roll['cg'][0]:+.4f} m, {len(pms)} point masses")
    air = adh_doc.node(doc, "1.2", create=True)
    adh_doc.muas(air, f"{ctx.aircraft}_airvehicle")
    roll = mass_model.rollup(flat)
    air["muas"]["point_masses"] = [_pm_adh(p) for p in flat]
    air["muas"]["mass_properties"] = {
        "mass": {"value": roll["mass_kg"], "units": "kg"}, "cg": {"xyz": roll["cg"]}, "inertia": roll["inertia"],
        "source": "estimate", "placeholder": True,
        "notes": [f"Configuration {st['configuration']}: the weight log of the Master Specification Sheet "
                  f"({st['weights_sheet']}), positions from {st['positions_sheet']}. No payload and no water tanks.",
                  "The mass is the sum of the weighed subassembly totals. The CG x comes from the position sheet. "
                  "y = 0 and z = 0 for every point mass: the sheet has no vertical positions (stand-in).",
                  "The inertia is the parallel-axis sum of the point masses. A part has no inertia of its own in it."]}
    set_sources(air, NAME, [ctx.source_ref(path, "mass model: weight log and CG sheet")])
    changes.append(f"air vehicle: {roll['mass_kg']:.4f} kg, CG {[round(v, 4) for v in roll['cg']]}, "
                   f"{len(flat)} point masses (sheet total {data['total_g'] / 1000.0:.4f} kg)")
    return changes


def _ingest_csv(doc: Dict[str, Any], ctx: Context, st: Dict[str, Any], path: Path, data: Dict[str, Any]):
    """CSV mode: the placement rules of the settings turn the weight log into point masses (see the module text)."""
    hubs = rotor_hubs(doc, st["hubs"])
    subs = build_point_masses_csv(data, st, hubs)
    changes, flat = [], []
    for s in subs:
        pms = s["point_masses"]
        roll = mass_model.rollup(pms)
        item = _item(doc, s["cfg"])
        item["muas"]["point_masses"] = [_pm_adh(p) for p in pms]
        item["muas"]["mass_properties"] = {
            "mass": {"value": roll["mass_kg"], "units": "kg"}, "cg": {"xyz": roll["cg"]}, "source": "estimate",
            "placeholder": True,
            "notes": [f"Mass: the weighed subassembly total of the sheet ({s['group']}). CG: point masses placed by the rules "
                      "of the settings (hub, half arm, origin). The origin mass is a stand-in position."]}
        flat += pms
        changes.append(f"{s['group']}: {roll['mass_kg']:.4f} kg, CG {[round(c, 4) for c in roll['cg']]}, {len(pms)} point masses")
    air = adh_doc.node(doc, "1.2", create=True)
    adh_doc.muas(air, f"{ctx.aircraft}_airvehicle")
    roll = mass_model.rollup(flat)
    air["muas"]["point_masses"] = [_pm_adh(p) for p in flat]
    air["muas"]["mass_properties"] = {
        "mass": {"value": roll["mass_kg"], "units": "kg"}, "cg": {"xyz": roll["cg"]}, "inertia": roll["inertia"],
        "source": "estimate", "placeholder": True,
        "notes": [f"Configuration {st['configuration']}: the weight log of the Master Specification Sheet "
                  f"({Path(st['workbook']).name}), total row {st.get('total_row', 'Total')}.",
                  "Motors, propellers, ESCs and motor mounts are point masses at the four hubs, the boom arms are point "
                  "masses half way along the arm, and all other mass is at the origin (user rules, 2026-10-16).",
                  "The inertia is the parallel-axis sum of the point masses. A part has no inertia of its own in it."]}
    refs = [ctx.source_ref(path, "mass model: weight log")]
    if st.get("sanity"):
        sp = ctx.root / st["sanity"]["file"]
        if sp.is_file():
            refs.append(ctx.source_ref(sp, "estimate sheet: sanity check only, never truth", note="estimates"))
            changes.append(_sanity(sp, st["sanity"], roll["mass_kg"]))
    set_sources(air, NAME, refs)
    changes.append(f"air vehicle: {roll['mass_kg']:.4f} kg, CG {[round(c, 6) for c in roll['cg']]}, {len(flat)} point masses "
                   f"(sheet total {data['total_g'] / 1000.0:.4f} kg)")
    ref = air["muas"].get("reference")
    if st.get("mrp") == "from_mass":
        if ref is None:
            raise ValueError("settings mrp: from_mass needs muas.reference (the AeroSandbox seed writes it)")
        pos = {"frame": "design", "xyz": list(roll["cg"]), "units": "m"}
        ref["nominal_cg"] = pos
        ref["mrp"] = {**ref["mrp"], "point": dict(pos)}
        ref["mrp"].pop("mass_properties_sha256", None)
        changes.append(f"MRP and nominal CG set to the rolled-up CG {[round(c, 6) for c in roll['cg']]} (settings mrp: from_mass)")
    return changes
