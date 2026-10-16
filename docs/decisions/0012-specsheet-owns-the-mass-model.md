# 12. The Master Specification Sheet owns the mass model

Date: 2026-10-15

Status: accepted

## Context

Weights come from weighing, and the sheet is the record.

## Decision

The Master Specification Sheet owns the mass model. The SpecSheet spoke writes the subassembly masses and the 1.2 roll-up (mass, CG, inertia, point masses). It runs after flow5, so flow5 ingest cannot keep its own mass model. The nominal configuration is the measured aircraft with no payload. Payload layouts are named configurations in the notebooks only. A link to the Google Sheet comes later.

## Consequences

The sheet file is in `tools/specsheet/sheets/<aircraft>/`.
