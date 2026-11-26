---
id: "0031"
title: Rules are code
date: 2026-11-26
status: accepted
kind: architecture
applies_to: ["docs/decisions/**", "tests/architecture/**", "CLAUDE.md", "aeroplan/**"]
---
# 31. Rules are code

## Context

The rules of the repository lived in three places: the ADR text, `CLAUDE.md`, and comments in the code. The three copies
disagreed. A person or an agent obeyed a rule only after it read the right text. Nothing told it which ADR covered a file.

Few rules had a check. A new feature could copy a helper or convert degrees in the core, and no test failed.

## Decision

- Each ADR has YAML front matter: `id`, `title`, `date`, `status` (`accepted` or `superseded`), `kind` (`architecture`,
  `data`, `design` or `process`), the links (`supersedes`, `superseded_by`, `amends`, `amended_by`) and `applies_to`
  (path globs).
- An accepted `architecture` or `data` ADR has a `## Rules` section. Each line is one rule, with its kind:
  - `APnnn:` a check in `tests/architecture/` (CI runs it).
  - `check:` a check of `aeroplan check` or of the code at run time.
  - `ci:` a CI job.
  - `process:` a rule that no check can see.
- An `APnnn` rule lives in one ADR only. Code cites the rule ID or the ADR number.
- `python -m aeroplan rules <path>` prints the rules of each accepted ADR whose `applies_to` matches the path. An agent hook
  gives these rules to the agent before it edits the file.
- `tests/architecture/allowlist.py` holds the violations that exist today, one entry for each file, with the reason. The list
  can only get shorter.
- `CLAUDE.md` holds no rule that a check enforces. Its code map is made from the module docstrings
  (`python -m aeroplan codemap --write`).

## Consequences

A new rule is a new line in an ADR plus a check. A rule with no possible check is a `process` line. The agent hook still
shows it at the right time. `python -m aeroplan rules --index --write` makes the index `docs/decisions/README.md` from the
front matter.

## Rules

- AP013: Each ADR has valid front matter, valid links and rules, and the index matches. Code cites ADRs that exist and are
  accepted.
- AP015: Each module of `aeroplan/` has a docstring and a row in the `CLAUDE.md` code map.
- process: Write prose in ASD-STE100 style.
