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
A validated recovery path resumed at a reported source timestamp. Manually inspect the boundary.

## Initial errors

- `E_INPUT_UNSUPPORTED`
- `E_PROJECT_TIMELINE_MISMATCH`
- `E_RENDERER_CAPABILITY`
- `E_OUTPUT_VALIDATION`
- `E_PRESET_ALREADY_EXISTS`
- `E_CONFIG_INVALID`
- `E_CHECKPOINT_INCOMPATIBLE`

Each stable ID must have documented meaning, probable causes, consequences, and remediation.

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
