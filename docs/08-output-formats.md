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
RGBA pixel format (8- or 16-bit), with CRC checking and strict decode errors.
Decode diagnostics fail validation even when
ffprobe exits zero. This runs before PNG publication and on PNG reuse: O(frames)
file reads/PNG decode and compact per-frame metadata, not decoded RGBA frames
retained in Python, and not one tool process per image. PNG files do not store a
sequence FPS; job FPS plus the contiguous expected count defines their timing.

MOV validation checks ProRes 4444/4444 XQ, `yuva444p` alpha capability, dimensions,
expected FPS, a known count within the existing one-frame tolerance, and positive
finite duration within one target frame (plus microsecond metadata rounding).
The production validator opts into a first-frame sample; ordinary `probe_video`
callers remain metadata-only. This output inspection requires the first video packet to
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


### Filled-ribbon alpha association and appearance checks

The refined filled ribbon writes **straight (unassociated) alpha**: where alpha
is nonzero, canonical RGB remains the selected foreground color, not that color
multiplied by alpha. Reflection attenuates lower-body/halo alpha, not RGB. The
independent horizon uses its configured final-pixel coverage and opacity. Exact
silence with idle activity zero contributes no body or halo; the enabled horizon
alone remains. A genuinely active body can cover the horizon at the shared seam.

Composite these assets with straight-alpha interpretation. Applying a
premultiplied-alpha interpretation to straight RGB can make a low-alpha lower
reflection or halo appear too bright or broad. This is an interpretation hazard,
not evidence of a defect in any particular player or NLE. Confirm the actual
consumer's alpha interpretation and compare canonical PNG against decoded MOV
over the same background before changing appearance controls. No automatic
consumer detection or new encoder/metadata guarantee is introduced here.

A viewer that discards alpha entirely displays raw RGB, not the intended
composition: low-alpha halo pixels can become a solid band and the reflected
body can look fully opaque. A missing-looking horizon in that view is not an
opacity/extent measurement. For ordinary-player inspection, use a **separate,
explicitly flattened inspection copy** over the intended background and label it
nontransparent. Keep the original transparent production asset for composition.
Flattening must apply straight alpha before dropping the channel; simply
converting RGBA to RGB is not flattening. Do not silently premultiply production
RGB, change appearance settings, or bake a background into the canonical asset
to accommodate an alpha-ignoring viewer. Inspection copies are not a newly
supported application output format or proof of any consumer's default behavior.

For a one-worker/two-worker comparison, use the same audio interval, resolved
frequency span, normalization peak and mapping history. Full-source auto analysis
and a cropped preview may select different spans and peaks; equal timestamps or
appearance settings alone do not imply equal contour heights. Regression tests
exercise real spawned pool workers, compare canonical PNG and decoded ProRes,
and reject opaque reflection, wrong horizon and broad silence even when the
background remains transparent. Codec-appropriate alpha rounding is separate
from geometry/coverage correctness. These checks do not establish consumer/NLE
compositing or operator visual acceptance.
