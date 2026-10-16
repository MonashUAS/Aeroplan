# 9. The changed file wins

Date: 2026-10-08

Status: accepted

## Context

Two geometry tools (flow5, OpenVSP) can describe the same item.

## Decision

A geometry spoke writes an item only when its input file differs from the asset that the item names. `muas.geometry_tool` names the spoke that wrote the geometry last.

## Consequences

After an OpenVSP change, the datum table warns that the aero model comes from older geometry until a new flow5 sweep.
