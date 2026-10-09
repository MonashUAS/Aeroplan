"""`aeroplan check <aircraft>`: every check of the source tree of one aircraft.

  1. ADH: the tree against upstream ADH, the `muas` keys against the MUAS extension (adh_doc.validate_document).
  2. Datasets: each hash against its asset ID (source_tree.read does it), each `daveml-adh` dataset against the ADH
     DAVEfunc model and, written as XML, against the DAVE-ML 2.0 DTD. When the dataset came from a DAVE-ML file
     that is on this machine (the DAVEML spoke), the round trip XML -> ADH -> XML must keep every element and value.
     Each checkData static shot must give its outputs within `tol` (aeroplan.daveml_eval).
  3. Datum: the geometry sources in one design frame, asset references, stale derived assets (aeroplan.datum).
  4. Consumers: each profile in aircraft.yaml `consumers` can be packed (aeroplan.consumers).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from . import adh_doc, assets, consumers


@dataclass
class CheckReport:
    lines: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)

    def ok(self, text: str) -> None:
        self.lines.append(f"pass  {text}")

    def fail(self, text: str) -> None:
        self.lines.append(f"FAIL  {text}")
        self.failures.append(text)

    def info(self, text: str) -> None:
        self.lines.append(f"      {text}")

    @property
    def passed(self) -> bool:
        return not self.failures

    def text(self) -> str:
        return "\n".join(self.lines)


def daveml_checks(rep: CheckReport, acft, root: Path) -> None:
    from . import daveml_adh, daveml_eval
    from .dml_validate import validate_dml

    for e in assets.register(acft.doc, create=False):
        if e["kind"] != "dataset" or e["dataset"]["form"] != "daveml-adh":
            continue
        name, d = e["name"], acft.datasets[e["id"]]
        try:
            from aircraft_data_hierarchy.behavior import DAVEfunc

            DAVEfunc.model_validate(d)
            xml = daveml_adh.to_xml(d)
        except Exception as err:          # noqa: BLE001  (any fault of the model is a check failure)
            rep.fail(f"{name}: not a valid ADH DAVEfunc: {err}")
            continue
        errors = validate_dml(xml)
        if errors:
            rep.fail(f"{name}: the XML fails the DAVE-ML 2.0 DTD: {errors[:3]}")
        else:
            rep.ok(f"{name}: ADH DAVEfunc, DAVE-ML 2.0 DTD")
        for src in e.get("derived_from") or []:
            try:
                se = assets.entry(acft.doc, src)
            except assets.AssetError:
                continue
            if se["kind"] != "file" or e["tool"] != "DAVEML":
                continue
            local = assets.local_path(se, root)
            if local is None:
                rep.info(f"{name}: source {se['name']} is not on this machine: no round-trip check")
                continue
            diff = daveml_adh.compare(local.read_bytes(), xml)
            if diff:
                rep.fail(f"{name}: the round trip from {se['name']} loses data: {diff[:3]}")
            else:
                rep.ok(f"{name}: lossless round trip of {se['name']} (every element, attribute and value)")
        if d.get("check_data"):
            try:
                shots = daveml_eval.run_check_data(d)
            except daveml_eval.EvalError as err:
                rep.fail(f"{name}: checkData cannot run: {err}")
                continue
            bad = [s for s in shots if not s.passed]
            if bad:
                for s in bad[:5]:
                    rep.fail(f"{name}: checkData {s.name}: {'; '.join(s.faults[:3])}")
            else:
                n = sum(len(s.outputs) for s in shots)
                rep.ok(f"{name}: checkData, {len(shots)} static shots, {n} outputs within tol")


def run(acft, root: Path) -> CheckReport:
    from .datum import datum_checks

    rep = CheckReport()
    try:
        adh_doc.validate_document(acft.doc)
        rep.ok("ADH tree: valid against upstream ADH and the MUAS extension")
    except ValueError as err:
        rep.fail(f"ADH tree: {err}")
        return rep
    rep.ok(f"datasets: {len(acft.datasets)} match their asset IDs (sha256 of the canonical JSON)")
    daveml_checks(rep, acft, root)
    d = datum_checks(acft.doc, root)
    rep.lines += ["", "Datum checks:", d.text(), ""]
    if not d.ok:
        rep.failures.append("datum checks")
    for profile in acft.info.get("consumers") or []:
        probs = consumers.profile_problems(acft, profile)
        if probs:
            rep.fail(f"profile {profile}: " + "; ".join(probs))
        else:
            rep.ok(f"profile {profile}: the aircraft has every item it needs")
    return rep
