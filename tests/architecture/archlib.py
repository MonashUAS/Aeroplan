"""Shared helpers of the architecture checks (ADR 0031).

Each check has a rule ID (`AP001`...). `RULES` gives the text and the ADR of each rule, read from the `## Rules` section of
the ADRs. A failure message names the rule, its ADR, each file and line, and the fix. `ratchet` compares the violations with `allowlist.py`: a file on the list
may keep its old violations, a file that is not on the list may have none, and a file on the list with no violation left
is a stale entry. So the list can only get shorter.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from aeroplan import REPO_ROOT
from aeroplan.rules import rule_index
from aeroplan.spokes import SPOKES, folder_name

ROOT = REPO_ROOT
PKG = ROOT / "aeroplan"

#: rule ID -> (the rule text, (its ADR,)). The text lives once, in the `## Rules` section of its ADR (ADR 0031).
RULES: Dict[str, Tuple[str, Tuple[str, ...]]] = {k: (text, (adr,)) for k, (text, adr) in rule_index().items()}

TOOLS = tuple(folder_name(s) for s in SPOKES)


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def py_files(*roots: Path) -> Iterator[Path]:
    """Every .py file below the roots, without the tool Pythons (.venv) and caches."""
    for r in roots:
        for p in sorted(r.rglob("*.py")):
            if not {".venv", "__pycache__", "build"} & set(p.relative_to(ROOT).parts):
                yield p


def core_files() -> List[Path]:
    """The core: aeroplan/*.py and every subpackage that is not a tool (aeroplan/muas/)."""
    return [p for p in py_files(PKG) if p.relative_to(PKG).parts[0] not in TOOLS]


def tool_of(path: Path) -> Optional[str]:
    part = path.resolve().relative_to(PKG).parts[0]
    return part if part in TOOLS else None


@functools.lru_cache(maxsize=None)
def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imports(path: Path) -> List[Tuple[str, Optional[str], int]]:
    """(absolute module name, the function that holds the import or None, line) for each import of a file."""
    pkg = path.resolve().relative_to(ROOT).with_suffix("").parts[:-1]  # the package that holds the file
    out: List[Tuple[str, Optional[str], int]] = []

    def absolute(level: int, module: Optional[str]) -> str:
        if not level:
            return module or ""
        base = list(pkg[: len(pkg) - level + 1])
        return ".".join(base + ([module] if module else []))

    def walk(node: ast.AST, fn: Optional[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, child.name)
                continue
            if isinstance(child, ast.Import):
                out.extend((a.name, fn, child.lineno) for a in child.names)
            elif isinstance(child, ast.ImportFrom):
                base = absolute(child.level, child.module)
                out.append((base, fn, child.lineno))
                out.extend((f"{base}.{a.name}", fn, child.lineno) for a in child.names)
            walk(child, fn)

    walk(tree(path), None)
    return out


def fail(rule: str, lines: Iterable[str], fix: str) -> None:
    lines = list(lines)
    if lines:
        title, adrs = RULES.get(rule, ("(no ADR states this rule: AP013 fails)", ()))
        head = f"{rule} ({', '.join('ADR ' + a for a in adrs)}): {title}"
        raise AssertionError("\n".join([head, *("  " + x for x in lines), f"Fix: {fix}"]))


def ratchet(rule: str, found: Dict[str, List[str]], fix: str) -> None:
    """Compare the violations of each file with the allowlist of the rule (see the module docstring)."""
    from allowlist import ALLOW

    allowed = ALLOW.get(rule, {})
    new = [f"{f}: {x}" for f, xs in sorted(found.items()) if f not in allowed for x in xs]
    stale = [f"{f}: on the allowlist of {rule} but has no violation. Remove the entry from "
             f"tests/architecture/allowlist.py." for f in sorted(allowed) if not found.get(f)]
    fail(rule, new + stale, fix)
