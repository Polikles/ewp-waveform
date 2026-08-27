# Work Status

## Current state

Specification baseline accepted.

License: EWP Waveform Community License 1.0.

Development is internal-beta / pre-MVP. There is no chosen release candidate and no public release.

## Next phase

FFmpeg research spike in progress (`docs/21-ffmpeg-baseline-plan.md`).

Synthetic + short speech-cut evidence is in `docs/notes/ffmpeg-spike/` (see `speech.md`). Filled+glow is the FFmpeg baseline; 30 and 60 fps are supported and look different; particles unsupported; naive chunk concat needs preroll; `segmented` stays experimental.

Waiting on: operator visual QA of **speech** renders; DaVinci 30 vs 60 playback; long jobs (s2e9 full, ~2.5 h) **outside this VM**.

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
