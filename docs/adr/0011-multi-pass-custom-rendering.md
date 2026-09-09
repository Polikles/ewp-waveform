# ADR-0011 — Multi-pass custom rendering target

- **Status:** Accepted
- **Date:** 2026-08-26

## Context
Waveform geometry and effects may need different continuity mechanisms and benchmark matrices. Recomputing base geometry for every effect variant is wasteful.

## Decision
The custom renderer should support independent base/effect passes where useful, followed by canonical composition. FFmpeg may remain monolithic where appropriate.

## Consequences
Architecture must permit pass-level reuse/caching, effect combinations, targeted validation, and component-specific continuity strategies.

The custom renderer is also the throughput path (`NFR-PERF-005`/`006`, `FR-BENCH-017`). The FFmpeg MVP draws frames in Python (GIL) and pipes one FFmpeg stdin per worker; process-pool `jobs` help but leave a many-core host under-used. MVP2 must be designed to use available CPU (threads/SIMD/processes as evidence dictates) and later GPU, without making device or worker count part of visual identity.
