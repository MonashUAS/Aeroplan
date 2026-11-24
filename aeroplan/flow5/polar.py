"""flow5 polar reader: one flow5 7.57 polar text file (`*.csv`, fixed-width text, no commas).

Facts used here, and where each comes from. Nothing else is assumed.

- The polar layout (header block, welded first row, declared row count): read from the files, same traps as in
  the Aerolink CLAUDE.md.
- Control deflection = lo + Ctrl * (hi - lo), with lo and hi from the first nonzero `Range_k` header line.
  Source: Aerolink `control_derivatives`. The sign of a positive flow5 flap is NOT verified.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

_GREEK = {"α": "alpha", "β": "beta", "φ": "phi"}
_COUNT = re.compile(r"Nbr\. of data points\s*=\s*(\d+)")
_RANGE = re.compile(r"^\s*(Range_\d+):\s+([-+\d.eE]+),\s+([-+\d.eE]+)")
_SPEED = re.compile(r"Freestream speed\s*=\s*([-+\d.eE]+)\s*m/s")


class PolarError(ValueError):
    """The polar file is malformed or incomplete."""


@dataclass
class Polar:
    path: Path
    columns: List[str]
    data: np.ndarray
    ranges: List[Tuple[str, float, float]]
    declared: Optional[int]
    speed: Optional[float]

    def col(self, name: str) -> np.ndarray:
        try:
            return self.data[:, self.columns.index(name)]
        except ValueError:
            raise PolarError(f"{self.path.name}: no column {name!r}") from None


def _num(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _label(s: str) -> str:
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s.strip())
    return _GREEK.get(s, s)


def parse_polar_text(text: str, path: Path = Path("polar")) -> Polar:
    """Parse one flow5 polar. Refuses a file whose row count differs from the count the file declares."""
    lines = text.split("\n")
    head_i = next((i for i, ln in enumerate(lines) if "Ctrl" in ln and "CL" in ln and "CD" in ln), None)
    if head_i is None:
        raise PolarError(f"{path.name}: no polar table header")
    declared = speed = None
    ranges: List[Tuple[str, float, float]] = []
    for ln in lines[:head_i]:
        if m := _COUNT.search(ln):
            declared = int(m.group(1))
        if m := _RANGE.match(ln):
            ranges.append((m.group(1), float(m.group(2)), float(m.group(3))))
        if m := _SPEED.search(ln):
            speed = float(m.group(1))
    rows = [ln.split() for ln in lines[head_i + 1:] if ln.split() and all(_num(t) for t in ln.split())]
    width = len(rows[0]) if rows else None
    head = lines[head_i]
    tokens = [(m.start(), m.group()) for m in re.finditer(r"\S+", head)]
    k = len(tokens)
    while k > 0 and _num(tokens[k - 1][1]):  # the first data row sits on the label line
        k -= 1
    tail = tokens[k:]
    if width is not None and len(tail) > width:
        tail = tokens[len(tokens) - width:]
    label_end = tail[0][0] if tail else len(head)
    columns = [_label(x) for x in re.split(r"\s{2,}", head[:label_end].strip()) if x]
    body = ([[float(t[1]) for t in tail]] if tail else []) + [[float(t) for t in r] for r in rows]
    if any(len(r) != len(columns) for r in body):
        raise PolarError(f"{path.name}: {len(columns)} labels but rows of {sorted({len(r) for r in body})} values")
    if declared is not None and declared != len(body):
        raise PolarError(f"{path.name}: {len(body)} points found, {declared} declared. Refusing a partial polar")
    return Polar(path, columns, np.array(body, dtype=float).reshape(len(body), len(columns)), ranges, declared, speed)


def control_range(polar: Polar) -> Tuple[float, float, bool]:
    """The deflection range of a T6 polar: (lo, hi, antisymmetric).

    Every nonzero `Range_k` must equal the first one or be its exact reverse (the two ailerons move in
    opposite directions, so the second range runs from +15 to -15). The first nonzero range is the reference.
    `antisymmetric` is True when a reversed range exists.
    """
    nz = [(lo, hi) for _, lo, hi in polar.ranges if lo != hi]
    if not nz:
        raise PolarError(f"{polar.path.name}: no nonzero Range in the header")
    lo, hi = nz[0]
    for r in nz[1:]:
        if r not in ((lo, hi), (hi, lo)):
            raise PolarError(f"{polar.path.name}: ranges {nz} are neither equal nor reversed")
    return lo, hi, any(r == (hi, lo) for r in nz[1:])
