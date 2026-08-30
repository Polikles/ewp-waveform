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

## SKIPPED jobs

Equivalent completed jobs (same source hash and render signature, complete dest) are `SKIPPED`. The result still lists the existing output paths. `validation.passed` is true when those outputs still probe as complete. Empty leftovers are not skipped; the job re-renders in place.

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

Each `render` invocation writes a run summary next to the output root as `run_<id>_results.json` (schema `schemas/run.schema.json`). It stores run ID, job references, SUCCEEDED/SKIPPED/FAILED counts, and timestamps.

Run ID is operational, not visual identity. Per-job payloads include `run_json` pointing at that file.

## Versioning

Result schema version is independent of application/preset/benchmark schema versions.
