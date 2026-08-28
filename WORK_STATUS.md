# Work Status

## Current state

Specification baseline accepted.

License: EWP Waveform Community License 1.0.

Development is internal-beta / pre-MVP. There is no chosen release candidate and no public release.

## Next phase

FFmpeg research spike in progress (`docs/21-ffmpeg-baseline-plan.md`).

Synthetic + short speech-cut evidence is in `docs/notes/ffmpeg-spike/` (see `speech.md`).

Two choosable visual defaults:

- **time + scroll** — sliding phrase envelope (linia lustrzana); current podcast target.
- **frequency + fixed axis** — spectrum-like wave, silence flat, vertical motion only; particle field for MVP2.

Playhead envelope is later (scrubber / optional viz).

FFmpeg cannot yet draw either look faithfully (`showwaves` window wrong; `showfreqs` is the right axis but not the product picture).

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
