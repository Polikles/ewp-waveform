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

FFmpeg `showwaves` at output fps is the wrong window (speech looks too fast). `lowpass=80` is **rejected** (sine beads). `showwavespic` of a short clip matches the **time scale** of the boards but still draws a ribbon, not bars.

FFmpeg MVP may ship a limited envelope/`showwavespic`-style stand-in. Faithful linia lustrzana is application envelope + bars (or the custom renderer). Do not silently substitute another style.

Default preset: **`mirrored` + glow medium + 30 fps**, color `#C7E6EC`. 60 fps remains a full-detail identity.

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
