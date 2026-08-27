# ADR-0008 — Source audio is immutable

- **Status:** Accepted
- **Date:** 2026-08-26

## Decision
Never overwrite or normalize source media. Analysis/visualization normalization uses streams or temporary workdir data.

## Consequences
Source SHA-256 must remain stable; integration tests verify immutability.
