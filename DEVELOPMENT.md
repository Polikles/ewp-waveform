# Development

## Reference environment

- Ubuntu 24.04 under WSL2 or bare-metal Ubuntu.
- Python 3.12 (`>=3.12,<3.13`).
- `uv` for the virtualenv and lockfile.
- FFmpeg and ffprobe as system packages (not vendored).

Operator install (no ruff/mypy) is [`Instructions/install.md`](./Instructions/install.md).

## Current phase

FFmpeg MVP **roadmap** (code + operator runbook) is in place. Next evidence is operator visual QA on a fresh WSL VM and long jobs off undersized disks. Spike notes stay in `docs/notes/ffmpeg-spike/`. Do not commit generated media.

Playhead, particles, GPU, Docker, and public release remain deferred (`docs/99-roadmap.md`).

## Quality gates

```bash
uv sync
uv run ruff check .
uv run mypy src tests
uv run pytest tests/unit tests/regression
uv run pytest tests/integration
```

If `make` is available: `make check` and `make test-integration`.

## External dependencies

Do not vendor FFmpeg, codecs, GPU runtimes, fonts, or media binaries.
