# 09 — State, Errors, Warnings, and Logging

## States

Per-job:

```text
PLANNED
SKIPPED
RUNNING
RESUMED
SUCCEEDED
FAILED
CANCELLED
```

Run-level aggregation may use `PARTIAL`.

## Initial warnings

### `W_AUDIO_STEREO_DOWNMIX`
Multichannel source is downmixed for visualization. Use isolated tracks when available.

### `W_CHANNEL_SPLIT_ASSUMPTION`
Channels are rendered independently, but speaker isolation is unproven; crosstalk may mislead.

### `W_PROJECT_DURATION_MISMATCH`
Grouped tracks differ by >1 and <=3 target frames. Review alignment.

### `W_JOB_RESUMED`
A validated recovery path resumed at a reported source timestamp (first rebuilt chunk). Manually inspect the boundary. The result also stores `resume_history`.

### `W_OUTPUT_SPACE`
Output-size estimate is missing, or is close to / above free space on the output volume. Labelled spike extrapolation; not a hard stop.

## Initial errors

- `E_INPUT_UNSUPPORTED`
- `E_PROJECT_TIMELINE_MISMATCH`
- `E_RENDERER_CAPABILITY`
- `E_OUTPUT_VALIDATION`
- `E_PRESET_ALREADY_EXISTS`
- `E_CONFIG_INVALID`
- `E_CHECKPOINT_INCOMPATIBLE` — checkpoint schema/identity/integrity failed. Automatic resume discards that state and rerenders; it does not fail the job.

Each stable ID must have documented meaning, probable causes, consequences, and remediation.

### Unsupported output formats (`E_CONFIG_INVALID`)

`UnsupportedOutputFormatError` in `ewp_waveform.application.formats` is an
`AppError` with configuration exit code 2. It identifies all unsupported tokens
and lists `png` and `prores4444` as the supported choices. Remove or replace the
unknown tokens in repeated `--format` flags or `[output].formats`. The entire
effective request is rejected, not partially rendered or reported as successful
SKIP; no source hashing/probing/encoding or output/work/result directory creation
is performed for that request. Application planning/dry-run/render and direct
`render_job`/destination planning callers receive the same typed error. Existing
`ewp_waveform.application.service.AppError` imports remain supported.

## Logging

Separate:

- concise human console output;
- canonical result JSON;
- optional debug logs.

Expected controls include `-v`, `-vv`, `--quiet`, `--debug`.

## Exit codes

Frozen for the first identifiable internal CLI (`waveform` 0.0.0):

| Code | Category |
|---|---|
| 0 | success |
| 2 | config/CLI error |
| 3 | input error |
| 4 | capability error |
| 5 | render/output error |
| 6 | partial multi-job failure |
