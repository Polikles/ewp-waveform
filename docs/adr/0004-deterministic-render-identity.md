# ADR-0004 — Deterministic render identity

- **Status:** Accepted
- **Date:** 2026-08-26

## Context
Batch reruns need reliable SKIP while alternative presets/settings and multiple encoders coexist.

## Decision
Compute deterministic render signature from stable inputs defining intended visual output.

Include source identity, clip start/duration (full file is `clip_duration=null`), normalization context, resolved visual config, seed, FPS, renderer identity, and visual-contract/algorithm versions. A preview interval is a different identity from a full-file render.

Exclude output format/path, chunk size, workers, threads, performance profile, and wall-clock timestamp.

## Consequences
Equivalent completed jobs can be skipped and multiple encoders can share one visual identity.
