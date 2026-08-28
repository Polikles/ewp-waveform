# 08 — Output Formats

## Alpha

Canonical production assets require alpha.

## MVP

- ProRes 4444 MOV with alpha.
- PNG RGBA sequence.

A render may request both with repeated `--format`.

Supported production FPS values are **60** (default asset generation) and **30**. FPS is part of visual render identity, not an encoder setting. At the default 5 s / 1400 px scroll, 30 fps moves ~9.3 px/frame and 60 fps ~4.7 px/frame; 30 fps is not required to match 60 fps smoothness at this speed.

## Fidelity

Output format is not part of visual identity. The same render identity must preserve geometry/style/timing across encoders within format-appropriate tolerance.

The custom renderer should conceptually generate canonical RGBA before encoding. FFmpeg MVP should preserve the same semantic contract even if its filter graph is monolithic.

## Validation

Successful output validates:

- existence/readability;
- dimensions;
- FPS;
- frame count/duration;
- alpha;
- expected codec/profile where relevant.

Byte-identical ProRes/PNG is not required.
