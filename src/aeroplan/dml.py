"""DAVE-ML writer for point datasets (brief 6.3, D06, D21).

The output is validated against the vendored DAVE-ML 2.0 DTD (spec/dave-ml/2p0, see dml_validate.py).
The brief's snippet 6.3 was not DTD-checked. Two structural errors were found and fixed here:
provenance sits in fileHeader (not at the root), and all tables come before all functions.

One ungriddedTableDef per output. Per-point sigma exports as a companion `<id>_sigma` table (D21).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import pandas as pd

from .muas.uncertainty import Distribution, Uncertainty, UncertaintyStatus


def _num(v: float) -> str:
    return repr(float(v))


def _uncertainty_el(u: Uncertainty) -> Optional[ET.Element]:
    if u.status is not UncertaintyStatus.QUANTITATIVE:
        return None
    el = ET.Element("uncertainty", effect=u.effect.value)
    if u.distribution is Distribution.NORMAL:
        if u.sigma is None:
            return None
        pdf = ET.SubElement(el, "normalPDF", numSigmas=_num(u.num_sigmas))
        ET.SubElement(pdf, "bounds").text = _num(u.sigma)
    else:
        pdf = ET.SubElement(el, "uniformPDF")
        for b in (u.lower, u.upper):
            ET.SubElement(pdf, "bounds").text = _num(b)
    return el


def points_to_dml(
    *,
    name: str,
    inputs: List[Dict],
    outputs: List[Dict],
    points: pd.DataFrame,
    uncertainty: Optional[Uncertainty] = None,
    author: str,
    created: str,
    ref_id: str,
    description: str = "",
) -> bytes:
    """Return DAVE-ML bytes. `inputs`: id, name, units, range|fixed. `outputs`: id, name, units.

    Held-fixed inputs are not independent variables: their value is checked, then they are skipped.
    """
    root = ET.Element("DAVEfunc")
    hdr = ET.SubElement(root, "fileHeader")
    ET.SubElement(hdr, "author", name=author, org="MUAS")
    ET.SubElement(hdr, "creationDate", date=created[:10])
    if description:
        ET.SubElement(hdr, "description").text = description
    ET.SubElement(hdr, "reference", refID=ref_id, author=author, title=name, date=created[:10])
    prov = ET.SubElement(hdr, "provenance", provID=f"prov_{name}")
    ET.SubElement(prov, "author", name=author, org="MUAS")
    ET.SubElement(prov, "creationDate", date=created[:10])
    ET.SubElement(prov, "documentRef", refID=ref_id)

    free = [i for i in inputs if i.get("range") is not None]
    for i in inputs:
        if i.get("fixed") is not None and not (points[i["id"]] == i["fixed"]).all():
            raise ValueError(f"input {i['id']} is declared fixed but varies in the points")
    for i in free:
        ET.SubElement(root, "variableDef", name=i["name"], varID=i["id"], units=i["units"])
    for o in outputs:
        ET.SubElement(root, "variableDef", name=o["name"], varID=o["id"], units=o["units"])

    # DTD order: all ungriddedTableDef elements, then all function elements, then checkData.
    in_ids = [i["id"] for i in free]
    for o in outputs:
        ut = ET.SubElement(root, "ungriddedTableDef", utID=f"{o['id']}_table", units=o["units"])
        ET.SubElement(ut, "provenanceRef", provID=f"prov_{name}")
        ue = _uncertainty_el(uncertainty) if uncertainty else None
        if ue is not None:
            ut.append(ue)
        for _, row in points.iterrows():
            ET.SubElement(ut, "dataPoint").text = " ".join(_num(row[c]) for c in in_ids + [o["id"]])
        sig_col = f"{o['id']}_sigma"
        if sig_col in points.columns:
            st = ET.SubElement(root, "ungriddedTableDef", utID=f"{o['id']}_sigma_table", units=o["units"])
            for _, row in points.iterrows():
                ET.SubElement(st, "dataPoint").text = " ".join(_num(row[c]) for c in in_ids + [sig_col])
    for o in outputs:
        fn = ET.SubElement(root, "function", name=o["name"])
        for i in free:
            lo, hi = i["range"]
            ET.SubElement(fn, "independentVarRef", varID=i["id"], min=_num(lo), max=_num(hi), extrapolate="neither")
        ET.SubElement(fn, "dependentVarRef", varID=o["id"])
        fd = ET.SubElement(fn, "functionDefn", name=f"{o['name']}_fn")
        ET.SubElement(fd, "ungriddedTableRef", utID=f"{o['id']}_table")

    if len(points):
        first = points.iloc[0]
        cd = ET.SubElement(root, "checkData")
        shot = ET.SubElement(cd, "staticShot", name=f"{name}_pt1")
        ci = ET.SubElement(shot, "checkInputs")
        for i in free:
            s = ET.SubElement(ci, "signal")
            ET.SubElement(s, "signalName").text = i["name"]
            ET.SubElement(s, "signalUnits").text = i["units"]
            ET.SubElement(s, "signalValue").text = _num(first[i["id"]])
        co = ET.SubElement(shot, "checkOutputs")
        for o in outputs:
            s = ET.SubElement(co, "signal")
            ET.SubElement(s, "signalName").text = o["name"]
            ET.SubElement(s, "signalUnits").text = o["units"]
            ET.SubElement(s, "signalValue").text = _num(first[o["id"]])
            ET.SubElement(s, "tol").text = "0.0"

    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
