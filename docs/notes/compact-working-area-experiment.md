# Compact-area finishing experiment (opt-in, no promotion)

`application.working_area_experiment.render_working_area` is a bounded callable
for an externally supervised original-audio campaign. It is deliberately **not**
a new production preset, performance-profile setting or public CLI. Do not infer
appearance or Resolve acceptance from technical validation.

```python
from pathlib import Path
from ewp_waveform.application.working_area_experiment import render_working_area
from ewp_waveform.ffmpeg.experiments import Crop
from ewp_waveform.ffmpeg.working_area import WorkingArea

# Example geometry only, NOT an appearance-approved production crop.
area = WorkingArea(Crop(100, 60, 1200, 160, 1400, 280), margin=48)
result = render_working_area(
    source=Path("original.wav"),
    start=2.0,
    duration=0.1,
    output=Path("fresh-observation/out.mov"),
    area=area,
    control="EARLY-AREA",
    ffmpeg="/selected/tools/ffmpeg",
    ffprobe="/selected/tools/ffprobe",
    visual_overrides={"reflection_opacity": 0.37},
)
```

The caller must allocate a fresh, task-owned output parent for each observation,
supply explicit finite `start >= 0` and `0 < duration <= 32` seconds, and supervise
process-tree ownership, deadlines, disk/RAM bounds and storage placement. Calls
must be serial or process-isolated because selected-tool PATH is scoped around the
production application. No dependency setup, GUI, automatic full-source run,
archive or cleanup is included. Hash/size/tool/preset/bounds/frame evidence is
returned; caller persists the report outside Git. Commands remain with the media.

## Controls and affected stages

All controls call the original refined-ribbon planning, clipped audio decode,
analysis, normalization, field raster and horizontal AA path. They disable the
analysis cache, force the serial branch, and feed **full original padded gray
masks**, not decoded finished masters. They use the same selected CPU
`prores_ks`, profile 4444, `yuva444p10le`, MOV encoder settings.

- `CPU-BASE`: original finishing graph and original canvas export.
- `CROP-OUT`: reuses the existing final-output crop adapter. All original finishing
  remains full-sized; only export crop, downstream color conversion and encoding
  use compact dimensions. Pre-encode crop pixels are exactly the corresponding
  original finished pixels. Different encoded block layouts are **not** promised
  to decode identically after lossy ProRes compression.
- `EARLY-AREA`: unchanged AA downsampling first, then reduces padded **gray height**
  before recursive `gblur`. Horizontal blur support is unchanged. Body/halo blend,
  horizon/reflection and colorization use the guarded smaller height. A final crop
  exports exactly the same rectangle as `CROP-OUT`. The original canvas is never
  replaced by a smaller layout or rescaled.

The rectangle is immutable for the whole clip and supplied explicitly, never
per-frame-adaptive. Use the same rectangle, interval, selected tools, overrides,
encoder and storage within pairs; compare the returned original-raster hashes.
For speech/onset/quiet/tail screens the parent chooses the intervals and persists
independent observations. Interval-local production analysis does not manufacture
full-source causal history. No original-audio performance run was required to
implement this seam.

## Coordinates, margins and refusal

Metadata retains the original canvas, exact pixel placement, horizon in original
and output coordinates, reflection split row, alpha association, working interval
and affected stages. Horizon extent remains based on original canvas width;
horizon/reflection Y tests use original canvas Y. `lum(X,Y)` samples stay local.
Guard rows are retained **through geq**, not discarded immediately after blur:
otherwise its local sampling would add a new boundary exactly at the export edge.
Physical canvas boundaries still use the original production boundary semantics.

Earlier finishing requires `margin >= max(1, ceil(3*glow))` final-pixel rows and
must actually reduce padded height. This is an explicit experimental floor, **not
finite support for FFmpeg's recursive blur or a mathematical error guarantee**.
Too-small margins, no reduction, unsupported/non-gray finishing, temporal shutter,
canvas drift and combined/chunked selections refuse rather than pretend
production equivalence. A wide output crop may leave no reduction at this margin;
that is an expected bounded refusal. Full raster generation/feed/AA costs remain.

Both compact outputs omit everything outside the rectangle, including faint halo.
An overly tight caller-selected rectangle can also omit strong content. Earlier
finishing additionally changes recursive boundary conditions and can affect
interior halo. These are intentional visual differences, never hidden execution
settings or a claim of byte equivalence.

## Difference reporting and acceptance

`ffmpeg.working_area.difference_metrics(full_rgba, compact_rgba, crop=area.crop)`
compares one canonical RGBA8 frame at a time, reconstructing original placement
without stretching. Use it consistently on pre-encode frames **or** decoded
frames, not a mixture. It returns:

- whole-canvas and inside-rectangle maximum alpha errors, RGBA maximum error;
- outside-rectangle alpha maximum/sum and hidden-RGB differences;
- counts strictly exceeding alpha code differences **0, 1, 2, 8, 32**;
- corresponding omitted-alpha counts, edge/halo and dark/light/checker composite
  integer metrics (existing production experiment metric definitions).

Those bins are descriptive thresholds, **not appearance acceptance tolerances**.
The render API optionally accepts `validation_reference_rgba` (exact full-canvas
RGBA8 frame count) for post-timer decoded-output comparison using the established
validator. It is never a throughput input. Without a reference, comparison fields
are unavailable/null, not a fabricated zero-error result. Source checksums,
complete decoded frame count, dimensions, cadence, duration, PTS and alpha content
are validated separately from appearance. The reused master validator requires both
transparent and active alpha samples: an entirely transparent export (for example
digital silence with the horizon disabled) is currently a bounded validation
refusal, not a claimed successful measurement. Raw silent-mask finishing is tested
independently. The inclusive pipeline timer excludes
planning/setup/fingerprints, external validation and report serialization; encoder
envelope overlaps generation/finishing and is not encoder-only. Cold process E2E
must be measured by the parent supervisor.

Every new compact artifact remains **appearance PENDING / Resolve PENDING**. This
work does not change supplied preview acceptance, native-blur failures, production
defaults, retention holds or promote a compact profile. Full-style delivery and
operator acceptance remain separate later work.

## Tiny actual fixtures

`tests/integration/test_working_area_route.py` executes real FFmpeg on first/last
canvas edges, overscan/no-overscan, odd placement, horizontal supersampling,
fractional alpha, reflection/horizon and two-pixel geometry. With zero blur it
checks exact compact-vs-original pixel coordinates; a deterministic random-mask
recursive-blur fixture witnesses nonzero interior error instead of fake equivalence. Three-frame
original synthetic audio exercises all three controls with identical raster
hashes, complete final frame/PTS validation and unchanged source bytes.
