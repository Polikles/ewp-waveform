# 10 — Rendering and Effects

## Model

```text
audio
 -> analysis/features
 -> base waveform representation
 -> effects
 -> canonical composition
 -> encoders
```

## Visualization domain

Two choosable defaults (part of visual identity):

| Domain | X axis | Motion | Default use |
|---|---|---|---|
| `time` + `scroll` | recent envelope window (phrase-length) | shape slides as speech proceeds | podcast episode asset (**current target**) |
| `time` + `playhead` | whole file envelope | shape static, cursor moves | later viz + GUI scrubber |
| `frequency` + fixed axis | frequency (low → high) | vertical only; silence is a flat line | second choosable default; particle field |

Styles (`classic` / `mirrored` / `filled` / `segmented`) describe **how amplitude is drawn**. Domain describes **what the horizontal axis means**.

Frequency span: `auto` (from typical energy in the source or project) or explicit `fmin_hz` / `fmax_hz`. Speech should land near the middle of the axis.

FFmpeg `showfreqs` is the same *idea* (fixed X = frequency) but is not the product look yet (energy hugs the left/bottom unless heavily tuned). Custom renderer owns a faithful mirrored spectrum wave and particle collision.

## Styles

Initial registry:

- `classic`
- `mirrored`
- `filled`
- `segmented`

Styles define the primary waveform representation. The style interface must be extensible enough for custom geometry, envelope mapping, and rendering logic.

Brand boards (`docs/notes/ffmpeg-spike/reference.md`) define the four styles as **phrase-length amplitude shapes**, not a 33 ms PCM oscilloscope:

- `classic` — thin vertical ticks (linia klasyczna), low glow.
- `mirrored` — vertical mirrored bars (linia lustrzana), medium glow; **default on 1/2/3-speaker templates**.
- `filled` — smooth ribbon (wstęga wypełniona), higher glow.
- `segmented` — discrete columns (impuls segmentowy), medium glow.

FFmpeg `showwaves` at output fps is the wrong window. `lowpass=80` is **rejected**.

FFmpeg MVP **time+scroll** path (limited): decode to workdir WAV, RMS envelope with `window_seconds` (default 5). Bins are frozen, then the window **translates horizontally only** (right edge = now). Auto-normalization fills typical speech to the canvas (preset `amplitude`, default 0.95). Mirrored bars + optional glow. Not a pixel match to linia lustrzana.

Vertical-only motion belongs to **frequency+fixed-axis**, not to the scrolling envelope.

FFmpeg MVP **frequency+fixed-axis** path (experimental): `showfreqs` + mirror. Idea confirmed; look not product-final.

Default preset: **`mirrored` + glow medium + 30 fps + `window_seconds=5`**, color `#C7E6EC`.

## Effects

Effects are separate from styles. Initial families:

- glow;
- particles.

Future examples include blur, shadow, trails, pulse, and gradients.

Multiple effects should be composable.

## Registries

Internal registries should cover:

- renderers;
- styles;
- effects;
- encoders.

MVP is plugin-ready but does not load arbitrary third-party code.

## Capabilities

A renderer should report whether a style/effect/output/continuity mode is full, limited, experimental, or unsupported.

Unsupported requested behavior must not be silently ignored.

## FFmpeg

FFmpeg is a baseline/permanent alternate renderer. It may remain monolithic when filter-graph execution makes separate passes impractical.

## Custom multi-pass target

```text
analysis
  +--> base waveform pass
  +--> glow pass
  +--> particle pass
  +--> other effect passes
            |
            v
        compositor
            |
            v
      canonical RGBA
```

This supports:

- effect recomputation without always recalculating base geometry;
- reusing a stable waveform while testing particle variants;
- effect combinations;
- per-pass continuity strategies;
- intermediate caching;
- focused regression/benchmark tests.

## Particles

Motion models may include:

```text
float, fall, rain, rise, radial, reactive
```

Interaction models may include:

```text
none, waveform-reactive, amplitude-reactive
```

A component may declare continuity requirements such as stateful/overlap/absolute-time support and minimum context.

See `22-chunking-and-continuity.md`.

## Identity boundary

If changing a rendering algorithm intentionally changes appearance, the algorithm/config belongs to visual render identity.

If two strategies are contractually equivalent within tolerance, strategy is execution metadata only.
