---
id: "0036"
title: Aerolink owns the contract and keeps a hand copy of the reader
date: 2026-11-26
status: accepted
kind: architecture
amends: ["0018"]
applies_to: ["aeroplan/aerolink/**", "aeroplan/package.py", "aeroplan/consumers.py", "aeroplan/multirotor*.py"]
---
# 36. Aerolink owns the contract and keeps a hand copy of the reader

## Context

The multirotor contract was cited at three paths (`docs/multirotor_contract.md`, `docs/reference/multirotor_contract.md`,
`spec/multirotor_contract.md`). None of them is in AeroPlan. ADR 0018 said that Aerolink keeps a hand copy, and `CLAUDE.md`
said that AeroPlan keeps no copy.

## Decision

- Aerolink owns the multirotor contract. AeroPlan keeps no copy.
- Every citation reads: the Aerolink `docs/multirotor_contract.md`.
- Aerolink keeps a hand copy of the package reader (`src/aerolink/muas.py`) and the glTF reader (`visual/cad.py`).
- Copy data by hand between repositories. No symlinks, no cross-repository paths. AeroPlan imports no sibling repository.

## Consequences

The hand copy can drift from the AeroPlan reader. No check finds the drift. A change of the package format or of the
extension version needs a matching change in Aerolink.

## Rules

- AP003: AeroPlan imports no sibling repository. Only the AeroSandbox model files import Proptimiser.
- AP014: Docs have no merge-conflict marker, every relative link resolves, and no live file names a retired path (the old
  contract paths, `tools/<tool>/`).
- process: A change of the package format needs a change of the Aerolink hand copy.
