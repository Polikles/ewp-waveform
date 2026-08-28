# Work Status

## Current state

Specification baseline accepted.

License: EWP Waveform Community License 1.0.

Development is internal-beta / pre-MVP. There is no chosen release candidate and no public release.

## Next phase

FFmpeg research spike in progress (`docs/21-ffmpeg-baseline-plan.md`).

Synthetic + short speech-cut evidence is in `docs/notes/ffmpeg-spike/` (see `speech.md`).

Brand reference boards analyzed (`docs/notes/ffmpeg-spike/reference.md`). Target default is **linia lustrzana (mirrored bars) + medium glow @ 30 fps**, not a PCM oscilloscope and not lp80 (rejected).

FFmpeg cannot yet draw that geometry. Closest time-scale stand-in is `showwavespic` / a long envelope window. Faithful bars need an envelope-over-window (application or custom renderer).

Long jobs run on the operator workstation. Next: FFmpeg MVP application with honest capability ratings, still CPU.

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
