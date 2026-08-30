# Install (Ubuntu 24.04 / WSL2)

This is the operator install path for the FFmpeg MVP. You do not need a GUI, GPU, or Docker.

Reference environment: Ubuntu 24.04 (WSL2 or bare metal), Python 3.12, FFmpeg 6.x with `prores_ks` and PNG.

## 1. System packages

```bash
sudo apt update
sudo apt install -y ffmpeg git curl
ffmpeg -version
ffprobe -version
```

You need `prores_ks` and `png` encoders and the `gblur`, `overlay`, and `scale` filters. `waveform doctor` checks these. Do not vendor FFmpeg into the repo.

## 2. `uv` and Python 3.12

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv python install 3.12
```

## 3. Clone and install the package

```bash
git clone https://github.com/Polikles/ewp-waveform.git
cd ewp-waveform
uv sync --no-dev
uv run waveform version
```

`--no-dev` is enough to run the CLI. Developers who will run the quality gate should use `uv sync` (installs ruff, mypy, pytest). See `DEVELOPMENT.md`.

## 4. Verify

```bash
uv run waveform doctor
uv run waveform capabilities
```

`doctor` must print `doctor: ok` and exit 0. If it fails, the message names the missing encoder, filter, temp-dir write, or disk space. Fix the environment before rendering.

## 5. Optional: put `waveform` on PATH

```bash
uv sync --no-dev
# then, from this checkout:
uv run waveform --help
```

There is no public pip/PyPI release. Do not `pip install` from an index. Internal betas run from this repository with `uv`.
