# ADR-0010 — Plugin-ready architecture without public plugin loading in MVP

- **Status:** Accepted
- **Date:** 2026-08-26

## Decision
Use internal registries/protocols for renderers, styles, effects, and encoders. Do not load arbitrary third-party Python plugins in MVP.

## Rationale
Extensibility is needed now; stable compatibility/packaging/security contracts are not.

## Consequences
A public plugin system can be added after internal interfaces stabilize.
