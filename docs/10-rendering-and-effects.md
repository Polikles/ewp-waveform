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

Current development and acceptance sequence:
[baseline, optimize, refine; independent comparison and retention](23-visual-development-and-retention.md).
Broad look acceptance is not complete fidelity of every variant. The reference
yellow/preset discrepancy remains unresolved; no color is canonicalized here.

Initial registry:

- `classic`
- `mirrored`
- `filled`
- `segmented`

Styles define the primary waveform representation. The style interface must be extensible enough for custom geometry, envelope mapping, and rendering logic.

Brand boards (`docs/notes/ffmpeg-spike/reference.md`) define the four styles as **phrase-length amplitude shapes**, not a 33 ms PCM oscilloscope:

- `classic` — thin vertical ticks (classic line), low glow. In time+scroll, alternating bars at 25% opacity replace fully empty gaps by default to reduce motion strobing while retaining the jagged silhouette. `signal.classic_alternate_opacity` or the application API override may select another value from 0 to 1.
- `mirrored` — vertical mirrored bars (mirrored line), medium glow; **default on 1/2/3-speaker templates**.
- `filled` — smooth ribbon (filled ribbon), higher glow.
- `segmented` — discrete columns (segmented impulse), medium glow.

FFmpeg `showwaves` at output fps is the wrong window. `lowpass=80` is **rejected**.

FFmpeg MVP **time+scroll** path (limited): decode to workdir WAV, high-resolution RMS (`envelope_oversample` default **4**). A light reconstruction `area` @ 1 px, then a **temporal-Nyquist sinc** on amplitude-vs-X (`envelope_motion_lpf`, cutoff `fps/(2*velocity)*0.85` ≈ 0.09 cyc/px at 1400/5s/60). That removes 1–4 px needles that cannot be shown stably at 4.67 px/frame, without blurring the rasterized edge. 12× crisp raster, area downsample, glow under the base. Shutter is **0** while this geometry LOD is evaluated. `signal.smoothing` stays 0. Peak half-height is computed from canvas minus `gblur` spread. Not a pixel match to brand mirrored line.

Default production identity is **60 fps**. At 1400×280 / 5 s that is ~4.7 px/frame. 30 fps (~9.3 px/frame) remains supported but is not expected to look as smooth at this scroll speed; do not “fix” 30 fps judder by quantizing or extra-smoothing the scroll position. Do not use `tmix` / full-travel motion blur.

Vertical-only motion belongs to **frequency+fixed-axis**, not to the scrolling envelope.

FFmpeg MVP **frequency+fixed-axis** path (experimental): application FFT mapped onto a log-Hz axis, then mirrored draw/encode. Production still uses per-pixel magnitude lerp, column rasterization (`draw_envelope_frame`), and a 3-box spatial blur at `width/200`. **X is stationary:** each horizontal slot is a fixed mix of analysis bands; only Y amplitude animates. A scrolling temporal window is rejected.

Target architecture: **AnalysisFrame** → static **VisualField** → style geometry → **RenderPlan** → effects/encoder. RenderPlan picks MASK_FAST (coverage + downstream color) or RGBA_2D (general/reference) from required capabilities, not from the style name alone. Monochrome filled ribbon, mirrored bars, and segmented impulse cells with glow use MASK_FAST; particles/gradients fall back to RGBA_2D. Glow/particles stay downstream. Old recentered and even/odd fold outputs remain reference modes. New center-out field: 65 slots, one visual center (`scripts/spectrum_field_ribbon.py`). Default mirrored-line combo (thin 5 px, gap 7 px, alternating `#C7E6EC`/`#6E7BA7`, 2 px center stroke): `scripts/spectrum_field_mirrored.py`. Classic ticks (thin, sparse, low glow): `scripts/spectrum_field_classic.py`. Segmented impulse clips a stationary two-dimensional cell grid by the same smooth centered contour, preserving the base shape instead of reverting to the legacy linear spectrum mapping. Other bar combinations stay selectable. Ribbon raster defaults to 2× supersample (`RIBBON_SUPERSAMPLE`); scroll stays 12×. Analysis is a clip-length `AnalysisSequence` (NumPy `rfft`, PCM loaded once).

`signal.frequency.range = "auto"` fits a span around source energy so typical speech sits near the log-midpoint; explicit `fmin_hz` / `fmax_hz` override. Stock `showfreqs` is no longer the encode path (this FFmpeg build has no `fmin`/`fmax` zoom). Not a pixel match to the brand spectrum.

Default preset **`iuris-default`** (locked to operator pick `*ad0c99b500c0.mov`): mirrored, glow medium, 60 fps, 5 s window, oversample 4, motion sinc LOD, shutter 0, color `#C7E6EC`.

## Opt-in fixed-axis filled-ribbon variant

`iuris-ribbon-fixed` selects the existing `filled` geometry on the optimized
AnalysisFrame -> stationary center-out VisualField -> continuous contour -> glow ->
encoder path. It uses one existing pale-cyan color, `#C7E6EC`, and high glow. No spaced
bars, segmented cells, moving time window or horizontal scrolling are introduced. The
65-slot mapping has one broadband-organized central apex and independent side detail;
it is a visual band mix, **not** a monotonically increasing Hz axis. X weights never
follow framewise energy. Vertical contour halves are mirrored around the fixed baseline.
The reference's large variant-3 panel motivates the continuous fill and rounded lobes;
its dark board background, labels and speaker-composition thumbnails are not rendered.
A still reference proves neither motion nor alpha.

Selection is explicit, for example a bounded diagnostic (replace the example paths):

```bash
waveform preview /path/to/input.wav --preset iuris-ribbon-fixed \
  --start 25 --duration 8 --output-dir /path/to/unique-preview
```

The preset/profile name, effective appearance recipe, canvas, signal, color and effects
remain in render identity/results. MASK_FAST is eligible because the ribbon is
monochrome with alternating bars explicitly disabled; the existing RGBA_2D reference
path and physical supersampling remain selectable. No raster algorithm, encoder,
worker scheduling, dependency, legacy fixture or existing preset is changed.

Tests cover opt-in/invalid selection, legacy recipe preservation, fixed midpoint,
read-only planning, interval-sensitive output, SKIP, source immutability, repeatability,
high-glow mask/RGBA equivalence, worker-boundary equality, PNG/decoded-ProRes alpha and
silent/active response. These are technical gates, not appearance acceptance. Keep all
short diagnostics outside Git and evidence bundles, preserve baseline/download holds,
and apply [23](23-visual-development-and-retention.md) before any complete render.
The variant remains experimental pending independent operator comparison and Resolve
import/playback/compositing review. Transparent content, codec metadata, full-s0e00
acceptance and NLE acceptance are separate claims; no full render is implied here.

## Effects

Effects are separate from styles. Initial families:

- glow;
- particles.

Future examples include blur, shadow, trails, pulse, and gradients.

Multiple effects should be composable.

## Registries

The four built-in style identifiers and their defaults are reserved and immutable. Overrides operate on resolved copies. Configuration-only custom styles are saved visual-preset variants: they keep a built-in geometry identifier, receive a distinct preset name, and store user-selected color, opacity, glow, spacing, and similar settings without changing the built-in definition. New executable geometry implementations are a separate later extension and cannot replace a built-in identifier.

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


Fixed-axis appearance controls are resolved before output identity/reuse, not
only before drawing. The effective versioned recipe is part of frequency render
signatures and results, including SKIP. This intentionally changes prior
frequency/default signatures to avoid reusing old outputs of unknown appearance;
time-scroll identities and raster contract v13 are unchanged. See ADR-0004 for
the migration, inactive-control and representation/AA boundaries.
