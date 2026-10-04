# 12 — Testing and Acceptance

## Layers

- unit;
- integration;
- regression;
- media/output validation;
- determinism;
- visual-format equivalence;
- chunk continuity;
- resume;
- endurance;
- benchmark-tool validation.

## Source immutability

Integration tests verify source SHA-256 is unchanged. Where portable/meaningful, source modification time should also remain unchanged.

## Discovery/grouping

Cover:

- single WAV/MP3;
- ungrouped name;
- 2/3 grouped tracks;
- first-separator behavior;
- default non-recursion;
- explicit recursion;
- symlink exclusion;
- downmix/split warnings.

## Timeline

At target FPS:

- <=1 frame: accept;
- >1 to <=3: warning;
- >3: error;
- explicit override.

## Successful output

Verify:

- requested files/sequences exist;
- dimensions/FPS/frame count/duration;
- alpha;
- decoder readability;
- expected codec/profile;
- result JSON schema validation;
- no partial final publication.

## Determinism

Given stable source, visual config, renderer visual-contract version, seed, and FPS:

- repeated renders meet defined tolerance;
- changing chunk size/workers does not intentionally change output;
- changing format preserves visual/timing equivalence.

### Renderer equivalence oracle matrix

Renderer refactors must pass the following non-media oracle matrix. Tests create their tiny
audio and render products under pytest temporary directories; no generated audio, PNG, or MOV
is committed.

| Path | Optional tools/capabilities | Variants compared | Required oracle |
|---|---|---|---|
| Raster regression | none beyond the Python test environment | all current `time+scroll` styles and all `field_center_out` geometries | exact SHA-256 of canonical RGBA raster bytes using the frozen visual-contract-v13 fixture |
| PNG sequence | FFmpeg with the `png` encoder | one chunk vs many chunks; `jobs=1` vs `jobs=N`; uninterrupted vs interrupted/resumed | contiguous frame names and exact encoded bytes for every frame, including the frame before, at, and after every chunk boundary |
| ProRes 4444 | FFmpeg with `prores_ks` and ffprobe | one chunk vs many chunks | exact decoded RGBA frames plus codec, alpha pixel format, dimensions, FPS, frame count, duration, and at-most-one-frame drift checks |
| Result payload | the corresponding render path above | repeated equivalent execution with different temporary/output paths and wall-clock timing | semantic equality after excluding only absolute paths, start/completion timestamps, and measured elapsed phase time |

MOV container bytes are not a visual oracle: muxing metadata may vary even when decoded frames
are identical. Result comparison retains render signatures, visual-contract versions, warnings,
analysis, normalization, validation, phase counts, and deterministic execution evidence.

Particles and `time+playhead` are explicitly outside this matrix because both are currently
reported as unsupported. A request for either must continue to produce an unsupported-capability
result; tests must not silently treat either path as rendered or equivalent. When either becomes
supported, its deterministic oracle must be approved and added to this matrix before renderer
refactoring relies on it.

## Chunk boundary

Stress many boundaries and compare boundary neighborhoods for waveform amplitude, effects, pixel/alpha difference, missing/duplicate frames, and drift.

## Resume

Compare uninterrupted vs intentionally interrupted/resumed output and inspect the reported resume boundary.

## Duration

Validate typical 20–40 min, 60–80 min, and ~3 h endurance material without unnecessary whole-file memory scaling.

## FFmpeg MVP gate

MVP is not done until application API, CLI, presets/profiles, discovery/grouping, normalization baseline, alpha outputs, result identity, dry-run/preview/doctor, output validation, recovery evidence, and benchmark baseline are operational.
