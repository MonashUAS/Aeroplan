"""Hand config is YAML. Machine files are canonical JSON (brief D14; user answer 6).

`compile_yaml` writes sorted-key JSON. `roundtrip_ok` is the CI round-trip check.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def compile_yaml(src: Path, dst: Path) -> Path:
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(canonical_json(load_yaml(src)), encoding="utf-8")
    return dst


def roundtrip_ok(src: Path, dst: Path) -> bool:
    """True when the JSON file holds exactly the data of the YAML file."""
    return json.loads(Path(dst).read_text(encoding="utf-8")) == load_yaml(src)


def strip_comments(obj: Any) -> Any:
    """Drop every key that starts with an underscore (the legacy Aerolink comment convention)."""
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [strip_comments(v) for v in obj]
    return obj


def _scalar(v: Any) -> str:
    return yaml.safe_dump(v, default_flow_style=True, width=10**6).replace("\n...\n", "").strip()


def json_to_commented_yaml(obj: dict, _pad: str = "") -> str:
    """Write a legacy JSON hand config (with `_` comment keys) as YAML. Comment keys become `#` lines.

    The data is unchanged: `strip_comments(obj)` equals `yaml.safe_load` of the result.
    """
    out = []
    for k, v in obj.items():
        if str(k).startswith("_"):
            tag = "" if k in ("_comment", "_readme") else f"{k[1:]}: "
            for i, line in enumerate(v if isinstance(v, list) else [v]):
                out.append(f"{_pad}# {tag if i == 0 else ''}{line}")
        elif isinstance(v, dict):
            out.append(f"{_pad}{k}:" if v else f"{_pad}{k}: {{}}")
            if v:
                out.append(json_to_commented_yaml(v, _pad + "  "))
        else:
            out.append(f"{_pad}{k}: {_scalar(v)}")
    return "\n".join(out)
