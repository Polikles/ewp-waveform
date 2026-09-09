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
- [x] operator visual QA of speech renders (fresh WSL VM; `s0e00.wav` full `iuris-default` ProRes: look on par with 8 s preview, no artifacts at operator glance; see `docs/notes/ffmpeg-spike/speech.md`);
- [ ] operator visual QA of `iuris-spectrum` on the same speech source;
- [ ] long-duration (full s2e9 ~50 min, later ~2.5 h) **after throughput is closer to usable** (~10× realtime still implies many hours);
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
- [x] scroll chunk encode uses `jobs` as a process pool (`balanced`=2, `maximum`=4);
- [x] jobs 1 vs 4 wall-time on `s0e00` (12604 s → 4010 s, ~3.1×, ~17% CPU);
- [ ] jobs 1/2/4/8/auto wall-time matrix (same identity);
- [ ] wall-time / real-time-factor target adopted from evidence (`FR-BENCH-016`, `NFR-PERF-005`);
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
- [ ] design for available CPU (threads/SIMD/processes); FFmpeg MVP may stay under-used (`NFR-PERF-006`);
- [ ] continuity strategy benchmark;
- [ ] absolute-time particles;
- [ ] full style/effect implementation;
- [ ] intermediate pass reuse/cache;
- [ ] throughput benchmark vs FFmpeg MVP on the same identity (`FR-BENCH-017`) before GPU.

## FFmpeg visual tuning (after MVP baseline)
- [ ] phrase-length **scroll** envelope window (boards: seconds of speech as one shape, not 33 ms PCM);
- [ ] mirrored line as vertical mirrored bars (FFmpeg `showwaves` / lp80 are the wrong geometry);
- [x] `lowpass=80` rejected as a default;
- [x] fixed-axis spectrum (`iuris-spectrum`): speech-centered Hz range, vertical-only motion;
- [x] spectrum contour vs column raster A/B (`draw_spectrum_frame`; contour kept, difference too small);
- [ ] spectrum log-Hz Gaussian spatial scale A/B/C (1× / 2× / 3.5×; operator visual);
- [ ] playhead envelope (full-file + cursor) for optional viz and GUI scrubber;
- [ ] particle collision against the fixed-axis wave (custom renderer, especially music).

## Later
- [ ] GPU feasibility/RTX 3090 benchmark (after default-preset look stays locked, CPU `jobs` evidence is in, and custom-renderer CPU throughput is measured);
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
