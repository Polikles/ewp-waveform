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

## Chunk boundary

Stress many boundaries and compare boundary neighborhoods for waveform amplitude, effects, pixel/alpha difference, missing/duplicate frames, and drift.

## Resume

Compare uninterrupted vs intentionally interrupted/resumed output and inspect the reported resume boundary.

## Duration

Validate typical 20–40 min, 60–80 min, and ~3 h endurance material without unnecessary whole-file memory scaling.

## FFmpeg MVP gate

MVP is not done until application API, CLI, presets/profiles, discovery/grouping, normalization baseline, alpha outputs, result identity, dry-run/preview/doctor, output validation, recovery evidence, and benchmark baseline are operational.
