# Development

## Reference environment

- Ubuntu 24.04 under WSL2 or bare-metal Ubuntu.
- Python 3.12.
- `uv` for Python environment/dependency management.
- FFmpeg and ffprobe as system dependencies for MVP.

## Current phase

The next engineering phase is the FFmpeg research spike in `docs/21-ffmpeg-baseline-plan.md`. Record spike evidence as notes under `docs/notes/ffmpeg-spike/` (commands, capability outcomes, timing, and resource measurements). Do not commit generated media.

## Lock file

`uv.lock` is intentionally not fabricated in this specification pack. Generate and review it in the implementation environment after the dependency baseline is accepted.

## Intended quality gates

```bash
uv sync
make check
make test-integration
```

`uv sync` installs the `dev` dependency group (ruff, mypy, pytest). If `make` is unavailable, the same gates are:

```bash
uv run ruff check .
uv run mypy src tests
uv run pytest tests/unit tests/regression
uv run pytest tests/integration
```

The implementation phase must keep these operational.

## External dependencies

Do not vendor FFmpeg or other external binaries.
