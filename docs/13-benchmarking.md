# 13 — Benchmarking

The runner is `waveform benchmark dry-run|run MANIFEST.toml`. Spike time/resource measurements remain in `docs/notes/ffmpeg-spike/` as labelled evidence, not performance-profile defaults.

Matrix expansion is **inputs × variants × renderers × performance_profiles**. The manifest `formats` list is attached to every cell (one job may request ProRes and PNG together). Unknown renderers are `UNSUPPORTED`. Missing inputs are `BLOCKED`. Variant overrides are applied to an in-memory preset copy named `preset--variant`; canonical preset files are never written (FR-BENCH-010).

Dry-run reports cell count and SKIP/PROCESS/BLOCKED. When `dry_run_estimates = true` and duration is known, disk estimates are a **labelled** extrapolation from the 1400×280 @ 30 fps spike table. Wall-time estimates are omitted until the runner has its own evidence.

## Two families

### Performance benchmarks

Goal: characterize resource/runtime behavior and derive performance-profile defaults.

Measure where available:

- wall time;
- CPU time/use;
- peak RAM;
- disk I/O;
- temporary disk usage;
- output size;
- render FPS / real-time factor;
- expected vs actual duration;
- timeline drift.

Future GPU metrics: peak VRAM, GPU utilization, GPU processing time.

Throughput (wall time / real-time factor) is a **required** performance target, not an optional extra (`NFR-PERF-005`, `FR-BENCH-016`). Large ProRes can be acceptable within admitted capacity; size does not release baseline/comparison retention holds. Long wall time remains a product concern. Numeric bars (for example a maximum real-time factor on the operator workstation) are adopted only from labelled evidence. See [visual development and retention](23-visual-development-and-retention.md): short benchmark cells do not replace complete per-style s0e00 acceptance renders, and requested matrix expansion is not a mandatory full style/color/track/episode acceptance product.

Historical reported operator evidence (original measurement artifacts unavailable
for current comparison; retained numbers below are not reconstructed results), `iuris-default` ProRes on `s0e00.wav` (~395.7 s source, 23741 frames @ 60 fps, 7×60 s chunks, ~10 GB):

| Date | `jobs` | Wall | Real-time factor | CPU (Task Manager, approx.) | Look |
|---|---|---|---|---|---|
| 2026-08-31 | 1 (unused field) | 12604 s | ~31.9× | single-digit % | on par with 8 s preview |
| 2026-09-09 | 4 (`maximum`) | 4010 s | ~10.1× | ~17% | no visible artifacts at operator glance |

`jobs=4` is ~3.1× faster, still far from using a 20-core host. Further FFmpeg-MVP gains (higher `jobs`, less Python per frame) are in-scope but limited. The custom renderer owns using the machine (`NFR-PERF-006`, `FR-BENCH-017`). GPU waits until default-preset look stays locked and this CPU-parallel evidence is in.

### Visual benchmarks

Goal: compare styles/effects/normalization and tune appearance.

Candidate dimensions:

- style;
- amplitude;
- smoothing;
- normalization;
- soft clipping;
- glow;
- particle motion/interaction/density;
- effect combinations.

## Benchmark manifest

Defines inputs, renderers, visual variants, output formats, and performance profiles/settings. The runner expands the requested Cartesian matrix.

Non-canonical test variants are allowed.

Benchmark execution never silently changes canonical presets.

## Dry-run

Report expanded jobs, expected file count, formats, and—when evidence exists—estimated disk use and time. Estimates must be labelled and omitted when evidence is insufficient.

## Initial performance TODO

Test chunk sizes:

```text
30 / 60 / 120 / 300 seconds
```

Parallel jobs:

```text
1 / 2 / 4 / auto
```

`jobs` now fans out independent scroll-chunk encodes (one process per worker, each drawing RGBA and piping FFmpeg). It does not change intended appearance. First wall-time evidence: `jobs=1` → `jobs=4` on `s0e00` (~3.1×). `auto` is a benchmark-matrix token meaning the runner should also try an automatic worker count. It is not a `jobs` field value in committed performance profiles; those remain positive integers. Legacy fixed-axis spectrum stays single-process. The existing application/script
`field_center_out` path uses its own frame-partition pool when `jobs > 1` and
expected frames >= 1,800; shorter field work is serial. This is not the scroll
chunk/resume contract, nor a generally selectable CLI spectrum feature: field
layout/render-path/AA kwargs are not current CLI flags. `render` accepts
`--performance`; `preview` does not. See [operator limits](../Instructions/runbook.md#known-limits-do-not-treat-as-bugs).

FFmpeg threads:

```text
auto + selected fixed values
```

Durations:

- short diagnostic sample;
- ~30 min;
- ~60 min;
- ~180 min endurance.

Outputs:

- PNG;
- ProRes;
- both.

Complexity:

- base waveform;
- glow;
- more expensive supported combinations.

## Visual corpus

Include quiet/typical/loud speech, transient peaks, long silence, overlapping speech, and tracks with different perceived loudness.

## Dedicated benchmarks

- chunk-boundary torture test;
- resume vs uninterrupted;
- stateful vs overlap vs hybrid;
- output-format fidelity;
- normalization/soft-clipping sweeps.

A tested variant may be explicitly saved as a preset. Benchmark execution itself never mutates presets.


## Measurement semantics (BENCH-001)

Each run creates an exclusive `benchmark-*` invocation directory, then ordinal
`cells/cell-NNNNNN/output` and `work` namespaces. Profiles and duplicate inputs
never share output/recovery state, including across repeated invocations. Dry-run
plans the same cell layout without allocating an invocation. Output signatures,
presets and renderer decisions are unchanged. Analysis cache is independent:
select `EWP_ANALYSIS_CACHE` externally (an empty owned directory for a cold case,
the same populated directory for a warm case). The runner never clears or primes
it and records only observed hit/miss; uninstrumented paths report null.

`action` remains a compatibility alias of `planned_action`. `actual_action` and
`actual_status` describe the runtime result; cells not invoked have `NOT_RUN`
actuals, not a fictional terminal result. `status` retains the legacy plan status
for non-invoked cells. Only planned PROCESS plus actual SUCCEEDED, explicit passed
production validation, nonempty outputs, no reused outputs/resumed chunks and
known positive duration/frame/wall observations qualify as throughput samples.
SKIPPED, failed, unknown, blocked and unvalidated cases have null render FPS/RTF.
`render_fps` is validated output frames / render wall seconds. `real_time_factor`
is render wall seconds / effective clipped audio seconds, never full-source seconds.
PNG output duration is validated frame count / configured FPS; MOV duration is
validated metadata. Drift is output duration minus effective audio duration.
Speedup is null: no comparable paired baseline is collected by this runner.

Cell `wall_seconds` covers the render_job call, including hashing, reuse checks,
production validation, publication and cleanup. Benchmark probing/profile loading
and matrix planning are excluded. `benchmark_wall_seconds` covers invocation setup,
planning/probes/profile loads, all cells, output-size accounting and tool/platform fingerprint collection;
it excludes summary serialization/write. It is not a sum of phase counters.

Phase `seconds`/`counts` retain existing keys. Instrumentation is partial and
non-additive: generator time includes nested visual-field/raster work; blocking
stdin feed/write time is not encoder CPU time and can overlap child encoding.
Wait includes stdin close, drain-thread joins and process wait. Parallel spans
measure parent orchestration, not worker phases; unobserved worker breakdown is
null. Missing phase entries are unobserved, not zero. No frame stream is sampled
or iterated again for telemetry. `rgba_bytes` is a legacy last-feed attempted-byte
key (also used for gray masks); `raw_feed_bytes` sums chunks whose writes returned,
for instrumented parent feeds only, with the input pixel format labelled. It is
not process-tree I/O or a count inferred for uninstrumented workers.

Jobs/threads from profiles are requested settings. `encode_workers_resolved` is
the returned execution partition, not observed CPU utilization. Fingerprint jobs
are resolved field-worker count; fingerprint ffmpeg_threads is the parent-requested
thread setting, not necessarily the worker argument or an observed thread count.
The adapter-selected stream parameter is reported separately from its option role:
for dual PNG+ProRes the existing positive `-threads` is before `-i` and applies to
the input rawvideo decoder, not either output encoder; for a single output it is
after `-i` and applies to that output encoder. Zero omits `-threads` entirely.
`ffmpeg_encoder_threads_argument` is null for dual output or omitted options;
`ffmpeg_decoder_threads_argument` records only a positive dual-output option.
Null arguments do not establish observed defaults. Actual jobs/threads remain
unobserved/null. Command placement is preserved, not corrected/tuned here.

`resources.parent_lifetime_ru_maxrss` is RUSAGE_SELF's parent process-lifetime
high-water sampled after the cell (KiB on Linux, bytes on macOS, otherwise
platform-defined). The deprecated `ru_maxrss_kb` alias is populated only on Linux
and has that same lifetime scope. Neither is a per-cell or process-tree peak;
subtracting high-water marks cannot produce one. Per-cell/tree RSS, parent/child
CPU, normalized utilization, disk I/O and peak workdir bytes are explicitly null,
not collected. No new monitoring platform or performance claim is introduced.


Both-format cells retain per-format validated counts; a disagreement has no common
throughput frame count and suppresses FPS/RTF rather than summing or hiding it.
Production validation tolerances themselves are unchanged. Resolved adapter
parameters do not establish an FFmpeg process/filter thread cap. `nproc` in legacy
fingerprints is os.cpu_count machine metadata, not affinity/quota or utilization.
Output bytes are a post-call traversal of returned paths, including reuse when
present; they are not measured writes or disk I/O. Each invocation also retains
its own benchmark.json; the manifest-named JSON remains the latest-result alias.
