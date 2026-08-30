# Work Status

## Current state

Specification baseline accepted.

License: EWP Waveform Community License 1.0.

Development is internal-beta / pre-MVP. There is no chosen release candidate and no public release.

## Next phase

FFmpeg MVP application started. Spike notes remain in `docs/notes/ffmpeg-spike/`.

Synthetic + short speech-cut evidence is in `docs/notes/ffmpeg-spike/` (see `speech.md`).

Two choosable visual defaults:

- **time + scroll** — sliding phrase envelope (linia lustrzana); current podcast target.
- **frequency + fixed axis** — spectrum-like wave, silence flat, vertical motion only; particle field for MVP2.

Playhead envelope is later (scrubber / optional viz).

FFmpeg cannot yet draw either look faithfully (`showwaves` window wrong; `showfreqs` is the right axis but not the product picture).

CLI: `doctor`, `inspect`, `capabilities`, `dry-run`, `preview`, `render`.

`render`/`preview` write scrolling RMS envelope (`iuris-default`, limited) or experimental `showfreqs` (`iuris-spectrum`). Exit codes frozen in `docs/09`.

Current **scroll look lock** (operator, `*ad0c99b500c0.mov`): 60 fps, 5 s window, `envelope_oversample=4`, `envelope_motion_lpf=sinc` (~0.09 cyc/px), `envelope_aa=area@1`, `shutter_degrees=0`, 12× raster, medium glow. Not a pixel match to linia lustrzana.

Long jobs run on the operator workstation.

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
