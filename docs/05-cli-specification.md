# 05 — CLI Specification

## Executable

Preferred: `waveform`.

The README lists core operator commands. This document is the full planned CLI surface.

## Commands

```text
waveform render INPUT
waveform preview INPUT
waveform inspect INPUT
waveform dry-run INPUT
waveform doctor
waveform capabilities
waveform preset list|show
waveform performance list|show
waveform clean --workdirs
waveform benchmark dry-run|run
```

`INPUT` is a file or directory; there is no required separate `batch` command.

## Common planned flags

```text
--output-dir PATH
--preset NAME_OR_PATH
--performance NAME_OR_PATH
--config PATH
--renderer NAME
--format FORMAT       # repeatable
--fps 30|60
--recursive
--force
--debug
--keep-temp
```

Visual CLI overrides may include style/color/glow/FPS/etc and override lower-precedence config.

## Examples

```bash
waveform render episode.wav   --preset iuris-default   --format prores4444   --format png   --output-dir ./renders
```

```bash
waveform render ./audio --performance maximum
```

## Output format selection

`--format` is repeatable and accepts only `png` and `prores4444`. All effective
tokens are validated together: an unknown token rejects the entire request, even
when supported formats are also requested. The CLI reports `E_CONFIG_INVALID`
and exits 2 before source probing/hashing, encoding or output/work/result
directory creation. This applies to dry-run, preview and render, including
`[output].formats` inherited from application config. Benchmark dry-run/run also
reject unsupported manifest formats before matrix media work or result creation.

A nonempty CLI/API selection overrides the config list. An absent or empty API
selection falls back to the configured list (built-in default: `prores4444`); an
empty effective list retains the existing ProRes default. Repeated supported
tokens do not duplicate assets. Formats do not change visual render identity.

## Dry-run

Resolve the real plan without final rendering. Report discovery, grouping, warnings, timeline checks, effective preset/performance, signatures, dest paths, and SKIP/PROCESS. Concurrency/workdir policy remain listed as performance metadata (`chunk_seconds`, jobs, workdirs).

Planning and `inspect` do not create output directories, workdirs, analysis caches
or result files, and do not modify existing project trees. `dry-run` supports
`--start` / `--duration` to plan the same clip identity as `preview`; `render`
processes the full file and does not accept these clip flags.

Capacity inspection uses the output root when it exists, or its nearest existing
directory ancestor without changing the planned destination. An unavailable,
inaccessible or non-directory path produces a typed `W_OUTPUT_SPACE` warning
rather than creating directories or failing with a raw filesystem exception.
This capacity warning is advisory: check permissions and free space before
rendering. If destination inspection itself is inaccessible, planning stops with
a typed `E_OUTPUT_VALIDATION` / exit 5, rather than a raw filesystem exception or
a claim that inaccessible output is reusable. Normal execution still creates its
required output and work directories.

## Preview

Uses the real renderer over a short interval. Expected controls: `--start`, `--duration`, optional future `--template`. Preview uses the preset FPS (default **60**); `--fps 30` is a different identity and will look more stepped at the default scroll speed.

## Inspect

Reports source/grouping metadata without rendering.

## Doctor

Checks FFmpeg/ffprobe, `prores_ks` and PNG encoders, `gblur`/`overlay`/`scale`/`alphamerge`/`lut`, writable temp dir, and a minimum of 256 MiB free there. GPU checks are deferred. Canonical application config is validated when `--config` is passed to other commands.

## Capabilities

Reports renderer/style/effect/output/continuity support.

## Presets

MVP:

```text
waveform preset list
waveform preset show NAME_OR_PATH
```

Later:

```text
preset create/save/copy/import/export/validate/reset
```

Source-qualified references should support:

```text
builtin:name
user:name
project:name
/path/to/file.toml
```

Use `--overwrite` for preset replacement. Reserve `--force` for render versioning.

## Performance profiles

MVP: `performance list` and `performance show NAME_OR_PATH`. Validate remains implicit on load.

## Clean

`waveform clean --workdirs` removes `ewp-*` directories under the default temp work root (or `--root`). `--dry-run` lists them. Published outputs are never touched.

## Benchmark

```text
waveform benchmark dry-run MANIFEST.toml [--output-dir PATH]
waveform benchmark run MANIFEST.toml [--output-dir PATH] [--force]
```

Dry-run expands the Cartesian matrix and reports SKIP/PROCESS/BLOCKED/UNSUPPORTED. Run executes PROCESS cells through the real renderer and writes `{output-dir}/{manifest-name}_benchmark.json` with wall time, max RSS, and output size. Default output directory is `benchmark-output/`.

## Exit codes

Frozen for `waveform` 0.0.0: 0 success; 2 config/CLI; 3 input; 4 capability; 5 render/output; 6 partial multi-job failure. See `09-state-errors-and-logging.md`.

## Refined ribbon appearance overrides

`dry-run`, `preview` and `render` accept `--detail-level`, `--waveform-color`,
`--glow-level`, `--amplitude` and `--stroke-width`. They delegate to the shared
validated application API. See [06](06-configuration.md#refined-ribbon-controls-fr-look-controls-001)
for defaults/ranges/applicability, five brand colors, unresolved yellow and precedence.
Unsupported settings fail as configuration errors; dry-run plans the same signature
as rendering and creates no outputs.


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
