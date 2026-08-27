# 01 — Product Scope

## Purpose

`ewp-waveform` generates reusable animated waveform assets from audio, primarily for audio-only podcast episodes that will later be composed into video.

```text
audio -> ewp-waveform -> transparent waveform asset(s) -> DaVinci Resolve
```

## In scope

- audio inspection/discovery;
- project grouping;
- one waveform asset per source track;
- multiple styles and composable visual effects;
- visualization-only normalization;
- alpha-capable export;
- single-file and directory/batch processing;
- preview and dry-run;
- deterministic render identity/SKIP;
- chunked rendering and recovery;
- result metadata;
- benchmarking;
- renderer abstraction;
- GUI-ready application API.

## Permanently out of scope

- audio editing/mastering;
- denoising/repair;
- transcription/subtitle generation/translation;
- diarization/speaker recognition/source separation;
- final scene composition;
- publishing/upload/RSS/blog automation.

Transcripts may later be optional auxiliary metadata, but core waveform rendering must not depend on them.

## Relationship to EWP workflow

`ewp-waveform` is a sibling utility to `ewp-transcripts`. A later orchestration layer may call both.

## Status

Specification baseline accepted. Internal beta / pre-MVP. No release candidate and no public release.

Licensed under the EWP Waveform Community License 1.0. See `LICENSE` and `LICENSING.md`. Public release is a later event, after a working browser GUI and remaining functions, immediately before a Docker image.
