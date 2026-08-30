# 17 — Definition of Done — FFmpeg MVP

The FFmpeg MVP is complete only when:

## Product/API
- scope boundaries remain intact;
- file/directory render works;
- recursion is explicit;
- source files remain immutable;
- CLI is thin over application API.

## Rendering
- FFmpeg capability status is documented for all four initial styles;
- glow baseline exists;
- unsupported particles fail clearly;
- deterministic signature/SKIP works;
- FPS/timeline contract is enforced.

## Output
- ProRes 4444 alpha validates;
- PNG alpha validates;
- multiple formats can be requested together;
- cross-format fidelity meets defined tolerance;
- atomic publication prevents partial canonical assets.

## Grouping/normalization
- prefix grouping and frame-aware duration checks work;
- mixed SKIP/SUCCESS/FAIL batch outcomes work;
- visualization normalization is source-safe/outlier-resistant.

## Recovery/UX
- chunk/checkpoint/resume path exists;
- `W_JOB_RESUMED` is recorded;
- dry-run, preview, inspect, doctor, capabilities work;
- numeric exit-code contract is frozen before identifiable internal CLI build.

## Results/quality
- per-job results validate;
- run summary is implemented or explicitly accepted as a documented MVP exception;
- integration/regression/determinism/chunk/resume/output tests pass;
- benchmark **runner** exists; labelled spike estimates are not profile defaults;
- long-duration and speech visual QA are operator evidence (fresh WSL VM / workstation), not missing code paths. See `Instructions/runbook.md`.
