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

The application probes the workdir MOV (ProRes + `yuva`) or PNG sequence before publish. Failed validation does not replace a previous good dest. SKIPPED jobs re-probe the existing dest and keep `validation.passed` aligned with that check.

Byte-identical ProRes/PNG is not required.


### Production validation strength and cost

PNG validation requires `frame_000001.png` onward without gaps or extra matching
names, nonempty regular files, and the expected count. One installed ffprobe
image2 traversal decodes the sequence and checks every frame's dimensions and
RGBA pixel format (8- or 16-bit). Decode diagnostics fail validation even when
ffprobe exits zero. This runs before PNG publication and on PNG reuse: O(frames)
file reads/PNG decode and compact per-frame metadata, not decoded RGBA frames
retained in Python, and not one tool process per image. PNG files do not store a
sequence FPS; job FPS plus the contiguous expected count defines their timing.

MOV validation checks ProRes 4444/4444 XQ, `yuva444p` alpha capability, dimensions,
expected FPS, a known count within the existing one-frame tolerance, and positive
finite duration within one target frame (plus microsecond metadata rounding).
The existing ffprobe inspection now also requires the first video packet to
produce a readable frame and rejects error diagnostics. It runs at chunk
validation, final publication and destination reuse, with one bounded first-packet
decode per probe, not a full movie decode. It does not prove that later frames
are decodable, that all alpha values are meaningful, or that arbitrary damage,
ancillary chunks or visual content is correct. Full decode/equivalence oracles
remain in tests; they are deliberately not copied into every SKIP/cache check.

Invalid existing destinations follow the existing render path instead of being
SKIPPED. Newly produced invalid outputs return the existing FAILED/validation
failure and are not published. A missing expected PNG work directory also fails
validation. This does not redesign publication across multiple output formats,
checkpoint reuse policy, planning's advisory SKIP, repair, deletion or retry.
