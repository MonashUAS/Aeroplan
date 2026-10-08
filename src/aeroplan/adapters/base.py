"""Adapter contract (brief section 3: ingestion adapters live in AeroPlan; user answer 2).

An adapter reads one tool's raw file and writes a manifest plus points file.
It never edits the ADH tree directly. `ingest` returns the paths it wrote.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List


class Adapter(ABC):
    name: str
    #: dataset or node kinds this adapter can write
    produces: tuple[str, ...] = ()

    @abstractmethod
    def ingest(self, source: Path, out_dir: Path) -> List[Path]:
        """Read `source`. Write results under `out_dir`. Return the written paths."""
