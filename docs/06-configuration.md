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
