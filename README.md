# EWP Waveform

> `ewp-waveform` is a local-first CLI application for generating deterministic, transparent animated waveform assets from audio recordings. The intended executable is `waveform`.

## Status

- Specification baseline: accepted.
- Implementation status: pre-MVP; the FFmpeg research spike is the next phase.
- Release status: internal release candidate; no public release yet.
- Reference environment: Ubuntu 24.04 under WSL2 and bare-metal Ubuntu.
- Python baseline: Python 3.12.
- MVP reference renderer: FFmpeg.
- Planned later renderer: custom multi-pass renderer.
- License: TBD; a source-available license is planned before public release.

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

## Planned CLI

```bash
waveform render "/path/to/input" --output-dir "/path/to/output"
waveform preview "/path/to/input"
waveform dry-run "/path/to/input"
waveform inspect "/path/to/input"
waveform doctor
```

`INPUT` may be one file or one directory. Directory processing is batch processing. Recursion is opt-in.

## Core rules

- Source audio is immutable.
- One source track normally maps to one waveform asset.
- FFmpeg is a backend, not the public configuration model.
- CLI and future GUI use the same application API.
- Visual presets are separate from performance profiles.
- Alpha transparency is mandatory.
- ProRes 4444 and PNG sequence are MVP formats.
- FPS is part of render identity; output format and performance settings are not.
- Chunking and resume must preserve temporal/visual continuity.
- Equivalent completed jobs are skipped by deterministic render signature.
- Canonical results are schema-valid JSON.
- Repository documentation is written in English.

See `docs/README.md` for the documentation index and normative precedence.

## License

License terms are intentionally not declared yet.
