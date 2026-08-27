# 13 — Benchmarking

Until the benchmark runner exists, FFmpeg spike time/resource measurements are committed as notes under `docs/notes/ffmpeg-spike/`. Those notes are testing results, not performance-profile defaults.

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
