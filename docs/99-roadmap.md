# 99 — Roadmap

No dates are assigned until evidence supports them.

## Current navigation — 0.2.1 exact ribbon finishing

The internal MVP has been accepted; delivery is checkout + uv / Python
>=3.12,<3.13 / system FFmpeg, not a public release or qualified deployment image.
[Installation recipe](../Instructions/install.md) and
[future host QA](../Instructions/runbook.md#future-checkouthost-qa-checklist-not-a-qualification-result)
separate documented steps from completed host qualification.

Version 0.2.1 preserves opt-in refined ribbon mapping7, separate Moving mouth
revision4, selectable appearance/noise/idle controls, reflection/independent
horizon and dark/light-background foreground modes, with production appearance
regressions and alpha-aware output/viewing guidance. The ribbon-only row-support
guard preserves exact horizon arithmetic and lum interpolation while avoiding
coverage work on nonintersecting rows; production performance qualification is
separate. Legacy defaults are unchanged.
See [current scope and bounded operator feedback](../WORK_STATUS.md#current-implementation-and-next-work).
Intermediate pending/rejected ribbon prose below and in the development-chain
changelog is dated history, not the final selected mapping7 source.

Missing-foundation interpretations of the older MVP2/field checklist below are
superseded: AnalysisFrame, VisualField, canonical RGBA/raster paths and locked
style regression fixtures already exist. The field-center-out path has a process
pool for `jobs > 1` and >=1,800 expected frames; legacy CLI spectrum stays serial.
Ordinary preset/CLI delivery, measured optimization and separately deferred
features remain work, not grounds to rebuild these foundations. Historical
unchecked visual-review/research items below are not automatically marked done.
Earlier reported throughput remains historical; original measurements are not
available for a fresh performance comparison. Reuse the retained local visual
reference; this documentation update does not regenerate it or qualify new looks.

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
- [x] operator visual QA of the four fixed-axis style candidates on Damian (`s0e00`, 8 s); accepted as the current smooth baseline;
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
- [ ] optimize the active scroll and fixed-axis pipelines against an adopted wall-time/real-time-factor target without changing the approved visual baselines;
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
- [x] operator-approved smooth fixed-axis baseline for `classic`, `mirrored`, `filled`, and centered `segmented` on Damian;
- [x] classic time-scroll alternating-bar opacity selected at 0.25;
- [x] commit small redistributable regression fixtures for the approved built-in style defaults;
- [ ] provide both smooth and more jagged variants of the four main style silhouettes, tuning the jagged variants toward `warianty wizualizacji.png`; ignore the three `układ przestrzenny` composition examples;
- [ ] add style opacity controls: mirrored horizontal center bar, filled lower half, and alternating classic bars;
- [ ] after built-in baselines are regression-locked and the active render pipeline is optimized, allow users to save named visual-preset variants of built-in geometries with custom color, opacity, glow, spacing, and related settings; never mutate built-in presets or style defaults;
- [ ] phrase-length **scroll** envelope window (boards: seconds of speech as one shape, not 33 ms PCM);
- [ ] mirrored line as vertical mirrored bars (FFmpeg `showwaves` / lp80 are the wrong geometry);
- [x] `lowpass=80` rejected as a default;
- [x] fixed-axis spectrum (`iuris-spectrum`): speech-centered Hz range, vertical-only motion;
- [x] spectrum contour vs column raster A/B (`draw_spectrum_frame`; contour kept, difference too small);
- [x] spectrum log-Hz Gaussian spatial scale A/B/C (operator: 3.5× contour is smooth enough);
- [x] spectrum mapping 32/64 log-RMS bands + tilt/compression (operator: B is the new baseline);
- [x] spectrum horizontal layout recenter + taper A/B/C (operator: B recentered 64-band is spectrum baseline);
- [x] centered temporal RMS envelope vs recentered spectrum (**rejected**: X must be stationary);
- [x] static center-out 64-band fold vs recentered spectrum (kept as regression);
- [ ] AnalysisFrame → VisualField (65-slot center-out) filled ribbon vs old fold (operator visual);
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
- [ ] optional executable custom-geometry extension API, separate from configuration-only saved preset variants and unable to replace built-in geometry identifiers;
- [ ] richer preview templates;
- [ ] full operator Instructions;
- [ ] short in-repo example audio + default-preset visualizations for GUI/docs (CC BY-NC-SA excerpts; after renderer testing).

## Governance
- [x] source-available license adopted (EWP Waveform Community License 1.0).


## Maintained style collection

The four requested reference variants remain classic line, mirrored line, filled
ribbon (variant3), and segmented impulse. Moving mouth is an ADDITIONAL style,
not a replacement for any of those four. `iuris-moving-mouth` / `moving-mouth-v1`
preserves revision4 activity-driven behavior, positively accepted for the supplied
short look only; full-style/full-episode, Resolve/NLE and performance qualification
remain open for Moving mouth. `iuris-ribbon-refined` now selects mapping7; bounded
2026-11-11 feedback covers both full MP4 viewing copies and the transparent MOV
inspected in Resolve, not separate assessment of both masters or exhaustive
qualification. Historical revision6/revision7 pending prose preserves earlier
checkpoints; see current scope above. No plugin framework or duplicate
analysis/raster/encoder pipeline is introduced.


## Proposed styles and speaker annotations — future only

Propose a separately selectable **Mexican wave** style: stronger audio moves the
center then propagates smoothly outward. This is distinct from ribbon and Moving
mouth; it is not implemented or an existing control.

Propose **Monowave**: one dominant wave centered horizontally, with smaller waves
arranged symmetrically on both sides and a user-selectable number of side waves.
It may use an appearance similar to the current filled ribbon, including compatible
finishing effects. Implementation, visual trials and optimization are deferred.
Defaults, numerical limits, whether counts mean pairs/per-side/total, and detailed
motion mapping belong to the later design task. No public preset, CLI selector,
schema option or implementation is supplied by this proposal.

Propose optional visualization of speakers WITHIN ONE input track, with an initial
user speaker count1–3 and genuine speaker-timeline annotations. Two centers1/4,3/4;
proposed three1/6,1/2,5/6 are PENDING operator confirmation. Frequency/timbre is not
reliable speaker identity. A future external annotation interface should avoid
duplicating diarization. Identity ambiguity, overlapping speech, annotation
format/tooling, missing intervals and conflict handling remain design work. Default
one-track/one-asset behavior stays unchanged. No diarization model/dependency,
placeholder CLI or implemented multi-speaker capability is supplied.


## Output delivery and manuals — future only

- [ ] Preserve transparent MOV masters and offer optional, correctly composited
  opaque MP4 companions, including regeneration from an existing master without
  audio re-analysis or waveform rendering. Automatic companion export is planned,
  not a current application/CLI capability. The current [external FFmpeg workflow](
  08-output-formats.md#full-master-mov-to-mp4-viewing-copies-external-ffmpeg-workflow)
  is a separate manual conversion, not implementation of this backlog item.
- [ ] Develop full user manuals later as separate CLI and GUI versions. Do not
  interpret this item or the focused conversion recipe as an existing GUI or new
  CLI command/option.

The next separate product task is profiling the accepted mapping7 ribbon pipeline
from freshly fetched current integrated main to identify substantial optimization
opportunities while preserving the accepted look and retention holds. Profiling,
optimization and any choice of a Rust/native rewrite are not started or selected
by this integration; no performance claim is made.
