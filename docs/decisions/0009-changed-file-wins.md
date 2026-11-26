---
id: "0009"
title: The changed file wins
date: 2026-10-08
status: accepted
kind: data
applies_to: ["aeroplan/flow5/**", "aeroplan/openvsp/**"]
---
# 9. The changed file wins

## Context

Two geometry tools (flow5, OpenVSP) can describe the same item.

## Decision

A geometry spoke writes an item only when its input file differs from the asset that the item names. `muas.geometry_tool` names the spoke that wrote the geometry last.

## Consequences

After an OpenVSP change, the datum table warns that the aero model comes from older geometry until a new flow5 sweep.

## Rules

- process: A geometry spoke writes an item only when its input file differs from the asset that the item names.
