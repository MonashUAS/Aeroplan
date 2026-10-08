"""Assemble per-node JSON into one ADH tree (brief D14: `aeroplan assemble`)."""
from __future__ import annotations

from typing import Any, Dict, List

from .muas.node import validate_node


def assemble_adh(nodes: List[Dict[str, Any]], *, muas_schema_version: str) -> Dict[str, Any]:
    """Validate every node and return one deterministic document. Duplicate (wbs_no, instance) is an error."""
    seen = set()
    for n in nodes:
        validate_node(n)
        key = (n["wbs_no"], n["muas"]["instance"])
        if key in seen:
            raise ValueError(f"duplicate node {key}")
        seen.add(key)
    ordered = sorted(nodes, key=lambda n: ([int(p) for p in n["wbs_no"].split(".")], n["muas"]["instance"]))
    return {"muas_schema_version": muas_schema_version, "nodes": ordered}
