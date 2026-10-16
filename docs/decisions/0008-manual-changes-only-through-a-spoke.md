# 8. Manual changes come in through a spoke, by script only

Date: 2026-10-10

Status: accepted

## Context

A hand edit of the source tree has no source and no check.

## Decision

Nobody edits the source tree by hand. Every value names its source through a spoke. A failed check writes nothing.

## Consequences

A path change in the register is also made by code, never by hand.
