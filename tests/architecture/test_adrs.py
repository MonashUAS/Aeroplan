"""AP013: the ADRs are machine-read (ADR 0031). Front matter, links, rules, the index, and the ADR citations in code."""
from __future__ import annotations

import fnmatch
import re
import subprocess

from archlib import PKG, ROOT, fail, py_files, rel

from aeroplan import rules

TESTS = ROOT / "tests"
ADRS = rules.adrs()
BY_ID = {a.id: a for a in ADRS}
INVERSE = {"supersedes": "superseded_by", "superseded_by": "supersedes", "amends": "amended_by", "amended_by": "amends"}
PATH = re.compile(r"`((?:aeroplan|aircraft|docs|standards|tests)/[^`<>*\s]*)`")


def test_ap013_front_matter_and_numbers():
    bad = []
    for a in ADRS:
        name = a.path.name
        if a.id != name[:4]:
            bad.append(f"{name}: id {a.id!r} differs from the file number")
        for key in ("id", "title", "date", "status", "kind"):
            if not a.meta.get(key):
                bad.append(f"{name}: no {key}")
        if a.meta.get("status") not in rules.STATUSES:
            bad.append(f"{name}: status {a.meta.get('status')!r} is not one of {rules.STATUSES}")
        if a.meta.get("kind") not in rules.KINDS:
            bad.append(f"{name}: kind {a.meta.get('kind')!r} is not one of {rules.KINDS}")
        if (a.meta.get("status") == "superseded") != bool(a.links("superseded_by")):
            bad.append(f"{name}: a superseded ADR names its successor in superseded_by, and only a superseded ADR does")
        if not a.body.lstrip().startswith(f"# {int(a.id)}. {a.meta.get('title')}"):
            bad.append(f"{name}: the heading is not '# {int(a.id)}. <title>'")
    numbers = sorted(int(a.id) for a in ADRS if a.id.isdigit())
    gaps = sorted(set(range(1, numbers[-1] + 1)) - set(numbers))
    bad += [f"no ADR {n:04d}: write a stub that names its successor" for n in gaps]
    fail("AP013", bad, "fix the front matter (docs/decisions/README.md lists the keys).")


def test_ap013_links_are_symmetric():
    bad = []
    for a in ADRS:
        for key, back in INVERSE.items():
            for other in a.links(key):
                if other not in BY_ID:
                    bad.append(f"{a.path.name}: {key} names ADR {other}, which does not exist")
                elif a.id not in BY_ID[other].links(back):
                    bad.append(f"{a.path.name}: {key} {other}, but ADR {other} has no {back} {a.id}")
    fail("AP013", bad, "write the link in both ADRs.")


def test_ap013_rules_and_checks_agree():
    used = set()
    for p in (ROOT / "tests" / "architecture").glob("test_*.py"):
        used |= set(re.findall(r'(?:fail|ratchet)\("(AP\d{3})"', p.read_text(encoding="utf-8")))
    stated = {}
    bad = []
    for a in ADRS:
        if a.accepted and a.meta.get("kind") in ("architecture", "data") and not a.rules:
            bad.append(f"{a.path.name}: an accepted {a.meta.get('kind')} ADR has no ## Rules section")
        if a.accepted and a.rules and not a.links("applies_to"):
            bad.append(f"{a.path.name}: has rules but no applies_to")
        for r in a.rules:
            if r.id and a.accepted:
                if r.id in stated:
                    bad.append(f"{r.id} is stated in ADR {stated[r.id]} and in ADR {a.id}: a rule lives in one ADR")
                stated[r.id] = a.id
    bad += [f"{i} has a check but no ADR states it" for i in sorted(used - set(stated))]
    bad += [f"{i} (ADR {stated[i]}) has no check in tests/architecture" for i in sorted(set(stated) - used)]
    fail("AP013", bad, "state each APnnn rule in one ADR, and give it a check that calls fail() or ratchet().")


def _local(path):
    """Git ignores the path: a computer makes it (a .venv, work/), so a fresh clone does not have it."""
    return any(subprocess.run(["git", "check-ignore", "-q", p], cwd=ROOT).returncode == 0 for p in (path, path + "/"))


def test_ap013_applies_to_and_paths_exist():
    tracked = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.split("\n")
    bad = []
    for a in ADRS:
        if not a.accepted:
            continue
        for g in a.links("applies_to"):
            if not any(fnmatch.fnmatch(f, g) or f == g.rstrip("/*") for f in tracked if f):
                bad.append(f"{a.path.name}: applies_to {g!r} matches no file")
        live = "\n".join(s for s in re.split(r"\n(?=## )", a.body) if not s.startswith("## Context"))
        for m in PATH.finditer(live):
            path = m.group(1).rstrip("/.,")
            if live[max(0, m.start() - 9):m.start()] == "Aerolink ":
                continue                                    # a path in the Aerolink repository (ADR 0036)
            if not (ROOT / path).exists() and not _local(path):
                bad.append(f"{a.path.name}: names `{path}`, which does not exist")
    fail("AP013", bad, "fix the path. A path of the history goes in a superseded ADR or in the Context with its old name.")


def test_ap013_the_index_is_current():
    text = (ROOT / "docs" / "decisions" / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    copy = text.split(rules.INDEX_START, 1)[-1].split(rules.INDEX_END, 1)[0].strip("\n")
    fail("AP013", [] if copy == rules.index() else ["docs/decisions/README.md differs from the front matter"],
         "run `python -m aeroplan rules --index --write`.")


def test_ap013_code_cites_accepted_adrs():
    cite = re.compile(r"\bADRs? ?(\d{1,4})\b")
    bad = []
    files = list(py_files(PKG, TESTS)) + sorted(PKG.glob("*/settings/*.yaml")) + sorted(PKG.glob("*/README.md"))
    for p in files:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for n in cite.findall(line):
                a = BY_ID.get(f"{int(n):04d}")
                if a is None:
                    bad.append(f"{rel(p)}:{i} cites ADR {n}, which does not exist")
                elif not a.accepted:
                    bad.append(f"{rel(p)}:{i} cites ADR {n}, which is superseded by {', '.join(a.links('superseded_by'))}")
    fail("AP013", bad, "cite the ADR that holds the rule today.")
