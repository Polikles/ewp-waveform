# 99 — Roadmap

No dates are assigned until evidence supports them.

## Phase 0 — Specification
- [x] Scope/requirements/architecture.
- [x] CLI/config/results baseline.
- [x] ADR baseline.
- [x] Benchmark/continuity baseline.

## Phase 1 — FFmpeg research spike
- [ ] waveform capability matrix;
- [ ] ProRes alpha;
- [ ] PNG alpha;
- [ ] style approximations;
- [ ] glow;
- [ ] particles feasibility;
- [ ] timing/drift;
- [ ] resource baseline;
- [ ] chunk behavior.

## Phase 2 — FFmpeg MVP
- [ ] application API;
- [ ] CLI;
- [ ] config/preset/performance resolution;
- [ ] discovery/grouping;
- [ ] inspect/dry-run/render/preview/doctor/capabilities;
- [ ] normalization baseline;
- [ ] deterministic signature/SKIP/versioning;
- [ ] output validation;
- [ ] results;
- [ ] chunk/checkpoint/resume;
- [ ] benchmark runner;
- [ ] operator installation/runbook.

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
- [ ] full operator Instructions.

## Governance
- [x] source-available license adopted (EWP Waveform Community License 1.0).
