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
