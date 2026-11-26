---
id: "0003"
title: Only small, sourced data goes into the source tree
date: 2026-10-10
status: accepted
kind: data
applies_to: ["aircraft/**", "aeroplan/assets.py"]
---
# 3. Only small, sourced data goes into the source tree

## Context

Large tool files (STL, STEP, `.fl5`, sweep output, logs) make the repository slow and hide the design data.

## Decision

The source tree holds the ADH tree, the asset register, small geometry and lookup tables, and the datasets. Large files stay in `work/<tool>/<aircraft>/` (git ignores `work/`). The register names each one (`asset:sha256:<hash>`, repository path, URL).

## Consequences

A file that is not on this machine does not make a package invalid. A fetch checks the hash.

## Rules

- AP019: No file in `aircraft/` is larger than 1 MB.
- process: A large tool file stays in `work/<tool>/<aircraft>/`. The asset register names it by its hash.
