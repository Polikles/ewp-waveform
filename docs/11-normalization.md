# 11 — Visualization Normalization

## Principle

Never modify source/publication audio. Normalization applies only to decoded analysis data or temporary visualization representations.

## Goals

1. Comparable perceived loudness among tracks in one project should produce comparable visual response.
2. Typical speech across episodes should map to a stable visual range.
3. One isolated transient must not flatten the rest of a long waveform.

## Scopes

### Within-project
Compare related tracks and compensate only when a meaningful perceived-loudness difference exists.

### Across-project reference
Map typical speech to a stable visual target across episodes.

## Candidate metrics

- integrated loudness;
- short-term loudness;
- RMS/envelope statistics;
- percentile amplitude;
- peak;
- optional true peak;
- noise floor;
- silence proportion.

LUFS/EBU-R128-compatible analysis is a baseline candidate, but final visual mapping is project-specific and benchmark-driven.

## Robust scaling

Avoid `single max sample -> global 100% scale`.

Prefer:

```text
audio
 -> envelope
 -> silence-aware robust statistics
 -> percentile/reference
 -> project/reference compensation
 -> soft knee / soft clipping
 -> visual amplitude
```

## Soft clipping

Required in the custom visualization pipeline. Exact curve/threshold remains a benchmark target.

## Modes

Schema target:

```text
none
auto
project
reference
```

`auto` is the intended initial user-facing default.

All relevant measured metrics/resolved decisions should be recorded in results.
