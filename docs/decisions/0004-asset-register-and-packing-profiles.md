# 4. Asset register, storage tiers and packing profiles

Date: 2026-10-10

Status: accepted

## Context

Items must name data without paths, and consumers need different parts of the data.

## Decision

The asset register is `muas.assets` of node 1.10.2 DataRepository. Every item names an asset by its ID, never by a path. Storage tiers: inline, embedded, linked. Packing profiles: `aerolink`, `review`, `flight-record`, `archive` (`consumers.py`). Flight events go on 1.8.1.4 FlightTests, firmware on 1.2.9 AirVehicleSoftwareRelease.

## Consequences

A consumer states what it needs. `pack --profile aerolink` refuses an aircraft that lacks an item.
