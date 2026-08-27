# ADR-0005 — Output layout and signature-based collision handling

- **Status:** Accepted
- **Date:** 2026-08-26

## Decision
Default root is `<source-directory>/waveform-output/`; project groups use subdirectories.

Names include input stem, preset identity where applicable, and a short render-signature component.

Timestamps are not the primary collision mechanism because they break deterministic SKIP.

`--force` creates `_v002`, `_v003`, etc.

## Consequences
Multiple visual variants coexist while equivalent reruns remain detectable.
