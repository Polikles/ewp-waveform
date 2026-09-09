# Work Status

## Current state

Specification baseline accepted.

License: EWP Waveform Community License 1.0.

Development is internal-beta / pre-MVP. There is no chosen release candidate and no public release.

## Next phase

FFmpeg MVP **roadmap** is complete (application, CLI, chunk/resume, benchmark, operator runbook). Spike notes remain in `docs/notes/ffmpeg-spike/`. Operator visual QA: full `s0e00.wav` `iuris-default` ProRes looks usable (no artifacts at a glance); `jobs=4` cut wall time 12604 s → 4010 s (~10× realtime, ~17% CPU). Next evidence: `iuris-spectrum` on the same speech source. Episode-length jobs wait until throughput is closer to usable. Wall-time is a requirement (`NFR-PERF-005`); custom renderer owns using the CPU/GPU (`NFR-PERF-006`).

Synthetic + short speech-cut evidence is in `docs/notes/ffmpeg-spike/` (see `speech.md`).

Two choosable visual defaults:

- **time + scroll** — sliding phrase envelope (mirrored line); current podcast target.
- **frequency + fixed axis** — spectrum-like wave, silence flat, vertical motion only; particle field for MVP2.

Playhead envelope is later (scrubber / optional viz).

FFmpeg cannot draw mirrored line faithfully (`showwaves` window wrong). Fixed-axis spectrum is application FFT + log-Hz span (experimental vs brand).

CLI: `doctor`, `inspect`, `capabilities`, `dry-run`, `preview`, `render`, `preset list|show`, `performance list|show`, `clean --workdirs`, `benchmark dry-run|run`.

`render`/`preview` write scrolling RMS envelope (`iuris-default`, limited) or experimental fixed-axis spectrum (`iuris-spectrum`, auto/explicit Hz range). Exit codes frozen in `docs/09`.

Scroll jobs chunk at `chunk_seconds` (default 60) with overlap preroll so concat matches a single-pass preview. After the global peak is stored, `jobs` (default `balanced`=2, `maximum`=4) encodes remaining chunks in parallel processes. Concat stays ordered copy. Equivalent signatures SKIP complete dests and keep `outputs` populated. Failed scroll jobs keep a deterministic workdir and resume from validated `checkpoint.json` (`W_JOB_RESUMED`). Graceful Ctrl+C cancellation is still best-effort (last complete chunk).

Current **scroll look lock** (operator, `*ad0c99b500c0.mov`): 60 fps, 5 s window, `envelope_oversample=4`, `envelope_motion_lpf=sinc` (~0.09 cyc/px), `envelope_aa=area@1`, `shutter_degrees=0`, 12× raster, medium glow. Not a pixel match to brand mirrored line.

Long jobs run on the operator workstation. Labelled `s0e00` throughput is in `docs/13-benchmarking.md` and `docs/notes/ffmpeg-spike/speech.md`.

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
