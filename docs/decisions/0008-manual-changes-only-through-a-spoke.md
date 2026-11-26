---
id: "0008"
title: Manual changes come in through a spoke, by script only
date: 2026-10-10
status: accepted
kind: data
applies_to: ["aircraft/**", "aeroplan/source_tree.py", "aeroplan/build.py", "aeroplan/*/spoke.py"]
---
# 8. Manual changes come in through a spoke, by script only

## Context

A hand edit of the source tree has no source and no check.

## Decision

Nobody edits the source tree by hand. Every value names its source through a spoke. A failed check writes nothing.

## Consequences

A path change in the register is also made by code, never by hand.

## Rules

- AP009: Only `source_tree.py` makes a path into `aircraft/` (`source_tree.aircraft_dir`).
- process: Nobody edits the source tree by hand. Only spokes and code write it.
- process: A one-time migration is a script that reads and writes the tree through `source_tree`. Commit it with the data change, delete it in the next commit, and name the commit in the ADR.
