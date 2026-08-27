# Work Status

## Current state

Specification baseline accepted.

License: EWP Waveform Community License 1.0.

Development is internal-beta / pre-MVP. There is no chosen release candidate and no public release.

## Next phase

FFmpeg research spike in progress (`docs/21-ffmpeg-baseline-plan.md`).

Synthetic CPU evidence is in `docs/notes/ffmpeg-spike/` (`environment.md`, `capability-matrix.md`, `findings.md`). Filled+glow is a usable FFmpeg baseline; particles are unsupported; naive chunk concat has a `showwaves` warm-up seam.

Waiting on: operator visual QA of `local-renders/ffmpeg-spike/`; later podcast samples for speech/long-duration/determinism.

## Deferred pending evidence

- custom renderer stack (MVP2);
- GPU backend;
- final continuity strategy per pass/effect;
- exact overlap windows;
- final normalization thresholds/curve;
- final performance defaults;
- public plugin API;
- browser GUI;
- public release (immediately before Docker).
