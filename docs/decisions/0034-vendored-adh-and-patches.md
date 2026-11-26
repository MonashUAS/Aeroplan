---
id: "0034"
title: Vendored ADH and patches
date: 2026-11-26
status: accepted
kind: architecture
applies_to: ["standards/adh/**"]
---
# 34. Vendored ADH and patches

## Context

The rules for the vendored ADH were in `CLAUDE.md` and `standards/README.md`, with no ADR. One rule ("import upstream ADH
inside a function, so the MUAS models load without it") protected nothing: `import aeroplan` builds and loads the patched
ADH on its first run.

## Decision

- `standards/adh/upstream/` stays pristine. `standards/adh/upstream_commit.txt` names the upstream commit.
- A fix goes in a new patch `standards/adh/patches/NNNN-<name>.patch`. `standards/README.md` lists each patch and why.
- A patch must not break an upstream ADH test.
- The rule about the place of an upstream ADH import is removed. Import it where the code needs it.

## Rules

- ci: CI builds the patched ADH and runs the upstream ADH tests on it.
- process: Never edit `standards/adh/upstream/`. A fix is a patch.
