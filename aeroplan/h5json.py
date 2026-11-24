"""JSON <-> HDF5: the data files of a `.muas` package (`data/<name>.h5`).

A data file holds one dataset: a JSON value (an ADH DAVEfunc, or a table). A write followed by a read gives the same
JSON value, so the dataset hash (sha256 of its canonical JSON, see aeroplan.assets) is the same on both sides.

Mapping rules:

  - object               -> group (key order kept)
  - str, int, float, bool -> attribute. A str longer than LONG_TEXT characters goes into a scalar string dataset.
  - a str of numbers in canonical form (a DAVE-ML dataTable or bpVals, see `numbers_text`) with NUM_TEXT or more
                            numbers -> a float64 dataset with the attribute `_numtext` = True. The reader gives the same
                            str back.
  - list of numbers      -> dataset (int64 when every item is an int, else float64). A rectangular list of number
                            lists (for example points) -> a 2-D dataset.
  - list of str          -> dataset of UTF-8 strings
  - list of objects with the same number keys (for example points {x, y, z}) -> a table dataset (one column per
                            key, attribute `_records` = True)
  - any other list       -> group with attribute `_list` = True and members "0000", "0001", ...
  - None                 -> refused (a dataset holds no None, see aeroplan.assets.clean)

A dataset carries the attribute `_list` = True, so an empty or one-item list reads back as a list. An array of
CHUNK or more items is chunked and compressed (gzip). No time stamps are written, so the same JSON value gives the
same file bytes.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict

import h5py
import numpy as np

LONG_TEXT = 4096
NUM_TEXT = 16
CHUNK = 256
_LIST = "_list"
_TEXT = "_text"
_RECORDS = "_records"
_NUMTEXT = "_numtext"
_STR = h5py.string_dtype("utf-8")


class H5JsonError(ValueError):
    """A value cannot be stored, or the file is not a data file of this form."""


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, (bool, np.bool_))


def _numeric_array(values: list):
    """A numeric array of a list (or a rectangular list of number lists), else None."""
    if values and all(_is_number(v) for v in values):
        return np.asarray(values, dtype=np.int64 if all(isinstance(v, (int, np.integer)) for v in values) else np.float64)
    if values and all(isinstance(v, list) and v and all(_is_number(x) for x in v) for v in values) \
            and len({len(v) for v in values}) == 1:
        return np.asarray(values, dtype=np.float64)
    return None


def _records(values: list):
    """A structured array of a list of objects that share the same number keys, else None."""
    if not values or not all(isinstance(v, dict) and v for v in values):
        return None
    keys = list(values[0])
    if any(list(v) != keys for v in values) or not all(_is_number(x) for v in values for x in v.values()):
        return None
    if any(not k or "/" in k for k in keys):
        return None
    dtype = [(k, np.int64 if all(isinstance(v[k], (int, np.integer)) for v in values) else np.float64) for k in keys]
    return np.array([tuple(v[k] for k in keys) for v in values], dtype=dtype)


def numbers_text(values) -> str:
    """The canonical text of a list of numbers: repr of each float, one space between them."""
    return " ".join(repr(float(v)) for v in values)


def _numtext(value: str):
    """The float array of a canonical number text (see numbers_text) of NUM_TEXT or more numbers, else None."""
    parts = value.split(" ")
    if len(parts) < NUM_TEXT:
        return None
    try:
        arr = np.array([float(p) for p in parts], dtype=np.float64)
    except ValueError:
        return None
    return arr if numbers_text(arr) == value else None


def _dataset(group: h5py.Group, key: str, data, **kw):
    n = int(np.prod(np.shape(data))) if np.ndim(data) else 1
    if n >= CHUNK and np.ndim(data):
        kw.update(compression="gzip", compression_opts=6, shuffle=True, chunks=True)
    return group.create_dataset(key, data=data, track_times=False, **kw)


def _group(parent: h5py.Group, key: str) -> h5py.Group:
    """A new group that keeps the key order and holds no time stamp (so the file bytes do not change with time)."""
    gcpl = h5py.h5p.create(h5py.h5p.GROUP_CREATE)
    gcpl.set_link_creation_order(h5py.h5p.CRT_ORDER_TRACKED | h5py.h5p.CRT_ORDER_INDEXED)
    gcpl.set_attr_creation_order(h5py.h5p.CRT_ORDER_TRACKED | h5py.h5p.CRT_ORDER_INDEXED)
    gcpl.set_obj_track_times(False)
    return h5py.Group(h5py.h5g.create(parent.id, key.encode("utf-8"), gcpl=gcpl))


def _check_key(key: str) -> str:
    if not isinstance(key, str) or not key or "/" in key or key in (".", _LIST, _TEXT, _RECORDS, _NUMTEXT, "_order"):
        raise H5JsonError(f"the key {key!r} cannot be stored in HDF5")
    return key


def _write_value(group: h5py.Group, key: str, value: Any) -> None:
    key = _check_key(key)
    if value is None:
        raise H5JsonError(f"{group.name}/{key} is None: a dataset holds no None")
    if isinstance(value, dict):
        _write_dict(_group(group, key), value)
    elif isinstance(value, (list, tuple)):
        value = list(value)
        arr = _numeric_array(value)
        if arr is not None:
            ds = _dataset(group, key, arr)
            ds.attrs[_LIST] = True
        elif (rec := _records(value)) is not None:
            ds = _dataset(group, key, rec)
            ds.attrs[_RECORDS] = True
        elif value and all(isinstance(v, str) for v in value):
            ds = group.create_dataset(key, data=np.array(value, dtype=object), dtype=_STR, track_times=False)
            ds.attrs[_LIST] = True
        else:
            g = _group(group, key)
            g.attrs[_LIST] = True
            for i, v in enumerate(value):
                if v is None:
                    raise H5JsonError(f"{group.name}/{key}[{i}] is None: a list item must hold a value")
                _write_value(g, f"{i:04d}", v)
    elif isinstance(value, str):
        if (arr := _numtext(value)) is not None:
            ds = _dataset(group, key, arr)
            ds.attrs[_NUMTEXT] = True
        elif len(value) > LONG_TEXT:
            ds = group.create_dataset(key, data=value, dtype=_STR, track_times=False)
            ds.attrs[_TEXT] = True
        else:
            group.attrs[key] = value
    elif isinstance(value, (bool, np.bool_)):
        group.attrs[key] = np.bool_(value)
    elif isinstance(value, (int, np.integer)):
        group.attrs[key] = np.int64(value)
    elif isinstance(value, (float, np.floating)):
        group.attrs[key] = np.float64(value)
    else:
        raise H5JsonError(f"{group.name}/{key}: the type {type(value).__name__} cannot be stored")


def _write_dict(group: h5py.Group, d: Dict[str, Any]) -> None:
    for k, v in d.items():
        _write_value(group, k, v)


def _scalar(v: Any) -> Any:
    if isinstance(v, bytes):
        return v.decode("utf-8")
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.ndarray) and v.ndim == 0:
        return _scalar(v[()])
    return v


def _read_node(obj) -> Any:
    if isinstance(obj, h5py.Dataset):
        if obj.attrs.get(_TEXT, False):
            return _scalar(obj.asstr()[()])
        if obj.attrs.get(_NUMTEXT, False):
            return numbers_text(obj[()])
        if obj.attrs.get(_RECORDS, False):
            names = obj.dtype.names
            return [{n: _scalar(row[n]) for n in names} for row in obj[()]]
        if h5py.check_string_dtype(obj.dtype) is not None:
            return [str(s) for s in obj.asstr()[()]]
        return obj[()].tolist()
    if obj.attrs.get(_LIST, False):
        return [_read_node(obj[k]) if k in obj else _scalar(obj.attrs[k])
                for k in sorted(set(obj.keys()) | (set(obj.attrs.keys()) - {_LIST}))]
    out: Dict[str, Any] = {}
    names = list(obj.attrs.keys()) + list(obj.keys())
    order = _creation_order(obj)
    for k in sorted(names, key=lambda n: order.get(n, len(order))):
        out[k] = _read_node(obj[k]) if k in obj else _scalar(obj.attrs[k])
    return out


def _creation_order(group: h5py.Group) -> Dict[str, int]:
    """The order in which the keys were written (attributes and members share one sequence on write)."""
    seq = group.attrs.get("_order")
    if seq is None:
        return {}
    return {str(k): i for i, k in enumerate(seq.tolist() if hasattr(seq, "tolist") else seq)}


def _stamp_order(group: h5py.Group, d: Dict[str, Any]) -> None:
    """Record the key order of a JSON object, so the reader gives the keys back in the same order."""
    keys = [k for k, v in d.items() if v is not None]
    if keys:
        group.attrs.create("_order", np.array(keys, dtype=object), dtype=_STR)
    for k, v in d.items():
        if isinstance(v, dict):
            _stamp_order(group[k], v)
        elif isinstance(v, (list, tuple)) and k in group and isinstance(group[k], h5py.Group)                 and group[k].attrs.get(_LIST, False):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    _stamp_order(group[k][f"{i:04d}"], item)


def _write(target, value: Dict[str, Any], attrs: Dict[str, str]) -> None:
    fcpl = h5py.h5p.create(h5py.h5p.FILE_CREATE)
    fcpl.set_obj_track_times(False)
    fapl = h5py.h5p.create(h5py.h5p.FILE_ACCESS)
    fapl.set_libver_bounds(h5py.h5f.LIBVER_EARLIEST, h5py.h5f.LIBVER_V110)
    if isinstance(target, io.BytesIO):
        fapl.set_fileobj_driver(h5py.h5fd.fileobj_driver, target)
        fid = h5py.h5f.create(b"in-memory", h5py.h5f.ACC_TRUNC, fapl=fapl, fcpl=fcpl)
    else:
        fid = h5py.h5f.create(str(target).encode("utf-8"), h5py.h5f.ACC_TRUNC, fapl=fapl, fcpl=fcpl)
    with h5py.File(fid) as f:
        for k, v in attrs.items():
            f.attrs[k] = v
        g = _group(f, "data")
        _write_dict(g, value)
        _stamp_order(g, value)


def write_file(path: Path, value: Dict[str, Any], *, attrs: Dict[str, str]) -> None:
    """Write one JSON object to an HDF5 file: root attributes `attrs`, the object in the group /data."""
    _write(Path(path), value, attrs)


def to_bytes(value: Dict[str, Any], *, attrs: Dict[str, str]) -> bytes:
    """The bytes of the HDF5 file of `value` (see write_file)."""
    buf = io.BytesIO()
    _write(buf, value, attrs)
    return buf.getvalue()


def read_file(src) -> tuple:
    """(root attributes, JSON object) of a data file. `src` is a path or the file bytes."""
    with h5py.File(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src, "r") as f:
        if "data" not in f:
            raise H5JsonError("the HDF5 file has no /data group")
        return {k: _scalar(v) for k, v in f.attrs.items()}, _drop_order(_read_node(f["data"]))


def read_group(path: Path, group: str) -> Any:
    """The JSON value of one group of an HDF5 file in this form (used once to read the retired muas-adh 1.0 file)."""
    with h5py.File(path, "r") as f:
        return _drop_order(_read_node(f[group]))


def _drop_order(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _drop_order(x) for k, x in v.items() if k != "_order"}
    if isinstance(v, list):
        return [_drop_order(x) for x in v]
    return v
