# 07 — Results Data Model

## Per-job canonical result

Each successful render publishes `*_results.json`.

Required conceptual sections:

```text
schema/tool/job/renderer/project/inputs
preset
resolved_visual_config
resolved_performance_config
analysis
normalization
execution
warnings
outputs
validation
performance
resume_history
timestamps
```

## Identity

Store:

- job ID;
- full render signature;
- seed;
- source SHA-256;
- renderer/version/visual-contract version;
- preset source/name;
- canonical FPS/frame properties.

## Execution metadata not in visual identity

Still store:

- performance profile;
- chunk size;
- workers;
- FFmpeg threads;
- workdir policy;
- requested output formats.

## Run-level result

Multi-job invocation should create a run summary with run ID, command, timestamps, job references/counts, warnings, and aggregate performance.

Run ID is operational, not visual identity.

## Versioning

Result schema version is independent of application/preset/benchmark schema versions.
