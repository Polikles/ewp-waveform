# EWP Waveform

> `ewp-waveform` is a local-first CLI application for generating deterministic, transparent animated waveform assets from audio recordings. The intended executable is `waveform`.

## Status

- Specification baseline: accepted.
- Implementation status: pre-MVP; CLI inspect/doctor/dry-run/capabilities work; render not yet.
- Release status: internal beta; no release candidate; no public release.
- Reference environment: Ubuntu 24.04 under WSL2 and bare-metal Ubuntu.
- Python baseline: Python 3.12.
- MVP reference renderer: FFmpeg.
- Planned MVP2 renderer: custom multi-pass renderer.
- License: EWP Waveform Community License 1.0 (source-available, not OSI Open Source).

## Scope

The project ends at the reusable asset boundary:

```text
audio input
    |
    v
ewp-waveform
    |
    v
transparent waveform assets
    |
    v
DaVinci Resolve / external compositor
```

Audio editing/mastering, transcription, subtitles, source separation, final scene composition, and publishing are outside scope.

## CLI (0.0.0)

```bash
waveform doctor
waveform capabilities
waveform inspect "/path/to/input"
waveform dry-run "/path/to/input" --preset iuris-default
```

`render` is not implemented yet (capability error). Planned full surface is in `docs/05-cli-specification.md`.

## Planned CLI

Core operator commands:

```bash
waveform render "/path/to/input" --output-dir "/path/to/output"
waveform preview "/path/to/input"
waveform dry-run "/path/to/input"
waveform inspect "/path/to/input"
waveform doctor
```

`INPUT` may be one file or one directory. Directory processing is batch processing. Recursion is opt-in.

Additional planned commands (`capabilities`, `benchmark`, `clean`, `preset`, `performance`) are specified in `docs/05-cli-specification.md`.

## Core rules

- Source audio is immutable.
- One source track normally maps to one waveform asset.
- FFmpeg is a backend, not the public configuration model.
- CLI and future GUI use the same application API.
- Visual presets are separate from performance profiles.
- Alpha transparency is mandatory.
- ProRes 4444 and PNG sequence are MVP formats.
- FPS is part of render identity; output format and performance settings are not. Default 30; 60 is a supported option.
- Chunking and resume must preserve temporal/visual continuity.
- Equivalent completed jobs are skipped by deterministic render signature.
- Canonical results are schema-valid JSON.
- Repository documentation is written in English.

See `docs/README.md` for the documentation index and normative precedence.

## License

`ewp-waveform` is source-available under the **EWP Waveform Community License 1.0**. It is not Open Source software in the OSI sense.

See [`LICENSE`](./LICENSE) and [`LICENSING.md`](./LICENSING.md).
