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
waveform benchmark ...
waveform clean ...

waveform preset ...
waveform performance ...
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

## Dry-run

Resolve the real plan without final rendering. Report discovery, grouping, warnings, timeline checks, effective config, normalization plan, signatures, formats, paths, SKIP/PROCESS state, concurrency, and workdir policy.

## Preview

Uses the real renderer over a short interval. Expected controls: `--start`, `--duration`, optional future `--template`.

## Inspect

Reports source/grouping metadata without rendering.

## Doctor

Checks FFmpeg/ffprobe, encoders/alpha path, writable directories, disk space, and config validity. GPU checks are deferred.

## Capabilities

Reports renderer/style/effect/output/continuity support.

## Presets

Planned:

```text
preset list/show/create/save/copy/import/export/validate/reset
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

At minimum: list/show/validate.

## Benchmark

Planned:

```text
waveform benchmark run manifest.toml
waveform benchmark dry-run manifest.toml
```

## Exit codes

Semantic categories are fixed; numeric values must be frozen before the first identifiable internal CLI build:

- success;
- config/CLI error;
- input error;
- capability error;
- render/output error;
- partial multi-job failure.
