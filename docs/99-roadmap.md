# 99 — Roadmap

No dates are assigned until evidence supports them.

## Phase 0 — Specification
- [x] Scope/requirements/architecture.
- [x] CLI/config/results baseline.
- [x] ADR baseline.
- [x] Benchmark/continuity baseline.

## Phase 1 — FFmpeg research spike
- [x] waveform capability matrix (synthetic; see `docs/notes/ffmpeg-spike/capability-matrix.md`);
- [x] ProRes alpha (encode path; 10 vs 12-bit probe still open);
- [x] PNG alpha (CFR sequences);
- [x] style approximations (`filled` baseline; `classic`/`mirrored` limited; `segmented` experimental);
- [x] glow (split + `gblur` + overlay; medium σ=8);
- [x] particles feasibility (**unsupported** in FFmpeg);
- [x] timing/drift (CFR frame counts on 3/5/30 s synthetic);
- [x] resource baseline (30 s CPU sample only);
- [x] chunk behavior (frame count OK; visual warm-up seam — preroll required);
- [x] operator visual QA of noise renders (direction OK; noise too thick; chunk seam confirmed);
- [x] short speech cuts (s0e00 / s2e9) for style and glow comparison;
- [x] 30 vs 60 fps encode path on speech (appearance differs; DaVinci playback still operator);
- [ ] operator visual QA of speech renders (fresh WSL VM; see `Instructions/runbook.md`);
- [ ] long-duration (full s2e9 ~50 min, later ~2.5 h) **off this VM**;
- [ ] music/non-speech sample when available.

## Phase 2 — FFmpeg MVP
- [x] application API (doctor/inspect/dry-run/render/preview);
- [x] CLI (thin Typer; exit codes frozen);
- [x] config/preset/performance resolution;
- [x] discovery/grouping;
- [x] inspect/dry-run/render/preview/doctor/capabilities;
- [x] normalization baseline;
- [x] deterministic signature/SKIP/versioning;
- [x] output validation;
- [x] results;
- [x] chunk/checkpoint/resume;
- [x] benchmark runner;
- [x] operator installation/runbook.

## Benchmark TODO
- [ ] chunk 30/60/120/300 s;
- [ ] jobs 1/2/4/auto;
- [ ] FFmpeg thread variants;
- [ ] PNG/ProRes/both;
- [ ] ~30/~60/~180 min inputs;
- [ ] boundary torture;
- [ ] resume;
- [ ] format fidelity;
- [ ] normalization/soft-clipping.

## MVP2 — Custom renderer
- [ ] choose raster/render stack;
- [ ] canonical RGBA;
- [ ] multi-pass waveform/effects;
- [ ] robust scaling;
- [ ] continuity strategy benchmark;
- [ ] absolute-time particles;
- [ ] full style/effect implementation;
- [ ] intermediate pass reuse/cache.

## FFmpeg visual tuning (after MVP baseline)
- [ ] phrase-length **scroll** envelope window (boards: seconds of speech as one shape, not 33 ms PCM);
- [ ] linia lustrzana as vertical mirrored bars (FFmpeg `showwaves` / lp80 are the wrong geometry);
- [x] `lowpass=80` rejected as a default;
- [x] fixed-axis spectrum (`iuris-spectrum`): speech-centered Hz range, vertical-only motion;
- [ ] playhead envelope (full-file + cursor) for optional viz and GUI scrubber;
- [ ] particle collision against the fixed-axis wave (custom renderer, especially music).

## Later
- [ ] GPU feasibility/RTX benchmark;
- [ ] low-resource profiles/minimum hardware;
- [ ] Windows/Apple Silicon;
- [ ] browser GUI;
- [ ] remaining operator functions;
- [ ] public release (internal betas until then; no release candidate until public release approaches);
- [ ] Docker (public release is immediately before the Docker image);
- [ ] auto-generated project manifest;
- [ ] WebM/additional formats;
- [ ] public plugin API;
- [ ] richer preview templates;
- [ ] full operator Instructions;
- [ ] short in-repo example audio + default-preset visualizations for GUI/docs (CC BY-NC-SA excerpts; after renderer testing).

## Governance
- [x] source-available license adopted (EWP Waveform Community License 1.0).
