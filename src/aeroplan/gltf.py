"""glTF 2.0 binary (GLB): the 3D view of the aircraft in a `.muas` package (`preview/aircraft.glb`).

One glTF node and one mesh for each part. The positions are the design frame in metres (x aft, y right, z up), as
float32, one vertex for each triangle corner. The node `extras` hold the part data that Aerolink needs: the ADH
item, the hinge axis (two points, design frame, m), the material, the source and the placeholder flag. The asset
`extras` give the frame.

The design frame is not the glTF frame (y up). A viewer that needs the glTF frame applies the rotation in
`extras.to_gltf` (a 4x4 matrix, row major). The data stays in the design frame, so no rounding of a rotation
changes a hinge or a vertex.

A part whose extras hold `alpha` (0 to 1, for example a rotor disc) gets a glTF material with alphaMode BLEND and that
opacity, so a viewer draws it semi-transparent. The reader ignores materials and keeps `alpha` in the extras.

The writer is deterministic: the same parts give the same bytes.
"""
from __future__ import annotations

import json
import struct
from typing import Any, Dict, List, Tuple

import numpy as np

MAGIC, VERSION = 0x46546C67, 2
JSON_CHUNK, BIN_CHUNK = 0x4E4F534A, 0x004E4942
FLOAT, ARRAY_BUFFER = 5126, 34962
FRAME = "design (x aft, y right, z up, m)"
#: design (x aft, y right, z up) -> glTF (x left, y up, z forward): x_g = -y, y_g = z, z_g = -x
TO_GLTF = [[0, -1, 0, 0], [0, 0, 1, 0], [-1, 0, 0, 0], [0, 0, 0, 1]]


class GltfError(ValueError):
    """The bytes are not a GLB file of this form."""


def _pad(b: bytes, fill: bytes) -> bytes:
    return b + fill * (-len(b) % 4)


def write_glb(parts: List[Tuple[str, np.ndarray, Dict[str, Any]]], *, aircraft: str) -> bytes:
    """GLB bytes of the parts: (name, triangles (n, 3, 3) in m, extras), sorted by name."""
    nodes, meshes, accessors, views, materials = [], [], [], [], []
    blob = bytearray()
    for name, tri, extras in sorted(parts, key=lambda p: p[0]):
        pos = np.ascontiguousarray(np.asarray(tri, dtype=np.float32).reshape(-1, 3))
        if not len(pos):
            raise GltfError(f"part {name} has no triangles")
        data = pos.tobytes()
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": ARRAY_BUFFER})
        blob += _pad(data, b"\0")
        accessors.append({"bufferView": len(views) - 1, "componentType": FLOAT, "count": int(len(pos)), "type": "VEC3",
                          "min": [float(v) for v in pos.min(axis=0)], "max": [float(v) for v in pos.max(axis=0)]})
        prim = {"attributes": {"POSITION": len(accessors) - 1}, "mode": 4}
        if extras.get("alpha") is not None:
            alpha = float(extras["alpha"])
            if not 0.0 <= alpha <= 1.0:
                raise GltfError(f"part {name}: alpha must be between 0 and 1")
            materials.append({"name": f"{name}_blend", "alphaMode": "BLEND", "doubleSided": True,
                              "pbrMetallicRoughness": {"baseColorFactor": [0.5, 0.5, 0.5, alpha], "metallicFactor": 0.0}})
            prim["material"] = len(materials) - 1
        meshes.append({"name": name, "primitives": [prim]})
        nodes.append({"name": name, "mesh": len(meshes) - 1, "extras": extras})
    doc = {"asset": {"version": "2.0", "generator": "AeroPlan", "extras": {"aircraft": aircraft, "frame": FRAME,
                                                                          "units": "m", "to_gltf": TO_GLTF}},
           "scene": 0, "scenes": [{"name": aircraft, "nodes": list(range(len(nodes)))}],
           "nodes": nodes, "meshes": meshes, "accessors": accessors, "bufferViews": views,
           "buffers": [{"byteLength": len(blob)}]}
    if materials:
        doc["materials"] = materials
    js = _pad(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8"), b" ")
    bn = bytes(blob)
    total = 12 + 8 + len(js) + 8 + len(bn)
    return (struct.pack("<III", MAGIC, VERSION, total) + struct.pack("<II", len(js), JSON_CHUNK) + js
            + struct.pack("<II", len(bn), BIN_CHUNK) + bn)


def read_glb(data: bytes) -> Tuple[Dict[str, Any], Dict[str, Tuple[np.ndarray, Dict[str, Any]]]]:
    """(asset extras, {part name: (triangles (n, 3, 3), node extras)}) of GLB bytes from write_glb."""
    if len(data) < 20:
        raise GltfError("the file is too short for GLB")
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != MAGIC or version != VERSION or total != len(data):
        raise GltfError("not a GLB 2.0 file (magic, version or length)")
    jl, jt = struct.unpack_from("<II", data, 12)
    if jt != JSON_CHUNK:
        raise GltfError("the first GLB chunk is not JSON")
    doc = json.loads(data[20:20 + jl].decode("utf-8"))
    off = 20 + jl
    bl, bt = struct.unpack_from("<II", data, off)
    if bt != BIN_CHUNK:
        raise GltfError("the second GLB chunk is not BIN")
    blob = data[off + 8: off + 8 + bl]
    parts = {}
    for n in doc.get("nodes", []):
        prim = doc["meshes"][n["mesh"]]["primitives"][0]
        acc = doc["accessors"][prim["attributes"]["POSITION"]]
        view = doc["bufferViews"][acc["bufferView"]]
        if acc["componentType"] != FLOAT or acc["type"] != "VEC3" or prim.get("mode", 4) != 4:
            raise GltfError(f"part {n['name']}: only float VEC3 triangles are read")
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        pos = np.frombuffer(blob, dtype="<f4", count=acc["count"] * 3, offset=start).reshape(-1, 3)
        parts[n["name"]] = (pos.reshape(-1, 3, 3).astype(np.float64), n.get("extras") or {})
    return doc["asset"].get("extras") or {}, parts
