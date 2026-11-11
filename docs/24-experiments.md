# 24 — Opt-in reproducible experiments

This is experiment tooling, not a replacement renderer, deployment platform or
promotion of a new output profile. Normal rendering remains transparent ProRes
4444 or PNG with the existing exact same-contract regression tests. Experiment
outputs occupy separate namespaces and do not change canonical presets, defaults,
normal output/reuse identities or performance-profile meaning.

## Quality and decisions

Distinguish exact optimizations from approximation experiments. An exact
optimization promises the selected contract unchanged and must retain its exact
functional/decoded-frame oracles. An explicitly selected approximation may change
compression samples or visual arithmetic if the operator finds it visually close
to the accepted effect. It still must preserve frame count, rational cadence,
timestamps, dimensions or declared crop transform, content timing, source
immutability and actual straight alpha. Do not relax default-path tests or refresh
an unexplained failing oracle to accommodate an experiment.

Technical validity and visual acceptance are separate: TECHNICAL_PASS may coexist
with VISUAL_PENDING and STUDIO_PENDING. Numerical error, hashes, SSIM or PSNR do
not approve appearance. The operator assesses motion/local rhythm, dominant
contour and relative height, subordinate reflection, horizon coverage, glow
falloff, silence, aliasing/flicker and actual Studio import/scrub/alpha. Use dark
and light backgrounds and checkerboard as appropriate. A codec/pixel-format help
listing is advertised capability, not runtime success or NLE compatibility.

The operator's 2026-11-11 report that the optimized 0.2.1 MOV looks correct in
DaVinci Resolve Studio is a new bounded observation. It does not imply exhaustive
frame review, every output/profile/container, a particular unrecorded Studio
version, exact-artifact download confirmation or permission to remove held media.
Earlier pending assessments remain historical, not retrospectively edited.

## Frozen context and one factor

Freeze source commit/tree and loaded code identity, exact interpreter and imported
source location, input hash and effective interval, preset/appearance settings,
analysis/normalization/history and noise time origin, host and affinity, selected
FFmpeg/ffprobe executable hashes/build configuration, actual encoding commands,
working/output placement and requested/observed execution route. Cropped analysis
context is not claimed equivalent to analysis of the full source. Reconcile a
copied WAV by hash on the target; never silently substitute another recording.

A pair changes one declared effective factor, not merely one requested flag.
Compare effective configurations and normalized commands and reject unexplained
differences. Profile, backend and toolchain factors disclose their necessary
pixel-layout, container, adapter and linked-library changes. Such comparisons
support a practical profile/backend/build claim, not exclusive codec arithmetic
or hardware-only acceleration. Setup, buffer capture, verification, proxy and
view costs remain separate from the declared render/encode timer.

CROP-OUT freezes one rectangle for the entire clip from the control's alpha bounds
plus a declared margin, with original canvas, offset and horizon anchor. Retain
original waveform pixel geometry and virtual coordinates. A smaller canvas.height
would recalculate amplitude and is a different experiment. Compare the cropped
result after padding into the original canvas. A full-canvas rectangle is no
reduction, not a successful optimization. WORK-ROI remains a separate future
comparison against that fixed export, with independent working-extent/halo proof.

PRORES-Q4 retains ProRes4444, alpha and precision and changes output rate control;
its appearance is operator-assessed. ENC-FFV1 is an encoding-profile experiment,
including mandatory pixel-layout and selected-container differences. It requires
lossless roundtrip against common pre-encode buffers, not decoded lossy ProRes as
the alleged original. Native/codec fixtures use the same prepared buffers for
both members. Actual production timings use the real application service/worker
path and are labelled separately. Four-second clips are serial under the current
1,800-frame field-pool threshold even when jobs=2 is requested; do not advertise
short fixture timing as parallel end-to-end production throughput.

## Bounded execution and recovery

Run sequentially, with a fixed counterbalanced order and append-only intent and
terminal attempt events. Fresh attempts get exclusive output/work namespaces.
Only actual PROCESS, successful complete validation and non-reused/non-resumed
outputs can support fresh throughput. Unsupported capability is an explicit skip,
never a successful experiment or silent CPU fallback. An incomplete STARTED
attempt is an uncertainty requiring reconciliation, not permission to replay it.
Resume verifies previously completed identities and continues only unattempted
cells; reading old results never becomes another throughput observation.

Before execution admit finite attempt, elapsed-time and disk allowances against
fresh actual resources and the applicable filesystem reserve. Count shared
output/work/scratch devices once. Stop further admission when conservative
remaining growth threatens the reserve. Preserve failures and recovery state;
never delete held media to fit the next experiment. Start with at most three CPU
candidates and short speech/quiet/relevant-tail screening, not the whole catalog,
full episode or an automatic finalist campaign. Later full acceptance remains
separately bounded under document23.

Do not emit simultaneous PNG alongside a timed MOV: the current dual-output
adapter changes the graph and the placement/role of -threads. Requested thread
settings are not observed runtime thread counts. Inclusive phase spans are not
additive wall partitions and parent-lifetime RSS is not a per-cell tree peak.

## Media and transfer

Each screened variant/clip retains its short tested transparent native master, a
comparison MOV and a correctly straight-alpha-composited MP4 on the frozen
intended background. Reuse the tested MOV as the comparison MOV where possible.
For AVI/MKV keep the actual tested file and label the extra MOV as a comparison
proxy; that MOV cannot prove the original codec/container imports in Studio.
Generate views outside measured rendering and record rendering, proxy, MP4 and
verification costs separately. Keep local media outside Git and review/provider
context. A two-second actual Studio import/alpha/seek check may remain explicitly
operator-pending; never invent it.

A transfer delivery contains portable scripts/manifests, exact source references,
requirements, fixture provenance/hashes and short CPU references only. It excludes
source WAV, huge/full media, credentials and orchestration/profile/config/runtime
state. Include a payload-only hash manifest, excluding the manifest itself, and
verify safe extraction, membership, bytes and usable entrypoints. Archive/package
creation is separately scoped; it is not a public release or tag.

## WSL and Windows recipes — unrun

GPU scenarios in the design catalog are recipes, not implementation claims. A
named adapter is implemented only when code exists and has been exercised at its
declared scope. Target preflight must distinguish advertised features from tiny
actual Vulkan transfer/filter and encoder-alpha/decode probes, each with explicit
outcomes. CUDA WhisperX does not establish Vulkan or GPU ProRes support. No
automatic FFmpeg/driver installation, replacement, VM CPU resizing or target-machine
access follows from these recipes.

Use a fresh same-host, same-build CPU control on WSL. An optional old/new-build
contrast is a separate toolchain factor on that host; if the old build cannot run,
record it NOT_RUN and establish the new-build CPU control directly. GPU-TRANSFER
adds an explicit matched-format upload/download roundtrip. GPU-BLUR compares blur
implementations against that transfer topology with the same other settings.
GPU-PRORES compares the encoder backend including mandatory upload/format
adapters while retaining CPU finishing. Only later combine selected wins as an
explicitly multifactor integration experiment. GPU FFV1 requires its own same-host
CPU FFV1 control and actual alpha/NLE capability proof.

Windows is a distinct platform block with its own CPU and GPU controls. Dividing
old-VM CPU wall by new-WSL/Windows GPU wall does not isolate GPU acceleration.
Run target probes/experiments only with actual target access and an applicable
separate execution envelope. All GPU/Windows runtime outcomes from preparation
on a CPU VM remain NOT_RUN, not PASS.

## Checked CLI and supported first slice

From the exact checkout and its prepared Python 3.12 environment:

```bash
python scripts/experiments.py --help
python scripts/experiments.py preflight --run /outside/git/evidence \
  --media-root /outside/git/media \
  --enable CROP-OUT --enable PRORES-Q4 --enable ENC-FFV1 \
  --ffmpeg /selected/bin/ffmpeg --ffprobe /selected/bin/ffprobe
python scripts/experiments.py prepare --run /outside/git/evidence \
  --media-root /outside/git/media --manifest examples/experiments/cpu-screen.json \
  --audio /operator/input.wav --input-sha256 EXPECTED_LOWERCASE_SHA256 \
  --preflight /outside/git/evidence/EXACT_PREFLIGHT_FILENAME.json \
  --enable CROP-OUT --enable PRORES-Q4
python scripts/experiments.py one --run /outside/git/evidence --cell EXACT_PREPARED_CELL_ID
python scripts/experiments.py batch --run /outside/git/evidence
python scripts/experiments.py resume --run /outside/git/evidence
python scripts/experiments.py views --run /outside/git/evidence
python scripts/experiments.py report --run /outside/git/evidence
```

Use the actual preflight filename returned by preflight, and a cell ID returned by
prepare; these are placeholders, not a filename-discovery option. Prepare's enabled
set must equal its manifest candidates. The example selects CROP-OUT and PRORES-Q4;
preflight may additionally retain the tiny FFV1 runtime probe. To plan explicit
FFV1 skips, select it in a private manifest and in prepare's enabled set; without
an actual Studio record those larger cells stay SKIP. Do not invent that record.

Preflight supports `--limits LIMITS_JSON` with the four positive-integer fields
`attempts`, `seconds`, `growth_bytes`, `reserve_bytes`. Maximum render/probe/fixture
attempts36, cumulative worker seconds1800, growth2GiB, minimum reserve10GiB. The
private manifest must carry those exact same limits. Views have a separate maximum
of24 worker attempts, sharing the total worker-time/growth/reserve allowance. The
parent must also admit other task evidence, checks and transfer-package growth;
the runner measures its own evidence/media namespaces, not all disk consumers.
Polling can overshoot between observations and termination; it is not a kernel
hard quota. Failed and unknown attempts remain consumed. A separate supplied
`--gpu-envelope` is only for tiny target-side WSL probes, not a GPU campaign adapter.

The manifest freezes visual overrides and intended viewing background. The
concrete first design uses balanced refined ribbon, visual noise0.35, idle0,
noise rate0.8 and seed1729; canonical presets are not edited. Configuration inputs
and re-planned effective settings are authenticated before work. The selected
implementation supports at most three workload IDs with explicit duration<=4s;
there is no full-source/PRODUCTION32 or pool experiment option. CROP-OUT and Q4
have real short-service and shared-buffer codec routes. FFV1 has a shared-buffer
codec adapter/tiny alpha probe only, with larger screens gated on Studio evidence;
its service publication remains unsupported. GPU campaign adapters are not
implemented. No absent option is a successful test or an implicit fallback.

`prepare` freezes the plan and selected input; first execution prepares one
canonical pre-encode RGBA8 fixture per clip. Codec and production-service routes
are separate operational contrasts, not interchangeable measurements. Whole-clip
bounds are frozen from that fixture. Completed service outputs and codec fixtures
are never silently reused as another fresh measurement.

Run views only after the timed matrix reaches its terminal technical state.
It reuses actual MOVs and separately labels any native-MKV comparison proxy,
restores crop placement, composites straight alpha on the frozen background and
records proxy, MP4 and verification/hash costs outside render timers. Report
indexes every attempt, pair state and artifact role; a HOLD returns exit2.
Incomplete indexing may return0 with explicit INCOMPLETE status, not a completed
screen. Operator visual/NLE states remain PENDING after technical completion.
