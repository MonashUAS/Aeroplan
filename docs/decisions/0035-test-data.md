---
id: "0035"
title: Test data
date: 2026-11-26
status: accepted
kind: data
applies_to: ["tests/**"]
---
# 35. Test data

## Context

`CLAUDE.md` said "tests use synthetic numbers only", with no check. Some tests read committed aircraft data and settings.
A change of the data then broke a test of the code.

## Decision

- A test of the code uses synthetic numbers that it makes itself (in the test, a fixture or `tmp_path`).
- `tests/test_aircraft_files.py` is the one test file that reads the committed data. It runs every check, the pack and the
  unpack on each source tree, and checks the committed tool settings.

## Rules

- AP012: Tests read no committed aircraft data. The exception is `tests/test_aircraft_files.py`.
