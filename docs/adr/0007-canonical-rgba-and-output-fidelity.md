# ADR-0007 — Canonical RGBA model and output-format fidelity

- **Status:** Accepted
- **Date:** 2026-08-26

## Decision
Custom rendering conceptually produces canonical RGBA frames before encoding. PNG and ProRes derive from the same intended visual representation.

FFmpeg MVP preserves the same semantic contract even if internally monolithic.

Output format is not visual identity.

## Consequences
Cross-format tests use codec-appropriate visual/alpha/timing tolerances rather than byte equality.
