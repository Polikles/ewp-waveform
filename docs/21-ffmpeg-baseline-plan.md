# 21 — FFmpeg Baseline Plan

## Purpose

Create measured evidence and a usable MVP baseline. Do not force FFmpeg to mimic every later custom effect.

## Spike evidence

Commit testing-result notes under `docs/notes/ffmpeg-spike/`. Notes are reviewable evidence, not specification. Do not commit generated media, workdirs, or private audio.

Record in those notes:

- FFmpeg version/build;
- commands/filter graphs as argument lists;
- alpha/output behavior;
- frame/timing behavior;
- wall time, CPU time, peak RSS, disk/output size, and similar resource measurements;
- maintainability limitations;
- content-free `lavfi` evidence where appropriate, until redistributable samples exist.

Time and resource reports are part of the spike record. They belong in git as notes, not as discarded console logs.

## Targets

### Styles
Evaluate `classic`, `mirrored`, `filled`, `segmented` as:

```text
full / limited / experimental / unsupported
```

### Glow
Evaluate maintainable layered/blurred approaches and alpha edge behavior.

### Particles
Investigate enough to decide whether FFmpeg implementation is maintainable. Do not create a fragile graph just to claim parity.

### Output
Validate ProRes 4444 alpha, PNG RGBA, decode/readback, timing/frame count, and cross-format fidelity.

### Chunking
Determine how FFmpeg can satisfy the canonical chunk/resume contract. Application contract takes precedence over FFmpeg convenience.

### Performance
Measure representative short, ~30 min, ~60 min, and available endurance material; ProRes/PNG/both; selected styles/glow.

## Current evidence

Partial notes (2026-08-27): `docs/notes/ffmpeg-spike/capability-matrix.md`, `findings.md`, `speech.md`. Short speech cuts done. Not complete: DaVinci 30/60 playback, full s2e9 / 2.5 h (off this VM), music sample, GPU.

## Completion questions

1. Which styles are maintainable?
2. Is alpha reliable in reference environment?
3. What are format/effect costs?
4. What continuity limitations exist?
5. Which responsibilities belong in application layer?
6. Which measured limits motivate custom renderer?
