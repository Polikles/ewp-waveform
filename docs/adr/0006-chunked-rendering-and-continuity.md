# ADR-0006 — Chunked rendering and temporal continuity

- **Status:** Accepted
- **Date:** 2026-08-26

## Context
Long inputs need bounded-resource processing and recovery without visual seams.

## Decision
Chunking is part of the canonical processing model. Initial default is 60 seconds and benchmark-tunable.

Required:
- absolute timeline preservation;
- each canonical frame published exactly once;
- no visible/effect/timing discontinuity;
- resume meets the same continuity contract;
- chunk/performance strategy does not intentionally define appearance.

Mechanism may be stateful, overlap, absolute-time, hybrid, or another evidence-backed method.

## Consequences
Specific strategy remains a benchmark/design target. See `../22-chunking-and-continuity.md`.
