"""Config adapter: hand YAML in, canonical JSON out. Replaces Aerolink hand-config JSON."""
from __future__ import annotations

from pathlib import Path
from typing import List

from ..config import compile_yaml, roundtrip_ok
from .base import Adapter


class ConfigYamlAdapter(Adapter):
    name = "config_yaml"
    produces = ("config",)

    def ingest(self, source: Path, out_dir: Path) -> List[Path]:
        source = Path(source)
        dst = compile_yaml(source, Path(out_dir) / (source.stem + ".json"))
        if not roundtrip_ok(source, dst):
            raise RuntimeError(f"round-trip failed for {source}")
        return [dst]
