---
id: "0002"
title: Git holds the source tree, dist holds the package
date: 2026-10-10
status: accepted
kind: architecture
amended_by: ["0026"]
applies_to: ["aeroplan/package.py", "aeroplan/source_tree.py"]
---
# 2. Git holds the source tree, dist holds the package

## Context

A binary package in git gives no useful diff and no review.

## Decision

Git holds the source tree `aircraft/<aircraft>/` (committed). `aeroplan pack` builds the `.muas` package into `dist/` (git ignores it). A package is never edited in place. `aeroplan unpack` gives the source tree back.

## Consequences

Reviews read JSON diffs. The same source tree gives the same package bytes. The first Currawong tree came from the retired HDF5 file currawong.muas by a one-time script that is not kept.

## Rules

- process: Git holds the source tree. `aeroplan pack` writes the package into `dist/`, and git ignores `dist/`.
- process: Never edit a package in place. `aeroplan unpack` gives the source tree back.
