# ADR-0011 — Multi-pass custom rendering target

- **Status:** Accepted
- **Date:** 2026-08-26

## Context
Waveform geometry and effects may need different continuity mechanisms and benchmark matrices. Recomputing base geometry for every effect variant is wasteful.

## Decision
The custom renderer should support independent base/effect passes where useful, followed by canonical composition. FFmpeg may remain monolithic where appropriate.

## Consequences
Architecture must permit pass-level reuse/caching, effect combinations, targeted validation, and component-specific continuity strategies.
