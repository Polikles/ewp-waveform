# Install — internal checkout delivery

The accepted internal MVP baseline is extended by development version 0.2.1
(mapping7 ribbon with an exact row-support guard, separate Moving mouth and
selectable appearance controls).
The supported delivery recipe is a source checkout plus uv, Python >=3.12,<3.13
and system FFmpeg/ffprobe.
There is no public release, index-installable package or qualified wheel/Docker
image. GPU rendering, native Windows and Apple Silicon qualification remain
deferred. This document is a recipe, not evidence that every listed host works.

Historical reference: Ubuntu 24.04 / WSL2, Python 3.12 and FFmpeg 6.x. The current
restored project environment was checked on Ubuntu 26.04.1 x86_64 with CPython
3.12.3, uv 0.12.6 and system FFmpeg/ffprobe 8.0.1-3ubuntu2. Those observations and
the project gates do not constitute a fresh clean-host/WSL installation test.
See [the dependency baseline](../docs/14-dependency-baseline.md): the exact minimum
FFmpeg version is not qualified; capabilities matter more than the version string.

## 1. Provision system tools on an approved host

On an Ubuntu host where the operator permits system installation:

```bash
sudo apt update
sudo apt install -y ffmpeg git curl
ffmpeg -version
ffprobe -version
```

Require `prores_ks` and `png` encoders and `gblur`, `overlay`, `scale`,
`alphamerge`, and `lut` filters. `waveform doctor` checks these. Do not vendor
FFmpeg into the repository. No provisioning is performed by this documentation.

## 2. Prepare uv and Python 3.12

If absent, install uv using the operator-reviewed Astral instructions/source.
Review the installer before executing downloaded code. Then:

```bash
source "$HOME/.local/bin/env"
uv python install 3.12
```

Do not retarget a broken Python 3.12 virtual environment to system Python 3.14.
Preserve the old environment before an explicitly authorized rebuild. An existing
restored environment does not need reinstalling just because documentation changed.

## 3. Use the checkout and committed lock

```bash
git clone https://github.com/Polikles/ewp-waveform.git
cd ewp-waveform
uv sync --locked --no-dev
uv run --no-sync waveform version
```

Select the intended reviewed commit before syncing. `--no-dev` is enough for the
CLI; developers use `uv sync --locked` for Ruff, mypy and pytest. See
[DEVELOPMENT.md](../DEVELOPMENT.md). Do not update dependencies as an install fix
without a separately reviewed change. The package version and committed lock must
agree. Normal `uv run waveform ...` may sync; use `uv run --no-sync waveform ...`
when deliberately reusing the already prepared matching environment.

## 4. Verify, then run bounded QA

```bash
uv run --no-sync waveform doctor
uv run --no-sync waveform capabilities
uv run --no-sync waveform --help
```

Require `doctor: ok` and exit 0 before rendering. Resolve missing tools/filters,
temp write or disk capacity diagnostics on that specific host. Follow the
[future checkout/host QA checklist](runbook.md#future-checkouthost-qa-checklist-not-a-qualification-result)
with one tiny authorized input and storage headroom, recording actual results.
No clean-host, Windows, WSL, wheel, Docker or GPU support is inferred from help.

There is no public pip/PyPI release. Run from this repository with uv; these
instructions do not place a standalone `waveform` executable on the global PATH.
Keep local audio, reference images and generated media outside Git and review
packages. See [runbook.md](runbook.md) for retained-reference and capacity policy.
