# First working-path optimization campaign

The canonical operator commands remain in `EXPERIMENTS.md`. This note describes
experimental factors, not production-default promotion or GUI development.

## Direct encoding and thread controls

The CPU shortlist uses original audio analysis, interval-local normalization and
production raster/finishing. Direct FFV1 BGRA MKV does not decode or first produce a
ProRes master. Its matched ProRes control uses the same fixed-pipeline wrapper,
raster hashing and disabled analysis cache. Stock service time is a separately
labelled control, not the denominator for a direct-wrapper speedup. Native MKV
Resolve Studio import/alpha/playback remains pending; comparison MOV/MP4 views do
not qualify that native codec/container. A bounded serial32 direct API confirmation
is explicitly jobs1 and must not be called the stock jobs2 production32 route.

Encoder threads2 (FFV1) and complex-filter threads1 (ProRes) change independently;
no whole-process thread cap or production default follows. Initial VM.1 screens
found encoder2 neutral/slightly slower and filter1 substantially slower. Retain
negative results instead of adopting requested settings as improvements.

Native Windows async-depth1 versus4 uses independently qualified Vulkan ProRes and
a required same-input CPU oracle. Failure of that oracle skips only the dependent
async screen. Optional shared-master FFV1 prefixes6/60frames are bounded codec
attribution, one observation each, at most60seconds per worker including validation.
They include MOV decode/conversion/encoding; length differences do not isolate pure
startup. Neither these diagnostics nor the historical.465s CPU FFV1 transcode are
direct rendering evidence. No failed blur gate is waived to admit a codec.

## FIR output preparation

New modes preserve the selected FIR visual algorithm, not FFmpeg recursive gblur:

- `host-reference`: original allocating float32-alpha to RGBA host control.
- `host-reuse`: same half-up quantization/straight RGBA with reusable scratch/LUT.
- `device-rgba`: quantization/assembly on device, RGBA8 download4bytes/outputpixel.
- `device-alpha8`: device quantization, alpha8 download1byte/outputpixel, then host
  LUT assembly. Float32 alpha and RGBA8 both occupy4bytes/outputpixel.

With `--cuda`, the shortlist separately compares host-reference versus host-reuse,
host-reuse versus each device mode, batch1 versus2 with host-reuse, then diagnostic
versus ordinary timing with host-reuse/batch1. Both sides of every pair are gated
on their selected actual output/batch/timing route. Missing/failed CUDA does not
prevent independent CPU or compact cells. Tensor payload counters are not PCIe
hardware counters. Partial batches use only live frames; order/count/hidden RGB
and straight-alpha contracts remain explicit. Borrowed buffers are serialized
before reuse. The production geometry admits batch1/2 under a conservative256MiB
screen; this is not a guarantee for GPU-library workspace.

Ordinary mode removes detailed phase clocks/events and explicit phase syncs, but
blocking transfers and a completed-call synchronization remain. It is not pinned
staging, persistent full device-buffer reuse or transfer/compute overlap. Those
remain future attribution-driven experiments. Phase events, host wall spans,
finishing calls and pipeline/encoder envelopes overlap; never sum them into a
wall-time partition. Retain cold process/import/context/qualification separately.
VM.1 CPU Torch tests and host-assembly fixtures are not CUDA measurements.

## Compact finishing area

The initial speech crop is frozen for the whole clip at x0/y5/1400x258 in the
original1400x280 canvas. Place the compact native asset at original offset(0,5)
without stretching. It was derived from one whole control's decoded alpha>0 rows
13..254 plus8pixels; this is NOT a universal crop guarantee for other workloads,
settings or builds. A tighter threshold would be a separate appearance change.

Finished-output cropping and earlier guarded gray finishing height are independent
pairs. The earlier screen uses48px explicit vertical guards; recursive Gaussian
boundaries still change. The guard is not a finite-support/equivalence theorem.
Outside-export content/halo loss and interior differences remain descriptive
metrics plus pending operator assessment. Original analysis, scale, raster,
horizontal supersampling and full-mask transport are unchanged: the current early
domain reduction is in finishing, not earlier raster generation. See
`compact-working-area-experiment.md` for coordinate and edge tests/refusals.

## Verification and workflow time

External verification includes complete frame metadata/PTS, software decoding,
alpha/hash/temporal checks and, when requested, per-frame contrasting-composite
metrics. It is not render time. The supplied Windows GPU-ProRes~18s versus CPU~2.3s
observations do not isolate GPU decoding. New target costs must retain scope.

Exact-stream byte equality now proves error/composite terms zero while retaining
exact ROI denominators, avoiding redundant full-frame composite arithmetic.
Metadata decoding explicitly requests automatic threads; actual runtime counts
remain observations. Alpha extrema use exact vectorized uint8 reductions. These
changes retain every validation criterion; independently measured verification
savings must not be presented as renderer speedups. Cold worker cost still includes
verification and startup; MP4 generation remains separate.

Critical phase totals, actual payload counts, settings, validation and matched
statistics survive in `measurements-*.json`, prioritized in the2MiB diagnostic ZIP.
Raw ordered calls remain in the full report. Failure-path child stderr is retained
in cleanup even when the raster/FIR generator raises, without masking the original
exception. Missing target hardware and full-source confirmations remain explicit.
