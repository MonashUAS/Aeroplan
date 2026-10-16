# 2. Git holds the source tree, dist holds the package

Date: 2026-10-10

Status: accepted

## Context

A binary package in git gives no useful diff and no review.

## Decision

Git holds the source tree `aircraft/<aircraft>/` (committed). `aeroplan pack` builds the `.muas` package into `dist/` (git ignores it). A package is never edited in place. `aeroplan unpack` gives the source tree back.

## Consequences

Reviews read JSON diffs. The same source tree gives the same package bytes. The first Currawong tree came from the retired HDF5 file `aircraft/currawong.muas` by a one-time script that is not kept.
