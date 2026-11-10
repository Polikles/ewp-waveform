# 06 — Configuration

## Separate domains

1. **Application Config** — discovery/output/workdir defaults.
2. **Visual Preset** — style/color/FPS/signal/effects.
3. **Performance Profile** — chunks/workers/threads/workdir persistence.
4. **Preview Template** — non-canonical test composition.
5. **Benchmark Manifest** — automated experiment matrix.

A future project manifest is separate and deferred.

## Format

Human-editable configuration: TOML. Canonical result data: JSON.

Application config is validated against `schemas/config.schema.json`. Visual presets, performance profiles, preview templates, benchmark manifests, and results have their own schemas under `schemas/`.

## Precedence

```text
built-in defaults
 -> user application config
 -> explicit application config
 -> performance profile
 -> visual preset
 -> project/job-derived context
 -> CLI overrides
```

Only compatible domains override the same setting.

## Preset lookup

```text
explicit path > project > user > built-in
```

Same-name presets may coexist.

Built-ins are immutable. User/project overrides can shadow them.

## Saved visual variants

A saved custom style in the configuration sense is a named visual-preset variant that
reuses a built-in waveform geometry with user-selected settings such as color,
opacity, glow, and spacing. Saving a variant creates a new preset with a distinct
name; it never edits or replaces the built-in preset or its style defaults.

Executable geometry extensions are a separate later feature. They are not required
for saving configuration-only variants.

## Opt-in fixed-axis filled ribbon

`iuris-ribbon-fixed` is a distinct experimental visual preset. Select it explicitly;
application defaults, `iuris-default`, `iuris-spectrum`, and all existing style defaults
remain unchanged. Presentation (`frequency` + stationary center-out field), geometry
(`filled` ribbon), theme (high glow), and color (existing pale cyan `#C7E6EC`) are separate
choices, not a new performance profile or a replacement of the built-in `filled` style.

Its `signal.fixed_axis_profile = "filled-ribbon-v1"` selects a named visual bundle:
64 analysis bands, 65 stationary center-out slots, +3 dB/octave tilt, 0.75 compression,
Gaussian spatial filtering at the existing width/200 scale when smoothing is enabled,
and a monochrome continuous filled contour. The preset sets 0.15-second temporal
smoothing, amplitude 0.82, a center line and high glow. Color, amplitude, smoothing and
glow can be saved in a distinct preset copy; the profile owns the band/layout/shape
bundle, taking precedence over lower-level spectrum shaping arguments. Existing render
path, AA and supersampling controls retain their identity/equivalence semantics.

Unknown profile values and incompatible domain/style fail validation; profile requests
for temporal geometry, another field geometry, another non-default layout or alternating
bars fail rather than silently selecting an unrelated look. Omitting the profile retains
legacy resolution, including the old field path's inherited alternating-bar fallback.
No schema-version or product-version bump is implied by this opt-in variant.

## Refined ribbon controls (FR-LOOK-CONTROLS-001)

`iuris-ribbon-refined` / `signal.fixed_axis_profile="filled-ribbon-v2"` is a NEW
opt-in selection. `iuris-ribbon-fixed` / `filled-ribbon-v1` and all legacy presets,
recipes and defaults are unchanged and reproducible. The v1 bundle still owns its
historical lower-level shaping parameters; it is not the configurable refined profile.

| Control | TOML | Service / CLI | Refined default | Supported values |
|---|---|---|---|---|
| Detail | `signal.detail_level` | `detail_level` / `--detail-level` | `balanced` | `smooth`, `balanced`, `detailed` |
| Color | `waveform.color` | existing `waveform_color` / `--waveform-color` | `#C7E6EC` | TOML `#RRGGBB`; API/CLI also accept five names below |
| Glow | `effects.glow.level` + matching `enabled` | existing `glow_level` / `--glow-level` | `high`, enabled | `none`, `low`, `medium`, `high` (sigma 0/4/8/16 px) |
| Height | `waveform.amplitude` | `amplitude` / `--amplitude` | `0.82` | finite `0.01..1.0`, fraction of glow-safe half-height |
| Baseline thickness | existing `waveform.stroke_width` | `stroke_width` / `--stroke-width` | `1.0` px | finite `1..12` output px; requires `center_line=true` |

The five existing brand names resolve without changing old palettes:
`steel_blue=#3D5D73`, `periwinkle_blue=#6E7BA7`, `slate_teal=#2F474F`,
`pale_cyan=#C7E6EC`, `soft_yellow=#F2C558`. Yellow remains UNRESOLVED against the
reference `#F2C55B`; this increment deliberately retains the existing preset value.
Glow follows waveform color; a separate glow color/radius/intensity is not supported
by the existing encoder and is rejected for v2, not a second ignored control.
For v2, a supplied `effects.glow.color` must exactly match `waveform.color`
(including letter case); omission follows the waveform color. This cross-property
equality for arbitrary colors is semantic runtime validation by `VisualPreset`,
not enforced by standard JSON Schema. Schema validation alone is not sufficient:
validate saved presets through the public configuration model before planning.
The v2 schema and runtime both require six-digit `#RRGGBB` waveform color; legacy
color semantics remain unchanged.

For v2, `signal.frequency` supports `range="auto"` with either no explicit Hz
bounds (automatic span) or **both** `fmin_hz` and `fmax_hz` (explicit span). Each
bound must be finite `0.01..192000` Hz and the minimum must be less than the
maximum. A lone bound is rejected before planning instead of silently discarded.
Legacy frequency admission and the spectrum consumer are unchanged.

Thickness is a minimum full ribbon height at the baseline, independent of amplitude;
1 px retains the thin centerline, thicker values fill a solid core. It is not an
outline stroke. Centerline can be disabled only with no explicit thickness.

Precedence: explicit non-None service/CLI values > TOML preset values > documented
refined defaults. Overrides operate on validated private copies, never built-ins.
Both `plan_jobs` and `render` accept the same five overrides; CLI `dry-run`, `preview`
and `render` use these APIs. New detail/height/thickness API overrides apply only to
v2; legacy appearance stays configurable with existing TOML presets. No new GUI.
Color/glow reuse the existing public service names. Config model validation applies
to saved presets too, including unknown nested fields on v2. Unsupported low-level
spectrum/bar/temporal overrides fail clearly instead of being hidden by the profile.
Existing render path, AA and supersampling remain independent validated controls.

`signal.smoothing` remains a separate explicit temporal EMA (v2 default 0.06 s,
finite 0..0.5). Detail changes static band-neighborhood mixing, amplitude contrast and
Gaussian spatial support, not this user value or color/glow/height/thickness. All
levels use the SAME 64 audio bands, 65 slots, +3 dB/octave tilt and compression 1.
PCHIP interpolation has no overshoot. Smooth uses broader neighborhoods and more
coarse mixing; detailed retains narrower local peaks/deeper valleys; balanced is the
proposed starting point, not an operator-accepted preferred look. Shape differences
are audio-derived, without decorative noise. Profile/detail/mapping revision, effective
recipe, waveform and effects participate in output/reuse identity and resolved results.

Example bounded comparison (use authorized local paths):

```bash
waveform preview input.wav --preset iuris-ribbon-refined --start 25 --duration 8 \
  --detail-level detailed --waveform-color pale_cyan --glow-level high \
  --amplitude 0.82 --stroke-width 1 --output-dir unique-preview
```

## No inheritance

Preset inheritance (`extends`) is intentionally excluded from MVP for simplicity, portability, and predictable backup behavior.

## Import/export/reset

- validate before expensive work;
- backup export should be self-contained/resolved;
- writes are atomic;
- no silent overwrite;
- reset removes override and reveals immutable built-in.

## Auditability

Results store the fully resolved effective configuration, not only the preset name.


## Moving mouth — preserved activity style

`iuris-moving-mouth` selects `signal.fixed_axis_profile="moving-mouth-v1"`.
This additional style freezes revision-4 activity behavior: 65 stationary slots,
the designed broad carrier with fixed multiscale ribs, immediate current processed
band-RMS broadband height, and at most +/-24% local spectral deformation. The
shape descriptor uses a causal exponential0.24s decay with inclusive ceil(0.60*fps)
lookback; the separate existing contour EMA defaults to0.06s. Silence produces
zero new field and settles to the thin baseline. It is not a faithful Hz plot.

It shares analysis, interpolation, raster, glow and encoding, not a second
pipeline. Its concrete mapping and detail constants are independent from the
evolving filled ribbon. It supports the same validated smooth/balanced/detailed,
color, glow, amplitude and baseline thickness controls as refined ribbon; defaults
are1400x280/60fps,pale cyan#C7E6EC,high glow,amplitude0.82,thickness1,balanced.
The new profile/preset has a distinct identity even where pixels equal the
historical refined revision4. Historical previews keep their original names.

The operator positively accepted only the supplied short effect as Moving mouth.
This is NOT filled-ribbon reference3 acceptance, full-episode, Resolve/NLE or
performance qualification. Fine detail can remain restrained; lobes intentionally
share the strong common activity pulse. Other effective appearance changes are
identity-bound as for refined ribbon. Legacy/v1 presets are unchanged.


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
