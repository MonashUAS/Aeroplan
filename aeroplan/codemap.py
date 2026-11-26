"""The code map: one row for each module of the package, made from the first line of its docstring (rule AP015).

`python -m aeroplan codemap` prints it. `CLAUDE.md` holds a copy between the markers `<!-- codemap:start -->` and
`<!-- codemap:end -->`, and a check compares the copy with this output. `python -m aeroplan codemap --write` updates the copy.
Read the map before you add a function: the job you want can have a module already. This module reads the files as text
(ast) and imports no tool package.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Optional

from . import REPO_ROOT

START, END = "<!-- codemap:start -->", "<!-- codemap:end -->"
SKIP = {".venv", "__pycache__", "notebooks", "settings", "data"}


def modules(pkg: Path = REPO_ROOT / "aeroplan") -> List[Path]:
    """Every module of the package, without the tool Pythons, in path order."""
    return sorted(p for p in pkg.rglob("*.py") if not SKIP & set(p.relative_to(pkg).parts))


def summary(path: Path) -> Optional[str]:
    """The first line of the module docstring, or None when the module has none."""
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    return doc.strip().splitlines()[0].strip() if doc and doc.strip() else None


def render(pkg: Path = REPO_ROOT / "aeroplan") -> str:
    """The code map as a Markdown table: module, job. A tool `__init__.py` is left out (it only names its spoke)."""
    rows = ["| Module | Job |", "|---|---|"]
    for p in modules(pkg):
        rel = p.relative_to(pkg)
        if p.name == "__init__.py" and len(rel.parts) > 1:
            continue
        text = (summary(p) or "(no docstring)").replace("|", "\\|")
        rows.append(f"| `{rel.as_posix()}` | {text} |")
    return "\n".join(rows)


def block(text: str) -> Optional[str]:
    """The code map copy inside a Markdown text, or None when the text has no markers."""
    if START not in text or END not in text:
        return None
    return text.split(START, 1)[1].split(END, 1)[0].strip("\n")


def write(md: Path) -> bool:
    """Put the current code map into the file between the markers. True when the file changed."""
    raw = md.read_bytes().decode("utf-8")
    old = block(raw.replace("\r\n", "\n"))
    if old is None:
        raise ValueError(f"{md} has no {START} ... {END} block")
    new = render()
    if old == new:
        return False
    nl = "\r\n" if "\r\n" in raw else "\n"
    head, rest = raw.replace("\r\n", "\n").split(START, 1)
    text = f"{head}{START}\n{new}\n{END}{rest.split(END, 1)[1]}"
    md.write_bytes(text.replace("\n", nl).encode("utf-8"))
    return True
