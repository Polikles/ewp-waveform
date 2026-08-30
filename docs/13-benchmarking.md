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

`auto` is a benchmark-matrix token meaning the runner should also try an automatic worker count. It is not a `jobs` field value in committed performance profiles; those remain positive integers.

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
