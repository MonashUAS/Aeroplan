"""`aeroplan doctor`: what this computer has and lacks for AeroPlan, with one fix line for each missing item.

It imports no tool package (rule AP001). It finds the optional packages with `importlib.util.find_spec` and the programs on
the PATH, so it runs on a fresh install before any spoke works.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from typing import List

from . import REPO_ROOT

INSTALL_ALL = 'pip install -e ".[all]"'


@dataclass
class Item:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    needed: bool = True        # False: an optional tool (a spoke that needs it says so)


def _has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def items() -> List[Item]:
    out: List[Item] = []
    v = sys.version_info
    out.append(Item("Python 3.10 or newer", v >= (3, 10), f"{v.major}.{v.minor}.{v.micro} at {sys.executable}",
                    "install Python 3.10 or newer"))
    in_venv = sys.prefix != sys.base_prefix
    out.append(Item("a venv", in_venv, sys.prefix if in_venv else "this Python is not a venv",
                    "python -m venv .venv, then activate it (docs/tutorials/first-day.md)"))
    out.append(Item("git", shutil.which("git") is not None, shutil.which("git") or "not on the PATH",
                    "install git: the ADH build applies its patches with git"))
    adh = REPO_ROOT / "standards" / "adh" / "build" / "src"
    out.append(Item("the patched ADH", adh.is_dir(), str(adh), "python standards/adh/build_adh.py"))
    try:
        from importlib.metadata import PackageNotFoundError, distribution

        dist = distribution("aeroplan")
        out.append(Item("aeroplan installed", True, f"version {dist.version}", INSTALL_ALL))
    except PackageNotFoundError:
        out.append(Item("aeroplan installed", False, "this Python has no install of aeroplan", INSTALL_ALL))
    for module, what in (("pytest", "the tests"), ("ruff", "the lint")):
        out.append(Item(module, _has(module), what, INSTALL_ALL))
    for module, what in (("aerosandbox", "the AeroSandbox model files"), ("ipykernel", "the notebooks (the .venv kernel)"),
                         ("matplotlib", "the plots")):
        out.append(Item(module, _has(module), what, INSTALL_ALL))
    out.append(Item("proptimiser", _has("proptimiser"), "the propeller models (the sizing notebook needs it)",
                    'get read access to the private Proptimiser repository, run `gh auth login`, then '
                    'pip install -e ".[prop]" (Python 3.12 or newer)', needed=False))
    vsp = REPO_ROOT / "aeroplan" / "openvsp" / ".venv"
    out.append(Item("OpenVSP Python", vsp.is_dir(), str(vsp), "download OpenVSP, then python -m aeroplan setup OpenVSP",
                    needed=False))
    flow5 = os.environ.get("FLOW5_EXE") or shutil.which("flow5") or shutil.which("flow5.exe")
    out.append(Item("flow5", bool(flow5), flow5 or "not on the PATH and no FLOW5_EXE (the sweep also looks in Program Files)",
                    "install flow5, or set FLOW5_EXE",
                    needed=False))
    dot = shutil.which("dot")
    out.append(Item("Graphviz dot", bool(dot), dot or "not on the PATH", "install Graphviz (only the ADH tree drawing uses it)",
                    needed=False))
    return out


def report() -> str:
    lines, missing = [], 0
    for it in items():
        mark = "ok  " if it.ok else ("FAIL" if it.needed else "--  ")
        lines.append(f"{mark} {it.name}: {it.detail}")
        if not it.ok:
            lines.append(f"     fix: {it.fix}")
            missing += it.needed
    lines.append("All needed items are here." if not missing else f"{missing} needed items are missing: do the fix lines.")
    return "\n".join(lines)


def ok() -> bool:
    return all(it.ok for it in items() if it.needed)
