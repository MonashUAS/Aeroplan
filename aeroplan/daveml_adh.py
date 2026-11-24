"""DAVE-ML 2.0 (ANSI/AIAA S-119) XML <-> the ADH `DAVEfunc` form (upstream behavior.py).

ADH holds DAVE-ML as Pydantic classes with snake_case fields (`variableDef` -> `variable_def`, `varID` -> `var_id`).
The `.muas` file stores the aero model in that form, so the model is ADH data. A tool that needs the XML (the
Aerolink spoke, the DTD check) makes it again with `to_xml`.

The conversion keeps the element order of the source, so `to_xml(from_xml(x))` gives the same elements, attributes
and text as `x`. MathML inside `calculation` is kept as text in `Calculation.math`.
"""
from __future__ import annotations

import re
import typing
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

NS, MATHML = "http://daveml.org/2010/DAVEML", "http://www.w3.org/1998/Math/MathML"
XLINK = "http://www.w3.org/1999/xlink"
# XML attributes in another namespace -> the ADH field name (DTD: <reference xlink:href=...>)
NS_ATTRIBUTES = {f"{{{XLINK}}}href": "href"}
DOCTYPE = ('<!DOCTYPE DAVEfunc PUBLIC "-//AIAA//DTD for Flight Dynamic Models - Functions 2.0//EN" '
           '"http://daveml.org/DTDs/2p0/DAVEfunc.dtd">')

# XML attributes of each DAVE-ML 2.0 element (DAVEfunc.dtd). Every other item of an element is a child element.
ATTRIBUTES = {
    "fileHeader": ("name",), "author": ("name", "org", "xns", "email"), "creationDate": ("date",),
    "variableDef": ("name", "varID", "units", "axisSystem", "sign", "alias", "symbol", "initialValue", "minValue",
                    "maxValue"),
    "breakpointDef": ("name", "bpID", "units"), "bpRef": ("bpID",),
    "griddedTableDef": ("name", "gtID", "units"), "griddedTableRef": ("gtID",), "griddedTable": ("name",),
    "ungriddedTableDef": ("name", "utID", "units"), "ungriddedTableRef": ("utID",), "ungriddedTable": ("name",),
    "function": ("name",), "functionDefn": ("name",),
    "independentVarRef": ("varID", "min", "max", "extrapolate", "interpolate"), "dependentVarRef": ("varID",),
    "independentVarPts": ("varID", "name", "units", "sign", "extrapolate", "interpolate"),
    "dependentVarPts": ("varID", "name", "units", "sign"),
    "staticShot": ("name", "refID"), "signal": (), "reference": ("refID", "author", "title", "classification",
                                                                 "accession", "date"),
    "provenance": ("provID",), "provenanceRef": ("provID",), "modificationRecord": ("modID", "date", "refID"),
    "dataPoint": ("modID",), "confidenceBound": ("value",), "normalPDF": ("numSigmas",), "uniformPDF": (),
    "uncertainty": ("effect",), "documentRef": ("docID", "refID"),
}
# DAVE-ML wrapper elements that ADH flattens into a list field: ADH field -> (wrapper tag, item tag)
WRAPPERS = {"breakpoint_refs": ("breakpointRefs", "bpRef")}
# Element names whose ADH field is the element text (the class has a `value` field for it)
TEXT_FIELD = "value"


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z]+)", r"_\1", name).lower()


@lru_cache(maxsize=None)
def _camel_names() -> Dict[str, str]:
    """snake_case -> DAVE-ML spelling, for every element and attribute name of the table and the ADH classes."""
    names = set(ATTRIBUTES)
    for attrs in ATTRIBUTES.values():
        names.update(attrs)
    names.update(("isInput", "isControl", "isDisturbance", "isState", "isStateDeriv", "isOutput", "isStdAIAA",
                  "bpVals", "dataTable", "breakpointRefs", "calculation", "checkData", "checkInputs", "checkOutputs",
                  "internalValues", "signalName", "signalUnits", "signalValue", "varID", "tol", "description",
                  "fileVersion", "description", "staticShot", "variableDef", "breakpointDef", "griddedTableDef",
                  "ungriddedTableDef", "functionDefn", "independentVarRef", "dependentVarRef"))
    return {_snake(n): n for n in names}


def _camel(name: str) -> str:
    return _camel_names().get(name) or re.sub(r"_([a-z])", lambda m: m.group(1).upper(), name)


@lru_cache(maxsize=None)
def _fields(cls) -> Dict[str, Tuple[bool, Any]]:
    """field name -> (is a list, the ADH model class of the item or None for a plain value)."""
    from pydantic import BaseModel

    out = {}
    for name, f in cls.model_fields.items():
        ann, is_list = f.annotation, False
        if isinstance(ann, typing.ForwardRef):  # upstream classes that use a class defined later in the module
            import sys

            ann = eval(ann.__forward_arg__, vars(sys.modules[cls.__module__]), {"Optional": Optional, "List": List})
        for _ in range(4):
            origin = typing.get_origin(ann)
            if origin in (list, List):
                is_list, ann = True, typing.get_args(ann)[0]
            elif origin is typing.Union or str(origin) == "types.UnionType":
                args = [a for a in typing.get_args(ann) if a is not type(None)]
                ann = args[0]
            else:
                break
        model = ann if isinstance(ann, type) and issubclass(ann, BaseModel) else None
        out[name] = (is_list, model)
    return out


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _element_to_dict(e: ET.Element, cls) -> Dict[str, Any]:
    fields = _fields(cls)
    tag = _local(e.tag)
    out: Dict[str, Any] = {}
    for a, v in e.attrib.items():
        if a in ATTRIBUTES.get(tag, ()):
            out[_snake(a)] = v
        elif a in NS_ATTRIBUTES and NS_ATTRIBUTES[a] in fields:
            out[NS_ATTRIBUTES[a]] = v
    unknown = set(e.attrib) - set(ATTRIBUTES.get(tag, ())) - {a for a in NS_ATTRIBUTES if NS_ATTRIBUTES[a] in fields}
    if unknown:
        raise ValueError(f"<{tag}>: attributes {sorted(unknown)} are not in the DAVE-ML table of daveml_adh")
    text = (e.text or "").strip()
    if text and TEXT_FIELD in fields and not len(e):
        out[TEXT_FIELD] = text
    for child in e:
        ctag = _local(child.tag)
        key = _snake(ctag)
        if key not in fields:
            raise ValueError(f"<{tag}> has the child <{ctag}>, which the ADH class {cls.__name__} does not define")
        is_list, model = fields[key]
        if key in WRAPPERS:
            out[key] = [_element_to_dict(g, model) for g in child]
            continue
        if ctag == "calculation":
            math = next(iter(child), None)
            value: Any = {"math": _math_text(math)} if math is not None else {}
        elif model is None:
            value = True if not len(child) and not (child.text or "").strip() and _is_flag(cls, key) \
                else (child.text or "").strip()
        else:
            value = _element_to_dict(child, model)
        if is_list:
            out.setdefault(key, []).append(value)
        elif key in out:
            raise ValueError(f"<{tag}> has <{ctag}> twice, but ADH {cls.__name__}.{key} holds one")
        else:
            out[key] = value
    return out


def _is_flag(cls, key: str) -> bool:
    return cls.model_fields[key].annotation in (Optional[bool], bool)


def _math_text(math: ET.Element) -> str:
    ET.register_namespace("", MATHML)
    return ET.tostring(math, encoding="unicode").strip()


def from_xml(data: bytes) -> Dict[str, Any]:
    """The ADH DAVEfunc form of a DAVE-ML 2.0 file. Checked with the upstream ADH class."""
    from aircraft_data_hierarchy.behavior import DAVEfunc

    root = ET.fromstring(data)
    if _local(root.tag) != "DAVEfunc":
        raise ValueError("the root element is not DAVEfunc")
    d = _element_to_dict(root, DAVEfunc)
    DAVEfunc.model_validate(d)
    return d


def _scalar_text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return format(v, ".17g")
    return str(v)


def _dict_to_element(parent: Optional[ET.Element], tag: str, d: Any, cls) -> ET.Element:
    e = ET.Element(f"{{{NS}}}{tag}") if parent is None else ET.SubElement(parent, f"{{{NS}}}{tag}")
    if not isinstance(d, dict):
        e.text = _scalar_text(d)
        return e
    attrs = ATTRIBUTES.get(tag, ())
    fields = _fields(cls)
    ns_attrs = {f: a for a, f in NS_ATTRIBUTES.items()}
    for k, v in d.items():
        ctag = _camel(k)
        if k in ns_attrs and tag == "reference":
            e.set(ns_attrs[k], _scalar_text(v))
            continue
        if ctag in attrs:
            e.set(ctag, _scalar_text(v))
            continue
        if k == TEXT_FIELD and ctag not in attrs:
            e.text = _scalar_text(v)
            continue
        if k not in fields:
            raise ValueError(f"{tag}.{k} is not a field of ADH {cls.__name__}")
        is_list, model = fields[k]
        if k in WRAPPERS:
            w, item_tag = WRAPPERS[k]
            wrap = ET.SubElement(e, f"{{{NS}}}{w}")
            for item in v:
                _dict_to_element(wrap, item_tag, item, model)
            continue
        for item in (v if is_list else [v]):
            if ctag == "calculation":
                c = ET.SubElement(e, f"{{{NS}}}calculation")
                if item.get("math"):
                    c.append(ET.fromstring(item["math"]))
            elif model is None:
                if item is True and _is_flag(cls, k):
                    ET.SubElement(e, f"{{{NS}}}{ctag}")
                else:
                    ET.SubElement(e, f"{{{NS}}}{ctag}").text = _scalar_text(item)
            else:
                _dict_to_element(e, ctag, item, model)
    return e


def to_xml(d: Dict[str, Any]) -> bytes:
    """DAVE-ML 2.0 XML of an ADH DAVEfunc form, with the S-119 DOCTYPE."""
    from aircraft_data_hierarchy.behavior import DAVEfunc

    ET.register_namespace("", NS)
    ET.register_namespace("xlink", XLINK)
    root = _dict_to_element(None, "DAVEfunc", d, DAVEfunc)
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    body = re.sub(r'<(\w+:)?math xmlns(:\w+)?="' + re.escape(MATHML) + '"', f'<math xmlns="{MATHML}"', body)
    body = _strip_math_prefix(body)
    body = _xlink_on_reference(body)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + DOCTYPE + "\n" + body + "\n").encode("utf-8")


def _xlink_on_reference(body: str) -> str:
    """ElementTree declares the xlink namespace on the root. The DTD declares it on <reference> only."""
    decl = f' xmlns:xlink="{XLINK}"'
    if decl not in body:
        return body
    body = body.replace(decl, "", 1)
    return re.sub(r"<reference(?=[\s>/])([^>]*?)xlink:href=", lambda m: f"<reference{m.group(1)}{decl.strip()} xlink:href=",
                  body)


def _strip_math_prefix(body: str) -> str:
    """ElementTree writes the MathML elements with a prefix (ns0:apply). DAVE-ML files use the default namespace."""
    m = re.search(r'xmlns:(\w+)="' + re.escape(MATHML) + '"', body)
    if not m:
        return body
    p = m.group(1)
    body = body.replace(f' xmlns:{p}="{MATHML}"', "")
    body = body.replace(f"<{p}:math>", f'<math xmlns="{MATHML}">').replace(f"<{p}:math ", f'<math xmlns="{MATHML}" ')
    return body.replace(f"<{p}:", "<").replace(f"</{p}:", "</")


def canonical(data: bytes) -> List[Tuple[str, Dict[str, str], str]]:
    """Elements of a DAVE-ML file in document order, as (tag, attributes, text): for round-trip tests."""
    return [(_local(e.tag), dict(e.attrib), (e.text or "").strip()) for e in ET.fromstring(data).iter()]


def compare(a: bytes, b: bytes, limit: int = 10) -> List[str]:
    """The differences between two DAVE-ML files: elements, attributes and text in document order (comments and
    whitespace do not count). Empty when the files hold the same model."""
    ca, cb = canonical(a), canonical(b)
    out = []
    if len(ca) != len(cb):
        out.append(f"{len(ca)} elements against {len(cb)}")
    for i, (x, y) in enumerate(zip(ca, cb)):
        if x != y:
            out.append(f"element {i}: {x[0]} {x[1]} {x[2][:40]!r} against {y[0]} {y[1]} {y[2][:40]!r}")
            if len(out) >= limit:
                break
    return out
