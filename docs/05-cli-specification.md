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
