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
