# 14 — Dependency Baseline

Captured on **2026-08-26**.

## Python

```text
Python >=3.12,<3.13
reference interpreter: 3.12.3
```

## Initial stable Python packages

```text
Typer      0.27.1
Pydantic   2.13.4
Hatchling  1.32.0
Ruff       0.16.4
mypy       2.3.1
pytest     9.1.1
```

These versions are the specification-scaffold baseline, not permanent compatibility guarantees.

Generate/review `uv.lock` in the implementation environment.

## System dependencies

MVP requires FFmpeg and ffprobe.

Observed on **2026-08-27** in this environment: `ffmpeg` / `ffprobe` **6.1.1-3ubuntu5** (`libavcodec 60.31.102`). See `docs/notes/ffmpeg-spike/environment.md`.

The exact minimum FFmpeg version is still deferred. Capability verification is more important than assuming a version string guarantees alpha/filter/encoder behavior.

## Policy

- do not vendor FFmpeg/codecs/GPU runtimes;
- lock Python dependencies through `uv.lock`;
- installation scripts may install/verify system tools;
- document dependency changes that alter supported behavior.
