"""DAVEML spoke: published DAVE-ML 2.0 models (for example the NASA F-16 check-case model) -> datasets of the ADH items.

Input (git ignores it): DAVEML/work/<aircraft>/<file>.dml. When a file is not there, the spoke fetches it from its
`url` (and `member`, a path in the ZIP archive at the URL) and checks its sha256.
Settings (committed): DAVEML/settings/<aircraft>.yaml
    source        url, the reference of the publication (text)
    models        a list of {file, member, sha256, role, node, instance, name}
                  role       the dataset role: aero, propulsion, mass or control
                  node       the WBS number of the ADH node that gets the dataset
                  instance   muas.instance of that node

What ingest writes, for each model:
  - the DAVE-ML file: an asset of the register (linked: repo path and URL), named by `muas.sources` of the node
  - the model: a dataset `<role>.<name>` (form daveml-adh, fidelity REF, units as the source). Its metadata takes
    the tool, version and author from the DAVE-ML file header (ADH ModelDescription), and the file references as
    ADH Reference items.
The file must convert to the ADH form and back with no loss (aeroplan check repeats this test).

A published model keeps its own units (each variable names its units, for example ft and lbf): the checkData of
the file is in those units, so a conversion to SI would break the check cases.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from aeroplan import adh_doc, assets, daveml_adh
from aeroplan.spokes import Context, set_sources

NAME = "DAVEML"
ROLES = ("aero", "propulsion", "mass", "control")


def _file(ctx: Context, m: Dict[str, Any], url: str) -> Path:
    """The local DAVE-ML file: the work folder copy, else a fetch from the URL. The sha256 must match."""
    path = ctx.work / m["file"]
    want = m["sha256"]
    if path.is_file():
        got = assets.sha256_file(path)
        if got != want:
            raise ValueError(f"{path.name}: sha256 {got} is not the {want} of DAVEML/settings/{ctx.aircraft}.yaml")
        return path
    e = {"id": assets.asset_id(want), "name": m["file"], "locations": [{"url": url, "member": m["member"]}]}
    data = assets.fetch(e, ctx.root).read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _meta(d: Dict[str, Any], m: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    h = d.get("file_header") or {}
    authors = ", ".join(f"{a.get('name')} ({a.get('org')})" if a.get("org") else a.get("name", "")
                        for a in h.get("author") or [])
    md = {"generation_tool": "DAVE-ML 2.0 (ANSI/AIAA S-119)", "model_name": h.get("name") or m["name"]}
    if authors:
        md["author"] = authors
    if (h.get("file_version") or {}).get("value"):
        md["version"] = h["file_version"]["value"]
    if (h.get("description") or {}).get("value"):
        md["description"] = " ".join(h["description"]["value"].split())
    return {"form": "daveml-adh", "fidelity": "REF", "units_system": "as-source", "model_description": md,
            "notes": [f"Published reference model: {source['reference']}",
                      "No uncertainty estimate exists in the source (sigma not given).",
                      "The moments are about the reference point that the model itself defines (see its variables)."]}


def ingest(doc: Dict[str, Any], ctx: Context):
    st = ctx.settings()
    if not st or not st.get("models"):
        return None
    url = st["source"]["url"]
    changes: List[str] = []
    for m in st["models"]:
        if m["role"] not in ROLES:
            raise ValueError(f"{m['file']}: role {m['role']!r} is not one of {ROLES}")
        path = _file(ctx, m, url)
        raw = path.read_bytes()
        d = daveml_adh.from_xml(raw)
        diff = daveml_adh.compare(raw, daveml_adh.to_xml(d))
        if diff:
            raise ValueError(f"{path.name}: the ADH form loses data: {diff[:3]}")
        n = adh_doc.node(doc, m["node"], create=True)
        adh_doc.muas(n, m["instance"])
        if n["muas"]["instance"] != m["instance"]:
            raise ValueError(f"node {m['node']} carries {n['muas']['instance']!r}, the settings say {m['instance']!r}")
        ref = ctx.source_ref(path, f"DAVE-ML model {m['name']} ({m['role']})", url=url)
        e = assets.entry(ctx.acft.doc, ref["asset"])
        e["locations"] = [loc if "url" not in loc else {"url": url, "member": m["member"]} for loc in e["locations"]]
        keep = [s for s in n["muas"].get("sources") or [] if s["tool"] == NAME and s["asset"] != ref["asset"]
                and not s["role"].startswith(f"DAVE-ML model {m['name']} ")]
        set_sources(n, NAME, keep + [ref])
        refs = (d.get("file_header") or {}).get("reference") or []
        ctx.add_dataset(n, f"{m['role']}.{m['name']}", d, role=f"{m['role']} model (DAVE-ML in ADH form)",
                        dataset_role=m["role"], derived_from=[ref["asset"]], meta=_meta(d, m, st["source"]),
                        reference=refs or None)
        shots = len((d.get("check_data") or {}).get("static_shot") or [])
        changes.append(f"{m['instance']}: {m['role']} model {m['name']} ({len(d.get('variable_def') or [])} "
                       f"variables, {shots} check cases)")
    return changes
