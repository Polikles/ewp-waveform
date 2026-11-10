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

## Refined opt-in ribbon

`iuris-ribbon-refined` adds the validated controls documented in
[configuration](06-configuration.md#refined-ribbon-controls-fr-look-controls-001).
### Speech activity mapping (WF-LOOK-ACTIVITY-01)

The refined ribbon communicates overall speech/audio activity, **not faithful
frequency position**. Its configuration retains the existing frequency-analysis
container for compatibility; X is a fixed designed visual coordinate, not Hz.
Mapping revision 4 multiplies the existing broadband level (analysis-frame overall
level, otherwise band RMS) by a deterministic, midpoint-organized, gently asymmetric
multi-scale carrier across 65 stationary slots. Spatial ribs are fixed design,
not fabricated temporal activity. No peak ordering/tracking, centroid translation,
horizontal panning or random animation is used; exact symmetry/centroid is not a gate.

64-band fine/coarse mixtures retain useful audio-derived detail. The normalized
shape residual is bounded to +/-24% of the carrier, so weak individual bands cannot
independently flatten large speech-active regions. Only this residual uses a causal
exponential weighted finite history: 0.24-second response, 0.60-second maximum
lookback (inclusive endpoint), truncated and renormalized at the clip start. Current
broadband height is not delayed by that shape response; the existing overall 0.06s
EMA remains unchanged. This is not calming solely by spatial blur or delaying all
response. Silence supplies zero current carrier amplitude, leaving the stable thin
baseline after the existing short EMA release, with no ongoing decorative motion.

Shape calmness is fixed in this recipe and independent of selectable detail; no new
public control is introduced. Smooth/balanced/detailed still choose spectral
neighborhood/contrast and spatial filtering, not the shape time constant. Keep
balanced provisional default and both balanced/detailed available. Color, glow,
amplitude and baseline thickness controls remain unchanged. PCHIP, raster, alpha,
normalization and worker scheduling retain their existing contracts. Peak scan,
serial frames and pooled column preparation evaluate the same random-access
finite-context mapping; no mutable mapping history can leak across chunk order.
A separately requested clip initializes its own bounded history, as it does its
existing overall EMA/normalization; it is not promised pixel-identical to an
arbitrary full-render crop without the required analysis/EMA context.

### Preserved centering history (WF-LOOK-FIXED-CENTER-01)

Revision 3's monotone band ordering removed radial splitting but its actual short
speech previews remained left-weighted and received REQUEST_CHANGES. A spectral
midpoint did **not** establish the requested compositional midpoint; that attempt
is not an accepted completed centering prerequisite. Earlier balanced AND detailed
contour feedback was bounded positive feedback, not exclusive preference or final
motion acceptance. Revision 4 implements the separately clarified activity target;
short diagnostics, independent review, operator motion/NLE acceptance, full-style
production and main integration remain separate. No acceptance is asserted here.

The effective mapping revision is in output/reuse identity, so revision-3 media
cannot be reused as revision-4 output. V1/legacy appearance, recipes, defaults,
performance profiles and product version are unchanged. Preserve original and
candidate media under the retention rules in [23](23-visual-development-and-retention.md).

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


### Filled ribbon revision6 — independent horizontal regions

`iuris-ribbon-refined` / `filled-ribbon-v2` now has mapping revision6, distinct
from the preserved revision4 `iuris-moving-mouth` / `moving-mouth-v1`. Previous
revision4 activity documentation above describes the historical Moving mouth
behavior, not the current filled-ribbon mapping. Neither style duplicates the
shared analysis/raster/encoder pipeline.

Seven overlapping Gaussian RMS features span the existing64 processed log bands
(feature sigma=0.105*band_count). Each absolute feature and broadband level is
causally averaged with0.18s exponential decay through inclusive ceil(0.60*fps)
lookback, truncated/renormalized at clip start. Fixed lobe centers in65-slot
coordinates are[-26,-17,-8,0,8,17,26], with fixed feature order[5,2,0,1,3,6,4].
This places low speech features around the midpoint, without peak sorting or
translation. It is a stable designed arrangement, not exact frequency fidelity.

For averaged broadband B and local feature F, r=F/(B+F). Local lobe strength is
0.22B+0.78*(2B*r), width=3.1*(0.70+0.60*r). Gaussian lobes overlap and are summed without
pointwise overlap normalization, retaining valleys between fixed lobe centers.
A19-slot Gaussian edge-tapered
footprint multiplies(0.16B+0.84*local). Different feature strengths and widths can
therefore rise/broaden/narrow/settle separately; narrow-band weakness cannot erase
a broad region because features overlap and minority broadband floors remain.
Current activity only gates release with min(1,current/(0.35B)); it is NOT the
dominant instantaneous common multiplier during active speech. Current zero
activity yields zero new field; existing0.06s contour EMA settles to baseline.

The existing detail descriptor, mixed fine/coarse normalized spectral neighborhoods
and contrast, is separately averaged over the same finite response and contributes
the unchanged +/-24% residual. This is a new regional-envelope/width mapping, not
a larger deformation limit. Balanced/detailed use their documented separate
neighborhood/contrast/spatial settings. Color/glow/amplitude/thickness/detail
remain selectable and identity-bound; no new control or performance-profile change.

Composition and motion metrics are descriptive. Shared strong-syllable response
is allowed, but persistent lockstep is not intended. Full-style/full-episode,
operator visual reference3 acceptance, Resolve/NLE and performance qualification
remain open. Independent clips have their own analysis/normalization/history;
indexed evaluation with sufficient finite context is deterministic, not a promise
of arbitrary full-render-crop pixel identity.

The first bounded revision5 short comparison is retained as an intermediate:
its broad nominal lobes plus pointwise overlap division largely erased lobe
valleys, despite non-proportional regional envelopes. The second/last focused
visual iteration (revision6) removes that flattening division and narrows nominal
lobes. It does not increase +/-24% detail deformation or change Moving mouth.
No numerical peak count is a perceptual acceptance threshold; final operator
continuous-motion assessment remains required.


## Amplitude field ribbon (mapping revision 7)

`iuris-ribbon-refined` / `filled-ribbon-v2` is a designed speech-activity
amplitude contour, NOT faithful frequency-to-position or speaker identification.
It replaces revision6's seven broad correlated regions with129 fixed slots and21
irregular stationary wavelets. Normalized local spectral texture, finite0.24s
causal response (inclusive0.60s support), nonlinear local contrast and variable
widths form peaks/valleys across the width. Current broadband gates speech rhythm;
weak narrow bands cannot erase broad framing. Centers do not pan, sort or track.
Balanced/detailed remain selectable and distinct. Common contour smoothing, raster,
color/glow/height/thickness and execution pipeline are reused. This is an intentional
visual model/identity change, not a coefficient-only refinement or optimization.

Saved `[signal]` settings and matching service keyword / CLI controls (dry-run, render,
preview) are `visual_noise` / `--visual-noise` (finite0..1, default0),
`idle_activity` / `--idle-activity` (finite0..0.15, default0), `noise_rate` /
`--noise-rate` (finite0.1..3 lattice intervals/second, default0.8), and
`noise_seed` / `--noise-seed` (integer0..2147483647, default0). Booleans/nonfinite
values are rejected; incompatible profiles reject even explicit zero controls.
Explicit overrides beat saved settings; all resolved values are retained in effective
preset and recipe/reuse identity, including inactive rate/seed for reproducibility.
Legacy presets/defaults and Moving mouth do not acquire these settings.

Noise is intentional artistic modulation, not measured audio. C2 temporal value
noise with locally correlated channels changes useful wavelet heights AND widths,
not edge jitter; fixed seed+absolute input audio seconds determine it without
mutable RNG/worker state. Modest proposed setting: visual_noise0.35, rate0.8,
seed1729; detailed uses the same modulation with finer audio texture. This is a
proposal for operator assessment, not subjective acceptance. Amount0 removes artistic
speech modulation. Idle0 preserves genuine quiet baseline; idle0.035 adds an
intentional gentle animated floor even in silence independently of visual_noise.
Idle is added AFTER speech auto-normalization so a quiet-only clip cannot amplify
it into loud-looking activity. It is not detected speech, diarization or an audio edit.

The noise clock uses clip audio start + canonical frame index/fps, never wall clock
or chunk-local zero. This guarantees the noise phase for equal absolute timestamps,
NOT universal crop/full visual equivalence: analysis span, clip normalization,
finite context/startup and contour EMA retain documented clip-context limitations.
Moving mouth remains exact revision4 with its historical limited short acceptance;
new ribbon appearance, full-style/full-episode and NLE review remain separate.


## Filled-ribbon reflection and independent horizon (appearance revision 1)

Mapping revision7, analysis, motion/noise, normalization, columns and spatial layout
are unchanged. Filled-ribbon-v2 alone adds these `[waveform]` / service / CLI controls:

| Saved/service | CLI | Range | Provisional default |
|---|---|---|---|
| reflection_opacity | --reflection-opacity | finite0..1 | .45 |
| center_line | --center-line / --no-center-line | strict boolean | true |
| stroke_width | --stroke-width | finite1..12 final output pixels | 1 |
| center_line_extent | --center-line-extent | finite0..1 centered frame-width fraction | .96 |
| center_line_opacity | --center-line-opacity | finite0..1 | .55 |

`stroke_width` already meant full baseline thickness in final output pixels; it
retains that meaning, not contour width. There is no second horizon thickness or
enable control. Filled ribbon now draws that one horizon after body/halo finishing,
not as a minimum-ribbon core plus another line. Disabling `center_line` removes it
entirely, including in silence with thick saved stroke. Explicit false and zero
overrides win over saved values (`None` alone means no override). Extent0 or opacity0
also yields no horizon; inactive values remain in effective metadata/reuse identity.

Opacity attenuates actual lower body AND halo alpha after glow, not RGB against black.
Upper geometry/alpha does not depend on reflection. Reflection0 removes lower pixels
but does not remove a separately enabled horizon. Reflection1 is neutral attenuation.
The body mask uses existing AA and native FFmpeg mask union/glow/compositing, then
constant unassociated RGB is assigned wherever alpha is nonzero (zero elsewhere).
This also avoids colored halo fringes from blurring straight RGB against zero.
The center raster row belongs to the shared seam; lower reflection starts one row
below it. A fractional-width line uses analytic final-pixel coverage and no line glow.
True zero columns with horizon off are fully transparent and valid.

The provisional defaults are visual proposals from inspecting main reference panel3:
luminous pale-cyan upper ribbon, weaker lower reflection and a very fine nearly
full-width centered horizon. No numeric opacity was measured from the reference.
Uniform opacity does not reproduce its tint variation/edge taper; no gradient or
tint framework is implemented. Other style defaults and Moving mouth are unchanged;
new reflection/extent/opacity settings and public center-line overrides reject on
unsupported profiles even at zero/false, rather than silently ignoring them.
Saved legacy center_line retains its existing semantics.


## Filled-ribbon foreground appearance modes

`filled-ribbon-v2` / `iuris-ribbon-refined` adds saved `[waveform]` fields,
matching service keywords and `dry-run` / `render` / `preview` options:

- `background_mode` / `--background-mode`: `dark-background` or `light-background`.
- `color_mode` / `--color-mode`: `auto` or `custom`.

These select FOREGROUND appearance only. Production MOV and canonical PNG stay
transparent. The standard preset explicitly sets `dark-background` + `auto`:
bright existing `pale_cyan` / `#C7E6EC`. Selecting `light-background` on that
preset actually resolves existing dark `slate_teal` / `#2F474F`. Body, halo and
horizon share the resolved color. No independent halo/horizon tint is supported;
semantic validation still rejects mismatched saved halo colors. Geometry, motion,
detail/noise, reflection alpha and line extent/thickness/opacity are unchanged.

Explicit non-None service/CLI mode overrides beat saved modes. An explicit
`waveform_color` / `--waveform-color` (brand name or #RRGGBB) selects `custom`,
including an explicitly selected stock cyan. In custom mode, switching background
mode preserves that color exactly: no inference from RGB or color equality.
`color_mode=auto` resets a saved custom color to the mode's brand default; supplying
both explicit waveform_color and color_mode=auto is an error, not ignored intent.
`color_mode=custom` alone freezes the currently saved/resolved color. To save a
custom TOML preset, set color_mode="custom" and matching waveform.color/glow.color.
Old saved filled-ribbon presets lacking mode fields use dark-background + custom
to preserve their explicit colors; the stock preset's auto policy is explicit.
Other profiles reject these new modes (even dark-background/auto); legacy and
Moving mouth defaults stay unchanged. Both selections and effective RGB are retained
in effective metadata, recipe and reuse identity, even where pixels coincide.

Example foreground choice (not a composition background):

```bash
waveform preview /path/to/input.wav --preset iuris-ribbon-refined \
  --background-mode light-background --start 25 --duration 8
```

Only inspection copies may be composited on dark/light backgrounds; do not bake
those backgrounds into canonical assets. A decorative waveform has no imposed
text-accessibility contrast threshold. Full-source assessment/NLE acceptance is
separate from compact still checks and technical gates.
