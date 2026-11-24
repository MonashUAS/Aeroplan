"""The nested ADH document: one `AircraftSystem` tree, as upstream ADH defines it.

Upstream ADH (Boeing/aircraft-data-hierarchy 96179ca) defines the work breakdown structure as nested classes:
`AircraftSystem` > `AirVehicle` > `Airframe` > `Wing` > `Ailerons` ... Each class has a `wbs_no` default. In the
document, a child node sits under the snake_case name of its class (`air_vehicle`, `airframe`, `wing`). This is the
layout of the NASA ADH Web Editor (NASA/CR-20250007045, Figure 15).

A node holds the fields of the upstream `Component` (name, description, geometry, parameters, metadata,
subcomponents, requirements, performance, behavior), its `wbs_no`, its child nodes, and the MUAS extension `muas`.

Rule for several parts on one WBS number: ADH has one node for "Ailerons" and one for "Stabilizer". The left and
right aileron, the horizontal tail and the fin are `subcomponents` of that node. A subcomponent has no `wbs_no`.
No WBS number is invented.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import MUAS_SCHEMA_VERSION
from .muas.node import validate_ext
from .muas.requirement import RequirementExt

COMPONENT_FIELDS = ("name", "description", "geometry", "parameters", "metadata", "subcomponents", "requirements",
                    "performance", "behavior")
GEOMETRY_FIELDS = ("point", "polyline", "spline", "cross_section", "reference_axis", "airfoil", "lifting_surface", "body")


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()


@lru_cache(maxsize=1)
def wbs_tree() -> Dict[str, Dict[str, Any]]:
    """WBS number -> {"path": (keys from the root), "name": class name, "children": {key: wbs}}. From upstream ADH."""
    from aircraft_data_hierarchy.common_base_model import CommonBaseModel
    from aircraft_data_hierarchy.work_breakdown_structure.work_breakdown_structure import AircraftSystem

    out: Dict[str, Dict[str, Any]] = {}

    def walk(cls, path: Tuple[str, ...]):
        wbs = cls.model_fields["wbs_no"].default
        children = {}
        for attr, v in vars(cls).items():
            if isinstance(v, type) and issubclass(v, CommonBaseModel) and "wbs_no" in getattr(v, "model_fields", {}):
                key = _snake(attr)
                children[key] = walk(v, path + (key,))
        out[wbs] = {"path": path, "name": cls.__name__, "children": children}
        return wbs

    walk(AircraftSystem, ())
    return out


def _by_path() -> Dict[Tuple[str, ...], str]:
    return {v["path"]: k for k, v in wbs_tree().items()}


def new_document(name: str, description: str) -> Dict[str, Any]:
    """An empty document: the 1.0 AircraftSystem node only."""
    return {"wbs_no": "1.0", "name": name, "description": description,
            "muas": {"ext_version": MUAS_SCHEMA_VERSION, "instance": "aircraft_system"}}


def node(doc: Dict[str, Any], wbs: str, create: bool = False) -> Dict[str, Any]:
    """The node of a WBS number. With `create`, make the missing nodes on the path (name = the ADH class name)."""
    tree = wbs_tree()
    if wbs not in tree:
        raise KeyError(f"{wbs} is not an ADH WBS number")
    cur, path = doc, ()
    for key in tree[wbs]["path"]:
        path += (key,)
        if key not in cur:
            if not create:
                raise KeyError(f"the document has no node {wbs} (missing {'.'.join(path)})")
            w = _by_path()[path]
            cur[key] = {"wbs_no": w, "name": tree[w]["name"]}
        cur = cur[key]
    return cur


#: The ADH ReferenceData (airframe_parameters.py) takes its aliases only. A field name such as reference_area passes
#: the validation as an unknown extra key and the value is lost, so validate_document refuses every other key.
REFERENCE_ALIASES = {"s_ref": "Sref", "b_ref": "BLref", "c_ref": "Cbar"}
REFERENCE_UNITS = {"s_ref": "m^2", "b_ref": "m", "c_ref": "m"}


def reference(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The reference values of the air vehicle as quantities {s_ref, b_ref, c_ref: {value, units}}: the ADH
    `parameters.reference_data` of node 1.2 (SI by patch 0004). An empty dict when the node has none."""
    if not has_node(doc, "1.2"):
        return {}
    rd = (node(doc, "1.2").get("parameters") or {}).get("reference_data") or {}
    return {k: {"value": float(rd[a]), "units": REFERENCE_UNITS[k]} for k, a in REFERENCE_ALIASES.items() if a in rd}


def set_reference(doc: Dict[str, Any], s_ref: float, b_ref: float, c_ref: float) -> None:
    """Write the reference values of the air vehicle (m^2, m, m) to the ADH `parameters.reference_data` of node 1.2."""
    air = node(doc, "1.2", create=True)
    rd = air.setdefault("parameters", {}).setdefault("reference_data", {})
    rd.update({"Sref": float(s_ref), "BLref": float(b_ref), "Cbar": float(c_ref)})


def control_surface(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The control surface of an item: `muas.control_surface` with `eta_span` and `hinge_x_over_c` from the ADH
    parameters (ADR 0027). A left or right surface is an `AsymmetricControl`, a surface on both halves a `SymmetricFlap`.
    The ADH chord ratio is the control chord over the local chord: hinge_x_over_c = 1 - chord ratio. None when the item
    is not a control surface."""
    cs = (item.get("muas") or {}).get("control_surface")
    if not cs:
        return None
    p = item.get("parameters") or {}
    if "asymmetric_control" in p:
        a = p["asymmetric_control"]
        eta, ratio = [a["inboard_span_ratio"], a["outboard_span_ratio"]], a["inboard_aileron_chord_ratio"]
    elif "symmetric_flap" in p:
        s = p["symmetric_flap"]
        eta, ratio = [s["inboard_span_ratio"][0], s["outboard_span_ratio"][0]], s["inboard_chord_ratio"][0]
    else:
        raise ValueError(f"{cs['parent']} control surface {item['muas']['instance']}: no ADH parameters.asymmetric_control "
                         "or parameters.symmetric_flap")
    return {**cs, "eta_span": [float(e) for e in eta], "hinge_x_over_c": round(1.0 - float(ratio), 12)}


def set_control_geometry(item: Dict[str, Any], eta_span, hinge_x_over_c: float) -> None:
    """Write the span fractions and the hinge of a control surface item to its ADH parameters (see control_surface)."""
    side = item["muas"]["control_surface"].get("side", "both")
    eta0, eta1 = (round(float(e), 12) for e in eta_span)
    ratio = round(1.0 - float(hinge_x_over_c), 12)
    params = item.setdefault("parameters", {})
    params.pop("asymmetric_control", None)
    params.pop("symmetric_flap", None)
    if side == "both":
        params["symmetric_flap"] = {"flap_type": 1, "inboard_span_ratio": [eta0], "outboard_span_ratio": [eta1],
                                    "inboard_chord_ratio": [ratio], "outboard_chord_ratio": [ratio]}
    else:
        params["asymmetric_control"] = {"control_type": 4, "inboard_span_ratio": eta0, "outboard_span_ratio": eta1,
                                        "inboard_aileron_chord_ratio": ratio, "outboard_aileron_chord_ratio": ratio}


def has_node(doc: Dict[str, Any], wbs: str) -> bool:
    try:
        node(doc, wbs)
        return True
    except KeyError:
        return False


def child_keys(n: Dict[str, Any]) -> List[str]:
    """The keys of a node that hold child WBS nodes."""
    kids = wbs_tree()[n["wbs_no"]]["children"]
    return [k for k in n if k in kids]


def iter_nodes(doc: Dict[str, Any]) -> Iterator[Tuple[str, Dict[str, Any], Optional[str]]]:
    """Every node and subcomponent: (dotted path, item, parent instance or None for a WBS node)."""

    def subs(item, path, parent):
        for i, s in enumerate(item.get("subcomponents") or []):
            p = f"{path}.subcomponents[{i}]"
            yield p, s, parent
            yield from subs(s, p, (s.get("muas") or {}).get("instance"))

    def walk(n, path):
        yield path, n, None
        yield from subs(n, path, (n.get("muas") or {}).get("instance"))
        for k in child_keys(n):
            yield from walk(n[k], f"{path}.{k}")

    yield from walk(doc, "aircraft_system")


def find(doc: Dict[str, Any], instance: str) -> Dict[str, Any]:
    """The node or subcomponent whose `muas.instance` is `instance`."""
    for _, item, _ in iter_nodes(doc):
        if (item.get("muas") or {}).get("instance") == instance:
            return item
    raise KeyError(f"the document has no item with muas.instance {instance!r}")


def put_subcomponent(parent: Dict[str, Any], comp: Dict[str, Any]) -> Dict[str, Any]:
    """Add a subcomponent, or replace the one with the same `muas.instance`. Returns the stored item."""
    inst = comp["muas"]["instance"]
    subs = parent.setdefault("subcomponents", [])
    for i, s in enumerate(subs):
        if (s.get("muas") or {}).get("instance") == inst:
            subs[i] = comp
            return comp
    subs.append(comp)
    return comp


def muas(item: Dict[str, Any], instance: str) -> Dict[str, Any]:
    """The `muas` key of an item, made when it is missing."""
    return item.setdefault("muas", {"ext_version": MUAS_SCHEMA_VERSION, "instance": instance})


def _component_view(item: Dict[str, Any]) -> Dict[str, Any]:
    """The fields of an item that upstream `Component` validates. ADH Geometry needs every key, so fill with None."""
    view = {k: item[k] for k in COMPONENT_FIELDS if k in item}
    if "geometry" in view:
        view["geometry"] = {k: view["geometry"].get(k) for k in GEOMETRY_FIELDS} | dict(view["geometry"])
    view["subcomponents"] = [_component_view(s) for s in item.get("subcomponents") or []] or None
    return view


def validate_document(doc: Dict[str, Any]) -> None:
    """Check the tree against upstream ADH, then each `muas` key. Raises ValueError with the path of the fault."""
    from aircraft_data_hierarchy.work_breakdown_structure.airframe import Component

    tree = wbs_tree()
    instances: Dict[str, str] = {}

    def check_item(item, path, wbs_node: bool):
        allowed = set(COMPONENT_FIELDS) | {"muas"}
        if wbs_node:
            wbs = item.get("wbs_no")
            if wbs not in tree:
                raise ValueError(f"{path}: wbs_no {wbs!r} is not an ADH WBS number")
            expected = _by_path().get(tuple(path.split(".")[1:]))
            if expected != wbs:
                raise ValueError(f"{path}: wbs_no {wbs} does not match its place in the ADH tree ({expected})")
            allowed |= {"wbs_no"} | set(tree[wbs]["children"])
        elif "wbs_no" in item:
            raise ValueError(f"{path}: a subcomponent has no wbs_no (it shares the number of its WBS node)")
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise ValueError(f"{path}: unknown keys {unknown}")
        rd = (item.get("parameters") or {}).get("reference_data") or {}
        bad = sorted(set(rd) - set(REFERENCE_ALIASES.values()) - {"RougHgt"})
        if bad:
            raise ValueError(f"{path}: parameters.reference_data keys {bad}: ADH reads only its aliases Sref, BLref, "
                             "Cbar and RougHgt")
        try:
            Component.model_validate(_component_view(item))
        except Exception as e:
            raise ValueError(f"{path}: not a valid ADH Component: {e}") from e
        for req in item.get("requirements") or []:
            if "muas" in req:
                RequirementExt.model_validate(req["muas"])
        if (item.get("muas") or {}).get("control_surface"):
            cs = control_surface(item)
            if not (0 <= cs["eta_span"][0] < cs["eta_span"][1] <= 1 and 0 <= cs["hinge_x_over_c"] < 1):
                raise ValueError(f"{path}: control surface span ratios must rise inside 0..1 and the chord ratio must be "
                                 "in 0..1")
        if "muas" in item:
            ext = validate_ext(item["muas"], path, item.get("wbs_no") if wbs_node else None)
            if ext.instance in instances:
                raise ValueError(f"{path}: muas.instance {ext.instance!r} is also used at {instances[ext.instance]}")
            instances[ext.instance] = path
        for i, s in enumerate(item.get("subcomponents") or []):
            check_item(s, f"{path}.subcomponents[{i}]", False)

    def walk(n, path):
        check_item(n, path, True)
        for k in child_keys(n):
            walk(n[k], f"{path}.{k}")

    if doc.get("wbs_no") != "1.0":
        raise ValueError("the document root must be the 1.0 AircraftSystem node")
    walk(doc, "aircraft_system")


def normalize(doc: Dict[str, Any]) -> None:
    """Write every `muas` key in its validated form: defaults filled in, units in SI spelling, no None values.

    A reader of the file (Aerolink) then needs no MUAS default of its own. The aero model (an ADH DAVEfunc) is kept
    as written.
    """
    from .muas.node import MuasNodeExt

    for _, item, _ in iter_nodes(doc):
        if "muas" in item:
            item["muas"] = MuasNodeExt.model_validate(item["muas"]).model_dump(mode="json", exclude_none=True)
            item["muas"]["ext_version"] = MUAS_SCHEMA_VERSION         # the block is now in the form of this version
