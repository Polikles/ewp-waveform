# Changelog

The project follows Semantic Versioning. Development is currently an internal beta / pre-MVP; there is no public release.

## Unreleased

### Added

- Center-out VisualField: 11-slot broadband unimodal core; side spectral lobes scaled to stay under 0.9× the center apex.
- Center-out VisualField uses a 7-slot unimodal core from one shared RMS mix; side bands start outside the core so the center is one apex, not two shoulders.
- Visual pipeline split: AnalysisFrame → static VisualField → filled-ribbon renderer. 65-slot center-out mapping (one visual center). Script: `scripts/spectrum_field_ribbon.py`. Old recentered/fold modes remain.
- Static center-out fold of 64 spectral bands (X slots never move). Temporal-envelope experiment rejected: X must be stationary. Script: `scripts/spectrum_fold_abc.py`.
- Centered temporal-envelope visual experiment (1.5 s RMS / RMS+peak) vs recentered 64-band spectrum. Script: `scripts/spectrum_envelope_abc.py`.
- Spectrum layout experiment: dominant-region recenter + optional edge taper on the 64-band B mapping. Script: `scripts/spectrum_layout_abc.py`.
- Spectrum mapping experiment: 32/64 log-RMS bands, tilt, and compression before the existing contour. Production mapping unchanged. Script: `scripts/spectrum_mapping_abc.py`.
- Spectrum log-Hz spatial-scale experiment: true Gaussian LPF at 1× / 2× / 3.5× current σ, contour raster on. Production still uses 3-box spatial smoothing. Script: `scripts/spectrum_spatial_abc.py`.
- Spectrum contour raster experiment (`draw_spectrum_frame`, PCHIP, no peak overshoot) behind an internal flag; production spectrum stays column raster. A/B script: `scripts/spectrum_contour_ab.py`.
- Wall time and real-time factor are first-class performance requirements (`NFR-PERF-005`, `FR-BENCH-016`). The custom renderer must be designed to use available CPU, and later GPU (`NFR-PERF-006`, `FR-BENCH-017`).
- Scroll chunk encode uses `jobs` as a process pool after the global peak is stored. Concat order is unchanged. `jobs=1` and `jobs=2` PNG sequences match. Spectrum remains a single encode.
- Clip start/duration are part of render identity, so an 8 s preview cannot SKIP a full-file dest.
- Progress lines on stderr during hash/decode/chunk/encode.
- Windows drive paths (`D:\\foo`) map to `/mnt/d/foo` on Linux/WSL.
- `W_OUTPUT_SPACE` when output size cannot be estimated or the estimate is close to free space.
- `timestamps.duration_seconds` on per-job and run summaries.
- Operator install + runbook under `Instructions/` (Ubuntu/WSL2, doctor, SKIP/resume, fresh-VM checklist).
- `waveform doctor` checks writable temp dir, free disk, and the encoders/filters the render path actually uses.
- `waveform benchmark dry-run|run` expands a manifest matrix and records wall time / RSS / output size without mutating canonical presets.
- `waveform preset list|show`, `performance list|show`, richer `dry-run` (signature, dests, SKIP/PROCESS), run-level `run_*_results.json`, and `clean --workdirs`.
- Fixed-axis spectrum (`iuris-spectrum`) uses an application log-Hz span: `auto` from source energy or explicit `fmin_hz`/`fmax_hz`, drawn with mirrored bars. Scroll signatures are unchanged.
- Scroll jobs resume from validated workdir checkpoints: reuse completed chunks, reject stale signatures, emit `W_JOB_RESUMED`.
- Envelope jobs split into 60 s logical chunks with window+FIR preroll and FFmpeg copy-concat of published segments (ADR-0006).
- Equivalent-job SKIP: complete dests with a matching signature are skipped, listed in `outputs`, and re-validated; empty leftovers are rerendered.
- Published MOV/PNG are probed for codec, alpha, size, and frame count before publish.
- First identifiable CLI: `waveform doctor|inspect|capabilities|dry-run|preview|render`.
- Frozen exit codes 0/2/3/4/5/6.
- Scrolling RMS envelope renderer (5 s window, mirrored bars, glow) and experimental `showfreqs` spectrum path.
- Scroll path is translation-only of a frozen envelope (no vertical bounce). Auto-gain so speech fills the canvas.
- Operator-adopted scroll default is `iuris-default` as rendered in `*ad0c99b500c0.mov`: 60 fps, dense RMS (oversample 4), temporal-Nyquist sinc LOD (~0.09 cyc/px), shutter 0, 12× raster, medium glow.
- Initial specification baseline.
- Core documentation and ADR set.
- Draft schemas and TOML examples, including an application config schema.
- Repository governance and traceability rules.
- EWP Waveform Community License 1.0, licensing overview, contributor terms, and notices.
- FFmpeg spike note convention under `docs/notes/ffmpeg-spike/`, including an environment and `lavfi` smoke-test record.
- FFmpeg spike synthetic CPU findings: style/glow capability ratings, chunk warm-up seam, 30 s resource sample.
- Speech-cut spike follow-up; 30 and 60 documented as supported production FPS (`FR-RENDER-013`).
- FFmpeg spike analysis of Iuris et Logos reference boards (style names, speaker colors, 1/2/3-speaker layouts).

### Fixed

- Long FFmpeg stdin encodes no longer deadlock when the child fills a piped stderr (stats). Frame progress is logged every 300 frames.
- Dual PNG+ProRes encode no longer concatenates `flags=area` with `split` (`areasplit`).

### Changed

- `waveform doctor` requires `gblur`/`overlay`/`scale` rather than unused `showwaves`/`showfreqs`.
- Merged engineering workflow and legal contribution rules into `CONTRIBUTING.md`.
- Status documents now treat the license as adopted and describe internal betas rather than a release candidate.
- `FR-CLI-005` includes `capabilities`; `FR-CLI-009` covers `preset`, `performance`, `benchmark`, and `clean`.
- Default look is **mirrored** vertical bars + medium glow @ 30 fps per the brand boards. `lowpass=80` rejected. `iuris-default` style is `mirrored`. FFmpeg cannot draw that geometry faithfully yet.
- Visualization domain: time+scroll (current podcast target), time+playhead (later), frequency fixed-axis (second choosable default, `iuris-spectrum`). `FR-STYLE-004`–`006`.

### Fixed

- None.
