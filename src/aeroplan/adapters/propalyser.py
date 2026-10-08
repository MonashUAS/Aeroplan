"""Propalyser adapter: one contract-B `.h5` in, a Ct/Cp dataset out (docs/source/design/exchange.md, section B).

Reads `propulsion-system` schema_version 2 only. Any other schema or version is refused: there is no legacy reader.
Reads with h5py only. No Propalyser code is imported (tool independence).

Paths read: root attrs, `/generator`, `/prop_ctcp` (J, CT, CP, CT_sigma, CP_sigma, each with a `units` attr),
`/propeller`, `/uncertainty/prop_ctcp`, `/results/*`, `/warnings`, `/daveml/propulsion.dml`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import List

import h5py
import numpy as np
import pandas as pd

from ..config import canonical_json
from ..muas.propulsion import PropCtCpManifest
from ..muas.units import parse_units
from .base import Adapter

SCHEMA, VERSION = "propulsion-system", 2
_COLUMNS = {"J": "J", "CT": "Ct", "CP": "Cp", "CT_sigma": "Ct_sigma", "CP_sigma": "Cp_sigma"}
_UNC_KEYS = ("status", "scope", "basis", "method", "distribution", "effect", "num_sigmas", "coverage")


def _text(v) -> str:
    return v.decode("utf-8") if isinstance(v, bytes) else str(v)


def _attrs(group) -> dict:
    out = {}
    for k, v in group.attrs.items():
        if isinstance(v, (bytes, str, np.str_)):
            out[k] = _text(v)
        elif hasattr(v, "item") and np.ndim(v) == 0:
            out[k] = v.item()
        else:
            out[k] = v
    return out


def _check_units(f, name: str) -> None:
    """Every `units` attribute in the file must be a pint spelling (exchange.md, unit spelling rule)."""
    bad = []

    def visit(path, obj):
        if "units" in obj.attrs:
            try:
                parse_units(_text(obj.attrs["units"]))
            except ValueError:
                bad.append(f"/{path} ({_text(obj.attrs['units'])})")

    f.visititems(visit)
    if bad:
        raise ValueError(f"{name}: units not in pint spelling: {', '.join(bad)}")


class PropalyserAdapter(Adapter):
    name = "propalyser"
    produces = ("prop_ct_cp",)

    def __init__(self, config_id: str):
        self.config_id = config_id

    def ingest(self, source: Path, out_dir: Path) -> List[Path]:
        src = Path(source)
        raw = src.read_bytes()
        with h5py.File(src, "r") as f:
            root = _attrs(f)
            if root.get("schema") != SCHEMA or int(root.get("schema_version", -1)) != VERSION:
                raise ValueError(f"{src.name}: need schema {SCHEMA!r} version {VERSION}, "
                                 f"found {root.get('schema')!r} version {root.get('schema_version')}")
            gen = _attrs(f["generator"])
            if bool(gen["dirty"]):
                raise ValueError(f"{src.name}: written from a dirty tree. The contract forbids it")
            table = f["prop_ctcp"]
            unc = {k: v for k, v in _attrs(f["uncertainty/prop_ctcp"]).items() if k in _UNC_KEYS}
            quantitative = unc.get("status") == "quantitative"
            # sigma columns exist only when the uncertainty is quantitative (contract: no invented value)
            cols = {k: v for k, v in _COLUMNS.items() if quantitative or not k.endswith("_sigma")}
            missing = [c for c in cols if c not in table]
            if missing:
                raise ValueError(f"{src.name}: /prop_ctcp lacks {missing}")
            for c in cols:
                if "units" not in table[c].attrs:
                    raise ValueError(f"{src.name}: /prop_ctcp/{c} has no units attribute")
            _check_units(f, src.name)
            df = pd.DataFrame({new: table[old][()] for old, new in cols.items()})
            tattrs = _attrs(table)
            valid_j = tuple(float(x) for x in np.asarray(table.attrs["valid_J"]))
            prop = _attrs(f["propeller"])
            gates = []
            if "gates" in f and "status" in f["gates"]:
                g = f["gates"]
                gates = [(_text(i), _text(s)) for i, s in zip(g["id"][()], g["status"][()])]
            derived = {}
            for n in (f["results"] if "results" in f else []):
                g = _attrs(f["results"][n])
                derived[n] = {k: g.get(k) for k in ("median", "lower", "upper", "coverage", "units", "method")}
            warnings = [_text(x) for x in f["warnings"][()]] if "warnings" in f else []
            dml = bytes(f["daveml/propulsion.dml"][()]) if "daveml/propulsion.dml" in f else None

        if not np.isfinite(df.to_numpy()).all():
            raise ValueError(f"{src.name}: Ct/Cp table has non-finite values")
        if quantitative:
            unc["per_point_column"] = "Ct_sigma"
        notes = [
            f"Source basis: {root.get('basis')}. Source says placeholder = {bool(root.get('placeholder'))}.",
            f"Selected Propalyser source: {tattrs.get('selected_source', 'not stated')}.",
            "Per-point sigma columns: Ct_sigma and Cp_sigma (absolute 1-sigma, contract B)." if quantitative
            else "No per-point sigma: the source uncertainty status is not quantitative.",
            *[f"Propalyser gate {i}: {s.upper()}" for i, s in gates if s != "pass"],
            f"Propeller: {prop.get('model', 'not stated')}, design_ref {prop.get('design_ref', 'none')}.",
            f"Source file data_sha256 (its own hash): {root.get('data_sha256')}.",
            *[f"Propalyser warning: {w}" for w in warnings],
        ]
        complete = {k: v for k, v in derived.items()
                    if None not in (v["median"], v["lower"], v["upper"], v["coverage"])}
        for v in complete.values():
            v["units"] = v["units"] or "nd"
            if v["method"] is None:
                v.pop("method")
        manifest = PropCtCpManifest(
            dataset_id=f"prop.ctcp.propalyser.{root['system_id']}", config_id=self.config_id,
            propeller_id=str(prop.get("model", root["system_id"])),
            fidelity="L3" if root.get("basis") == "stand" else "L0",
            source_tool="propalyser", diameter={"value": float(prop["diameter_m"]), "units": "m"},
            valid_domain="static_only" if valid_j[1] <= 0.0 else "forward_flight", valid_j=valid_j,
            derived=complete, placeholder=bool(root.get("placeholder")), notes=notes,
            limits=[f"Table covers J {valid_j[0]:g} to {valid_j[1]:g} only."],
            uncertainty=unc, columns=list(cols.values()),
            processing={"binning": f"source {tattrs.get('selected_source', 'not stated')}",
                        "n_raw": len(df), "n_points": len(df)},
            provenance={"tool": "propalyser", "tool_version": f"commit {gen['commit']}", "author": root["author"],
                        "created": _text(root["created_utc"]).rstrip("Z"),
                        "input_sha256": hashlib.sha256(raw).hexdigest(), "config_id": self.config_id,
                        "method": f"propulsion-system v{VERSION}"},
        )
        ds = Path(out_dir) / manifest.dataset_id
        ds.mkdir(parents=True, exist_ok=True)
        df.to_parquet(ds / "points.parquet", index=False)
        (ds / "manifest.json").write_text(canonical_json(json.loads(manifest.model_dump_json())), encoding="utf-8")
        written = [ds / "manifest.json", ds / "points.parquet"]
        if dml is not None:
            (ds / "source_propulsion.dml").write_bytes(dml)
            written.append(ds / "source_propulsion.dml")
        return written
