# 3. Only ADH data goes into the source tree

Date: 2026-10-10

Status: accepted

## Context

Large tool files (STL, STEP, `.fl5`, sweep output, logs) make the repository slow and hide the design data.

## Decision

The source tree holds the ADH tree, the asset register, small geometry and lookup tables, and the datasets. Large files stay in `work/<tool>/<aircraft>/` (git ignores `work/`). The register names each one (`asset:sha256:<hash>`, repository path, URL).

## Consequences

A file that is not on this machine does not make a package invalid. A fetch checks the hash.
