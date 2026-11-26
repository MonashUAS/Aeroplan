"""The rules of the repository, read from the ADRs in docs/decisions/ (ADR 0031): front matter, `## Rules`, the index.

`python -m aeroplan rules <path>` prints the rules that apply to a file. `python -m aeroplan rules --index --write` makes
`docs/decisions/README.md` from the front matter. The architecture checks (`tests/architecture/`) take their rule titles
from here, so each rule is written once, in its ADR.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import REPO_ROOT

DECISIONS = REPO_ROOT / "docs" / "decisions"
STATUSES = ("accepted", "superseded")
KINDS = ("architecture", "data", "design", "process")
LINKS = ("supersedes", "superseded_by", "amends", "amended_by")
RULE_KINDS = ("check", "ci", "process")
_RULE = re.compile(r"^- (AP\d{3}|check|ci|process): (.+)$")


@dataclass
class Rule:
    kind: str                 # APnnn, check, ci or process
    text: str
    adr: str

    @property
    def id(self) -> Optional[str]:
        return self.kind if self.kind.startswith("AP") else None


@dataclass
class Adr:
    path: Path
    meta: Dict[str, object]
    body: str
    rules: List[Rule] = field(default_factory=list)

    @property
    def id(self) -> str:
        return str(self.meta.get("id"))

    @property
    def accepted(self) -> bool:
        return self.meta.get("status") == "accepted"

    def links(self, key: str) -> List[str]:
        return [str(x) for x in self.meta.get(key) or []]

    def applies_to(self, rel: str) -> bool:
        return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(rel, g.rstrip("/*")) for g in self.links("applies_to"))


def parse(path: Path) -> Adr:
    """One ADR file: the YAML front matter, the body and the lines of its `## Rules` section."""
    import yaml

    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: no YAML front matter")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as err:
        raise ValueError(f"{path.name}: the front matter is not valid YAML: {err}") from err
    body = text[m.end():]
    adr = Adr(path, meta, body)
    section = body.split("\n## Rules\n", 1)
    if len(section) == 2:
        lines = section[1].split("\n## ", 1)[0]
        for item in re.split(r"\n(?=- )", lines.strip()):
            item = " ".join(x.strip() for x in item.splitlines())
            r = _RULE.match(item)
            if not r:
                raise ValueError(f"{path.name}: the rule line {item[:60]!r} has no kind (APnnn, check, ci, process)")
            adr.rules.append(Rule(r.group(1), r.group(2), adr.id))
    return adr


def adrs(folder: Path = DECISIONS) -> List[Adr]:
    return [parse(p) for p in sorted(folder.glob("[0-9][0-9][0-9][0-9]-*.md"))]


def rule_index(folder: Path = DECISIONS) -> Dict[str, Tuple[str, str]]:
    """APnnn -> (the rule text, the ADR that holds it)."""
    return {r.id: (r.text, r.adr) for a in adrs(folder) if a.accepted for r in a.rules if r.id}


def rules_for(path: str, root: Path = REPO_ROOT) -> List[Tuple[Adr, Rule]]:
    """The rules of each accepted ADR whose `applies_to` matches the path (repository-relative or absolute)."""
    p = Path(path)
    rel = (p.resolve().relative_to(root.resolve()) if p.is_absolute() else p).as_posix()
    return [(a, r) for a in adrs(root / "docs" / "decisions") if a.accepted and a.applies_to(rel) for r in a.rules]


def text_for(path: str) -> str:
    """The rules for a path as plain text, for a person or an agent hook."""
    found = rules_for(path)
    if not found:
        return f"No ADR rule names {path}."
    lines = [f"Rules for {path} (docs/decisions):"]
    for adr, rule in found:
        lines.append(f"- [{rule.kind}] {rule.text} (ADR {adr.id})")
    return "\n".join(lines)


INDEX_START, INDEX_END = "<!-- index:start -->", "<!-- index:end -->"


def index(folder: Path = DECISIONS) -> str:
    """The Markdown table of the ADRs, made from the front matter."""
    rows = ["| ADR | Date | Status | Kind | Decision |", "|---|---|---|---|---|"]
    for a in adrs(folder):
        status = str(a.meta.get("status"))
        notes = [f"{k.replace('_', ' ')} {', '.join(a.links(k))}" for k in LINKS if a.links(k)]
        if notes:
            status += " (" + "; ".join(notes) + ")"
        rows.append(f"| [{a.id}]({a.path.name}) | {a.meta.get('date')} | {status} | {a.meta.get('kind')} | {a.meta.get('title')} |")
    return "\n".join(rows)


def write_index(folder: Path = DECISIONS) -> bool:
    """Put the current index into README.md between the markers. True when the file changed."""
    md = folder / "README.md"
    text = md.read_text(encoding="utf-8").replace("\r\n", "\n")
    head, rest = text.split(INDEX_START, 1)
    old, tail = rest.split(INDEX_END, 1)
    new = f"{head}{INDEX_START}\n{index(folder)}\n{INDEX_END}{tail}"
    if new == text:
        return False
    md.write_text(new, encoding="utf-8", newline="\n")
    return True
