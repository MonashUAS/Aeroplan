"""AP014 and AP015: the docs and the code map. AP013 (the ADRs) is in test_adrs.py."""
from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from typing import Dict, List

from archlib import ROOT, fail, ratchet

TEXT = (".md", ".py", ".yaml", ".yml", ".json", ".toml", ".txt", ".cfg", ".ipynb")
#: Retired paths and the text that replaces them (ADR 0025, ADR 0036)
RETIRED = {
    r"(?<![\w/.])tools/(aerosandbox|openvsp|specsheet|flow5|ardupilot|creo|daveml|propalyser|aerolink)\b": "aeroplan/<tool>/",
    r"spec/multirotor_contract\.md": "Aerolink `docs/multirotor_contract.md`",
    r"docs/reference/multirotor_contract\.md": "Aerolink `docs/multirotor_contract.md`",
}
#: Files that may name a retired path: the history (old ADRs and reports) keeps its old words
HISTORY = ("docs/decisions/", "docs/reports/", "CHANGELOG")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _tracked() -> List[str]:
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout.split("\n")
    return [f for f in out if f.endswith(TEXT) and (ROOT / f).is_file() and not f.startswith("standards/adh/upstream/")]


def test_ap014_no_merge_conflict_marker():
    bad = []
    for f in _tracked():
        for i, line in enumerate((ROOT / f).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.startswith(("<<<<<<< ", ">>>>>>> ")) or line == "=======":
                bad.append(f"{f}:{i}: {line[:40]}")
    fail("AP014", bad, "resolve the merge: keep the right text and delete the marker lines.")


def test_ap014_every_relative_link_resolves():
    bad = []
    for f in (x for x in _tracked() if x.endswith(".md")):
        text = (ROOT / f).read_text(encoding="utf-8")
        for target in LINK.findall(text):
            path = target.split("#", 1)[0]
            if not path or re.match(r"^[a-z][a-z0-9+.-]*:", path) or path.startswith("/"):
                continue                                    # a URL, a mail address or an anchor in the same file
            if not ((ROOT / f).parent / path).exists():
                bad.append(f"{f}: link to {target} (no such file)")
    fail("AP014", bad, "point the link at the file that exists, or remove the link.")


def test_ap014_no_retired_path_in_a_live_file():
    found: Dict[str, List[str]] = defaultdict(list)
    for f in _tracked():
        if f.startswith(HISTORY) or f == "tests/architecture/test_docs.py":
            continue
        text = (ROOT / f).read_text(encoding="utf-8", errors="replace")
        for pattern, now in RETIRED.items():
            for m in re.finditer(pattern, text):
                line = text.count("\n", 0, m.start()) + 1
                found[f].append(f"line {line}: {m.group(0)} (now {now})")
    ratchet("AP014", found, "write the current path.")


def test_ap015_each_module_has_a_docstring_and_the_code_map_is_current():
    from aeroplan.codemap import block, modules, render, summary

    bad = [f"{p.relative_to(ROOT).as_posix()} has no module docstring" for p in modules() if summary(p) is None]
    copy = block((ROOT / "CLAUDE.md").read_text(encoding="utf-8").replace("\r\n", "\n"))
    if copy is None:
        bad.append("CLAUDE.md has no <!-- codemap:start --> ... <!-- codemap:end --> block")
    elif copy != render():
        bad.append("the code map in CLAUDE.md differs from the module docstrings")
    fail("AP015", bad, "write the module docstring (first line: the job), then run `python -m aeroplan codemap --write`.")
