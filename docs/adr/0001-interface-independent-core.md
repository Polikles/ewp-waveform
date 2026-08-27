# ADR-0001 — Interface-independent application core

- **Status:** Accepted
- **Date:** 2026-08-26

## Context
The project begins as a CLI but is expected to support GUI and orchestration later.

## Decision
CLI is an adapter over a stable application API. Rendering, grouping, normalization, storage, chunking, and backend-specific behavior stay outside CLI.

## Rationale
One application boundary avoids duplicated CLI/GUI behavior and improves testability.

## Consequences
More explicit boundaries initially; less extraction/rewrite later.
