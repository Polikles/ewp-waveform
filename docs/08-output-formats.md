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
independent horizon uses its configured final-pixel coverage and opacity. Exactly
zero processed waveform geometry with idle activity zero contributes no body or
halo; the enabled horizon alone remains. A zero source-audio instant after
activity can retain nonzero mapping history and need not mean exactly zero
processed geometry. A genuinely active body can cover the horizon at the shared
seam.

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


#### Observed playback and alpha-aware composition

In the bounded operator assessment on 2026-11-11, both full-length MP4 viewing
copies looked correct, and the transparent MOV inspected in DaVinci Resolve
also displayed correctly there. Ordinary-player playback of the MOV still showed
the uniformly filled appearance described above. These are actual observations,
not a compatibility guarantee for every player or Resolve configuration, exhaustive
frame-by-frame inspection, performance acceptance or release approval. They do not
confirm download or authorize cleanup.

The viewing-copy tasks left the transparent MOV masters unchanged. The difference
is playback/compositing: discarding alpha can make the reflection and weak halo
look uniformly filled and obscure the horizon. Correct straight-alpha composition
recovers their intended opacity; it is not a newly corrected raster implementation.
Keep the transparent master for alpha-aware composition and use a separate opaque
MP4 for ordinary viewing.

#### Full-master MOV-to-MP4 viewing copies (external FFmpeg workflow)

These two commands reproduce the verified full-viewing recipe with portable,
quoted filenames. They are external FFmpeg commands, **not new waveform CLI
commands or canonical application output formats**. They require the existing
`libx264` encoder; no installation is implied. Supply the corresponding existing
transparent masters and choose new, distinct output paths. `-n` refuses to
overwrite an existing output; never select a master as an output path.

The tested example is **1400x280, 60 fps, 23741 frames** for each master. The dark
foreground mode is composed over RGB(8,16,24), hexadecimal `0x081018`; the light
foreground mode uses RGB(240,240,240), hexadecimal `0xf0f0f0`.

Dark background:

```bash
ffmpeg -nostdin -n -v info -xerror -i 'transparent-master-dark.mov' \
  -f lavfi -i 'color=c=0x081018:s=1400x280:r=60' \
  -filter_complex '[0:v]format=rgba[fg];[1:v][fg]overlay=alpha=straight:format=auto,format=yuv420p[v]' \
  -map '[v]' -frames:v 23741 -an -c:v libx264 -preset fast -crf 12 \
  -pix_fmt yuv420p -threads 2 -movflags +faststart 'dark-OPAQUE-viewing-full.mp4'
```

Light background:

```bash
ffmpeg -nostdin -n -v info -xerror -i 'transparent-master-light.mov' \
  -f lavfi -i 'color=c=0xf0f0f0:s=1400x280:r=60' \
  -filter_complex '[0:v]format=rgba[fg];[1:v][fg]overlay=alpha=straight:format=auto,format=yuv420p[v]' \
  -map '[v]' -frames:v 23741 -an -c:v libx264 -preset fast -crf 12 \
  -pix_fmt yuv420p -threads 2 -movflags +faststart 'light-OPAQUE-viewing-full.mp4'
```

`format=rgba` prepares the foreground; `overlay=alpha=straight:format=auto`
composites its unassociated alpha over the background before `format=yuv420p`
drops alpha. Simply dropping alpha is not equivalent. Both commands produce
silent (`-an`), lossy, opaque H.264/libx264 viewing derivatives with preset `fast`,
CRF 12, `yuv420p`, encoder threads 2 and `+faststart`. The thread setting applies
to the encoder, **not a whole-process thread cap**. These copies cannot replace
the alpha masters and may differ in RGB because of compression/color conversion.

For another master, obtain its actual width, height, exact frame rate (including
any rational numerator/denominator), frame count and timestamp cadence from that
master's validated metadata/frame inspection, not from these example constants.
Set the background `s` and `r` to the actual dimensions and cadence, and
`-frames:v` to the actual complete frame count. Select the intended background
for that foreground mode. The verified recipe assumes a zero-start regular frame
grid; do not claim it preserves arbitrary variable or irregular timestamps.

The finite `-frames:v 23741` bound is essential: the generated lavfi background
has no duration limit and must not be allowed to keep the output running
indefinitely. Preserve the master's exact frame count and cadence, not a rounded
audio duration. In this example the frame grid is exactly `23741/60` seconds
(approximately 395.683333 seconds), not the source audio's 395.6785 seconds; do not
replace the frame limit with an audio-duration `-t`. Verify the derivative's
complete decode, dimensions, exact count, FPS and frame timestamps against its
master, and confirm opacity/no audio and faststart. Retain input/output identities,
background and conversion settings separately; do not overwrite the masters.

A viewing copy can be regenerated from an existing MOV without audio re-analysis
or waveform rendering, retaining that master's normalization and mapping context.
Automatic transparent MOV plus optional MP4 companion export remains a **future
requirement**, not a current CLI option. See the [delivery and manuals roadmap](
99-roadmap.md#output-delivery-and-manuals--future-only). Full user manuals will be
separate CLI and GUI documents later; this focused conversion recipe is not either
manual.
