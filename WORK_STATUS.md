# Work Status

## Current state

Specification baseline accepted.

License: EWP Waveform Community License 1.0.

The operator accepted the internal MVP at 0.1.0; current development version is
0.1.3 with compatible render-pipeline refactoring, gapless raster batching and
benchmark corrections, alongside production PNG/ProRes validation corrections,
read-only planning and corrected operator guidance. Delivery remains
checkout + uv / Python >=3.12,<3.13 / system FFmpeg. No release candidate or public
release, clean-host qualification, wheel, Docker, native Windows or GPU support
is claimed. See [Instructions/install.md](Instructions/install.md).

## Current implementation and next work

Current [visual-development and retention requirements](docs/23-visual-development-and-retention.md)
separate accepted broad looks from full four-variant fidelity, intentional visual
evolution from structural equivalence, and short diagnostics from complete per-style
s0e00 acceptance assets. Historical throughput/visual claims below retain their
original scope, not new performance or operator-review results. No renderer or
benchmark implementation is part of this documentation reconciliation.

FFmpeg MVP **roadmap** is complete (application, CLI, chunk/resume, benchmark, operator runbook). Spike notes remain in `docs/notes/ffmpeg-spike/`. Operator visual QA: full `s0e00.wav` `iuris-default` ProRes looks usable (no artifacts at a glance); `jobs=4` cut wall time 12604 s → 4010 s (~10× realtime, ~17% CPU). That historical next-evidence suggestion is superseded: locked fixed-axis style
fixtures and the AnalysisFrame/VisualField/raster foundation now exist. Ordinary
preset/CLI delivery of script/API-only field controls remains backlog work. Episode-length jobs wait until throughput is closer to usable. Wall-time is a requirement (`NFR-PERF-005`); custom renderer owns using the CPU/GPU (`NFR-PERF-006`).

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

Long jobs run on the operator workstation. Historical reported `s0e00` throughput (not freshly comparable; original measurements unavailable) is in `docs/13-benchmarking.md` and `docs/notes/ffmpeg-spike/speech.md`.

The current field-center-out application path has conditional parallel encode
(`jobs > 1`, at least 1,800 expected frames). Legacy CLI `iuris-spectrum` remains
serial; CLI has no field-layout/render-path/AA selector. Scroll retains its
chunk process pool. Clip flags belong to `preview` and `dry-run`, not `render`.
Do not replace these implemented foundations as if they were missing; remaining
product delivery and measured optimization are separate work.

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
