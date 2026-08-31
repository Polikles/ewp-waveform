# Work Status

## Current state

Specification baseline accepted.

License: EWP Waveform Community License 1.0.

Development is internal-beta / pre-MVP. There is no chosen release candidate and no public release.

## Next phase

FFmpeg MVP **roadmap** is complete (application, CLI, chunk/resume, benchmark, operator runbook). Spike notes remain in `docs/notes/ffmpeg-spike/`. Next evidence: operator visual QA on a fresh WSL VM (`Instructions/runbook.md`) and long jobs off undersized disks.

Synthetic + short speech-cut evidence is in `docs/notes/ffmpeg-spike/` (see `speech.md`).

Two choosable visual defaults:

- **time + scroll** — sliding phrase envelope (mirrored line); current podcast target.
- **frequency + fixed axis** — spectrum-like wave, silence flat, vertical motion only; particle field for MVP2.

Playhead envelope is later (scrubber / optional viz).

FFmpeg cannot draw mirrored line faithfully (`showwaves` window wrong). Fixed-axis spectrum is application FFT + log-Hz span (experimental vs brand).

CLI: `doctor`, `inspect`, `capabilities`, `dry-run`, `preview`, `render`, `preset list|show`, `performance list|show`, `clean --workdirs`, `benchmark dry-run|run`.

`render`/`preview` write scrolling RMS envelope (`iuris-default`, limited) or experimental fixed-axis spectrum (`iuris-spectrum`, auto/explicit Hz range). Exit codes frozen in `docs/09`.

Scroll jobs chunk at `chunk_seconds` (default 60) with overlap preroll so concat matches a single-pass preview. Equivalent signatures SKIP complete dests and keep `outputs` populated. Failed scroll jobs keep a deterministic workdir and resume from validated `checkpoint.json` (`W_JOB_RESUMED`). Graceful Ctrl+C cancellation is still best-effort (last complete chunk).

Current **scroll look lock** (operator, `*ad0c99b500c0.mov`): 60 fps, 5 s window, `envelope_oversample=4`, `envelope_motion_lpf=sinc` (~0.09 cyc/px), `envelope_aa=area@1`, `shutter_degrees=0`, 12× raster, medium glow. Not a pixel match to brand mirrored line.

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
