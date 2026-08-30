# 22 — Chunking and Continuity

## Status

Normative continuity contract; specific mechanisms remain benchmark targets.

## Why chunk

Chunking provides bounded memory, recovery, parallelism, resource tuning, and long-duration stability.

Initial default: **60 seconds**, subject to benchmark revision.

## Canonical rule

Chunk size and continuity strategy are execution/performance concerns. They must not intentionally change intended appearance.

## Continuity requirements

No:

- waveform jumps;
- smoothing/glow/particle resets caused by boundaries;
- missing/duplicate frames;
- timing jumps;
- cumulative drift.

Resume satisfies the same contract as uninterrupted processing.

## Logical vs processing window

Overlap may process more context than it publishes.

Illustrative 60 s logical chunks with 15 s context:

```text
logical:
00:00-01:00
01:00-02:00
02:00-03:00

processing:
00:00-01:15 -> publish 00:00-01:00
00:45-02:15 -> publish 01:00-02:00
01:45-03:15 -> publish 02:00-03:00
```

Each canonical output frame is published exactly once. The 15 s context is illustrative, not a default.

## Envelope MVP (overlap + concat)

The FFmpeg scroll path uses overlap, not `showwaves` concat.

- Logical chunks default to **60 seconds** (`performance.processing.chunk_seconds`), partitioned on **canonical frames** so concat neither drops nor duplicates a frame.
- Each chunk decodes a processing window: **preroll** = `window_seconds` + FIR/glow pad, **postroll** = FIR/glow pad. The first chunk clamps preroll to t=0 (same zero-pad as an unchunked job).
- Viewport timing is global. `bins[0]` of a mid-file decode is placed with a bin origin so frame *i* samples the same envelope index as a single-pass render.
- Auto-normalization uses a **global** 95th-percentile peak collected from published regions only. Per-chunk auto-gain is forbidden (it would change bar height at joins).
- Published ProRes segments are copy-concatenated in the FFmpeg adapter. PNG sequences use contiguous `frame_%06d` numbers (`-start_number`).
- Chunk size remains outside visual identity (ADR-0004). Equivalent continuity does not bump `visual_contract_version`.

Spectrum (`showfreqs`) stays a single encode in this slice.

## Resume

Interrupted scroll jobs resume from `checkpoint.json` in the deterministic workdir. Reused segments are the same bytes that passed chunk validation; remaining chunks are encoded with the stored global peak so concat still matches an uninterrupted render. Changing source hash, signature, visual-contract version, clip, or chunk size invalidates the checkpoint.

## Stateful

```text
state_in -> chunk -> state_out
```

Strengths: efficient for temporal filters/physical simulations, little repeated work.

Limits: complex checkpoints/state versioning; sequential dependencies can reduce parallelism.

## Overlap

Each logical chunk receives context before/after.

Strengths: easy parallelism/resume; good for finite-window smoothing/blur/envelope.

Limits: repeated computation; context sizing; poor fit for long-lived state.

## Hybrid

Different passes use different methods.

Example:

```text
waveform smoothing -> overlap
glow -> overlap
physical particles -> stateful
deterministic particles -> absolute-time/overlap
composition -> stateless
```

Strength: flexibility and multi-pass fit. Limit: orchestration/debug complexity.

## Absolute-time deterministic evaluation

Investigate components whose state can derive from:

```text
global seed + component identity + absolute time + audio features
```

This can improve resume, parallelism, and chunk independence.

## Capability declaration

Components may declare:

```text
supports_stateful
supports_overlap
supports_absolute_time
preferred_strategy
minimum_context_before
minimum_context_after
requires_previous_state
```

A multi-pass renderer may use different context per pass.

## Potential expert configuration

Future benchmark/expert mode may expose:

```toml
[rendering]
continuity = "auto"
```

Candidate values:

```text
auto / stateful / overlap / hybrid
```

Production default is expected to be auto/hybrid only after benchmark evidence.

Forced incompatible strategy fails explicitly.

## Identity

Equivalent continuity strategies do not belong to visual identity. If a strategy intentionally changes appearance, it becomes visual algorithm/config and must enter render signature.

## Benchmarks

### Boundary torture
Compare reference with 300/60/10/1 s chunks (or similarly aggressive setting).

### Strategy
Compare stateful/overlap/hybrid for fidelity and CPU/RAM/disk/wall-time/recomputation/parallel scaling.

### Resume
Compare uninterrupted vs interrupted/resumed.

Boundary and resume benchmarks remain separate.
