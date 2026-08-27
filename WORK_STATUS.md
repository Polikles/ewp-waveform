# Work Status

## Current state

Specification baseline accepted.

License: EWP Waveform Community License 1.0.

Development is internal-beta / pre-MVP. There is no chosen release candidate and no public release.

## Next phase

FFmpeg research spike in progress (`docs/21-ffmpeg-baseline-plan.md`).

Synthetic + short speech-cut evidence is in `docs/notes/ffmpeg-spike/` (see `speech.md`).

FFmpeg MVP default: **filled + glow medium @ 30 fps**. 60 fps is a supported full-detail identity. Particles unsupported; chunk concat needs preroll; `segmented` experimental.

“Too fast” / busy speech motion is **not** a trivial `showwaves` fix; envelope lowpass ~80 Hz is an optional later tweak. Long jobs run on the operator workstation.

Next engineering phase: FFmpeg MVP application (API + thin CLI + this baseline), still CPU.

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
