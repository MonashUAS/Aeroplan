# 26. A flat aircraft folder

Date: 2026-10-30

Status: accepted. Amends ADR 2 (the form of the source tree).

## Context

A source tree had three parts: `aircraft.yaml` (name, kind, consumers), `adh/` (one file for each node) and `datasets/`.
The name in `aircraft.yaml` repeated the folder name. The folder `adh/` held every file of the tree but the datasets.

## Decision

```
aircraft/<aircraft>/
  1.0.aircraft_system.json   the root node, with muas.package (kind, consumers)
  <wbs>.<key>.json           one file for each other node
  datasets/<name>.json       one file for each dataset
```

- The folder name is the aircraft name.
- `muas.package` is a fact of the source tree, not of the ADH document. `source_tree.read` moves it to `Aircraft.info`, and the
  package keeps it in its manifest, as before. The package format does not change.
- One file for each node stays, for small git diffs and merges.
- The reader refuses a file in the folder that is not a node file or a dataset.

## Consequences

The four trees moved by `git mv` and one read and write through `source_tree`. The node files kept their content and their
history. `source_tree.exists` and `source_tree.list_aircraft` find a tree.
