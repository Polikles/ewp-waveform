# 25 — Opt-in WSL CPU/GPU experiment suite

This suite is experimental tooling, not a production GPU renderer or new output
profile. Normal APIs/presets/defaults and the old `scripts/experiments.py` remain
unchanged. Source implementation is not a claim of target runtime success.
Operator visual assessment and actual Resolve Studio import/alpha/playback remain
**PENDING** until recorded outside this technical suite. Studio is not a gate on
generating technically valid short assessment artifacts, including native FFV1.

## Workloads and the authenticated reference

`examples/experiments/vm-reference.json` is the portable authenticated historical
contract, including the entire resolved appearance, requested processing and actual
pool ranges, VM FFmpeg8.0.1 identities and historical result provenance. Its full
0.2.1 measurement is **318.452082 process / 318.095615 service seconds**, 23,741
frames and a 2,848,387,115-byte MOV. This is not a new full render of0.3.1 or of
the suite source. The mapping-only descendant has a measured32-second result;
its full MOV qualification remains capacity-pending in that historical record.

`prepare --source-commit` requires the exact clean **final suite checkout**, not
the historical commit in that reference. It freezes Git HEAD/tree/status, loaded
source/config bytes, interpreter/dependencies, selected tools, input, explicit
manifest order, device and resource envelope. Preflight checks the complete
preset/recipe against the reference; service cells also compare the entire
resolved visual configuration (excluding their explicit experiment identity).

| Scenario | Execution and comparison |
|---|---|
| FULL | Actual stock service, whole source; no four-second hook. Reference recipe, balanced jobs2/threads0/chunk60. |
| PRODUCTION32 | Actual stock service[25,57),1920frames, real production pool2 above1800-frame threshold. |
| A / B | Optional old-build versus selected-new-build short CPU service. Build contrast only. |
| B / C | Same-build short CPU service versus gray upload/download before unchanged CPU blur. Exact transfer and decoded finishing equality required. |
| C / D | Same transfer topology; CPU gblur replaced by mono Vulkan Gaussian sigma16,size97,planes1. Deliberate approximation. |
| E0 / E1 | Same CPU finishing, explicit common yuva444p10le conversion, ProRes4444 alpha_bits16. CPU prores_ks versus Vulkan upload/prores_ks_vulkan, hardware pix_fmt=vulkan,async_depth1. |
| F0 / F1 | Codec-buffer only, not service publication: one production-finished lossless compressed RGBA oracle; decode/BGRA/conversion/container plus CPU FFV1 versus Vulkan FFV1. Same level3,g1,coder1,context0,slices4; GPU async_depth1. |

Full and32-second calls do not bypass the pool through experiment hooks. Short
A/B CPU controls explicitly select the CPU-CONTROL experiment, changing logging
only to the same verbose level as their GPU service peers; their graph/encoder
remain CPU defaults. Matched codec CPU/GPU cells also use common verbose logging. Four
seconds remain serial, even though jobs2 is requested. The32-second and short
analysis, auto-span/normalization, EMA and causal history are interval-local;
procedural noise time origin is the actual source start. They are not
full-source-context excerpts. No global WSL eight-CPU or RAM allocation is imposed;
actual affinity/cgroup/memory/storage are discovered. Jobs2 is the frozen workload
factor, not a whole-process CPU cap; encoder thread arguments do not establish
observed process/filter thread counts.

The supplied matrix is sequential and finite, with explicit ABBA order for two
paired observations per factor. Full/32 cells are separate service blocks. Never
divide historical VM time by WSL GPU time or divide ProRes time by FFV1 time and
call that isolated GPU acceleration. E and F include their mandatory backend
conversion/upload package. No Q4, crop, combined-wins or altered appearance is
hidden in these routes.

## Separate pinned FFmpeg build

Use a prepared Python3.12 environment from this checkout and its documented locked
dependencies. This document does not authorize dependency, driver or host-config
changes. `scripts/experiments_build.py` performs **no dependency installation**.
It defaults to a source-only plan. The operator supplies a C compiler, make, git,
nasm, pkg-config, x264 development files, Vulkan headers and a working glslc.
The pinned source checks headers>=1.3.277 and separately1.4.317 capabilities;
its shader compiler must support the Vulkan1.4/SPIR-V1.6 compile target. Those
build targets are not a guarantee about the runtime ICD. Do not use a guessed
`--enable-libshaderc` recipe. No Linux NVIDIA display-driver installation in WSL.

The source is n9.0.2 commit
`946fcce07b6dcd0331c8cc609192aeff5e1924f8`, fetched from the official FFmpeg
mirror. All three roots below must be new, disjoint and outside Git. The script
uses an isolated TMPDIR under BUILD and never replaces system FFmpeg:

```bash
python scripts/experiments_build.py --source "$FFSOURCE" --build "$FFBUILD" \
  --prefix "$FFPREFIX" --cc cc --glslc glslc
# After independently admitting target build disk/RAM/time and prerequisites:
python scripts/experiments_build.py --source "$FFSOURCE" --build "$FFBUILD" \
  --prefix "$FFPREFIX" --cc cc --glslc glslc --execute
```

The builder retains command argv/stdout/stderr, actual compiler/SPIR-V compiler,
configure flags/log/config.h/config.mak, exact source commit/clean status, tool
hashes, ldd observations and actual linked-library hashes in
`$FFBUILD/build-receipt.json`. Retain the referenced evidence at those locations.
No binaries or source media go into Git. Configure enables Vulkan and x264, with
autodetection disabled; no vendor codec/driver binaries are distributed.

CUDA WhisperX/NVENC success does not establish Vulkan. Preflight inventories
advertised filters/encoders, observes WSL/kernel/CPU/affinity/cgroups/RAM/storage,
retains available nvidia-smi/vulkaninfo metadata, then performs actual two-frame
64x32 **and1400x280** transfer/blur/codec probes. Verbose FFmpeg must identify the
selected RTX3090; llvmpipe/lavapipe/software devices are rejected. GPU media probes
are not run on a non-WSL VM. `/dev/dri` alone is neither positive nor negative
proof. Every service GPU encode also checks selected-device evidence.

Probes require byte-exact gray/RGBA/BGRA/planar10 roundtrip and production-topology
CPU/transfer pre-encode equality; they verify software decode/count/rational PTS.
FFV1 must preserve every RGBA byte, including hidden RGB. ProRes records decoded
alpha-plane hashes, equality and maximum error against the common10-bit input.
The declared alpha precision allowance is at most **one10-bit input code step**;
transparent/active extrema must survive. Nonexact-but-valid quantization is
explicitly labeled assessment-pending, never alpha-exact. Opaque, truncated or
larger alpha loss is HOLD. ProRes color and Vulkan blur are not required to be
pixel-identical. No automatic visual or Studio acceptance follows from metrics.

Missing advertised optional encoder/filter support may produce a retained
CAPABILITY_UNAVAILABLE skip. A build without the Vulkan API records
API_UNAVAILABLE with GPU cells NOT_RUN. Unknown options, graph errors, wrong
selected device, timeout or failed alpha/lossless oracles are **FAILED/HOLD**, not
unsupported. BGRA failure does not prove all FFV1 alpha layouts unsupported;
no such alpha-unsupported conclusion is synthesized. Missing old tools leaves A
NOT_RUN while B establishes its own new-build baseline.

## Prepare, execute, resume, view and export

CLI scenario `FULL` is operator scenario A (full environment reference). The
short CLI label `A` is only the optional old-build contrast from the research
design; it must not be confused with that full reference.

From a normal GitHub checkout (the parent supplies the final literal commit):

```bash
git clone https://github.com/Polikles/ewp-waveform.git
cd ewp-waveform
git checkout --detach "$FINAL_SOURCE_COMMIT"
uv sync --frozen --python 3.12
source .venv/bin/activate
```

This is operator-run setup using the project's existing lockfile, not an agent
installation performed on VM.1. Supply uv/Python using the maintained install
runbook if they are absent; do not change the locked dependency versions.

For correspondence with the historical VM service recipe, the full call is:

```python
from pathlib import Path
from ewp_waveform.application.experiments import VISUAL
from ewp_waveform.application.service import render

# AUDIO and OUTPUT are local paths, with selected VM tools on PATH and a fresh
# external work/TMPDIR. This is a reproduction recipe, not fresh historical output.
results = render(
    Path(AUDIO),
    preset_name="iuris-ribbon-refined",
    performance_name="balanced",
    formats=["prores4444"],
    output_dir=Path(OUTPUT),
    start=None,
    duration=None,
    force=True,
    **VISUAL,
)
```

Balanced means the authenticated jobs2/chunk60/threads0 request. The portable
reference records actual pool ranges and encoder thread argument separately.
The suite's FULL cell uses this same stock service with explicit per-attempt
work/output roots and verifies the complete resolved recipe.


Checkout the parent-published **final source pin** before use; the integrator
supplies it in delivery notes. Do not use the mapping-only historical pin as the
suite pin. The only local substitutions are checkout/source pin, audio path,
selected tool/build locations, optional old tools and new output/accounting roots.
The distributed appearance/intervals/input hash do not require reconstruction.

```bash
python scripts/experiment_suite.py --help
python scripts/experiment_suite.py prepare --run "$RUN" --media-root "$MEDIA" \
  --manifest examples/experiments/wsl-suite.json --audio "$AUDIO" \
  --source-commit "$FINAL_SOURCE_COMMIT" \
  --ffmpeg "$FFPREFIX/bin/ffmpeg" --ffprobe "$FFPREFIX/bin/ffprobe" \
  --build-receipt "$FFBUILD/build-receipt.json" --device 'RTX 3090'
# Append --old-ffmpeg /old/bin/ffmpeg --old-ffprobe /old/bin/ffprobe for A.
# Append --account-root /another/disjoint/task-created/root for shared growth scope.
python scripts/experiment_suite.py preflight --run "$RUN"
python scripts/experiment_suite.py one --run "$RUN" --cell full-reference
python scripts/experiment_suite.py batch --run "$RUN"
python scripts/experiment_suite.py resume --run "$RUN"
python scripts/experiment_suite.py views --run "$RUN"
python scripts/experiment_suite.py results --run "$RUN"
python scripts/experiment_suite.py export --run "$RUN"
```

Prepare does no media execution. Preflight and later commands execute media and
require an admitted target envelope. `one` selects an exact already-frozen ID;
it does not create a new trial. `batch` and `resume` dispatch only unattempted
cells. Readback never counts as another throughput observation. A failed attempt
is immutable and blocks further timed dispatch; a partial STARTED attempt is an
uncertainty HOLD requiring external reconciliation. Never delete it or blindly
rerun it. Correct code/manifest in a new namespace, retaining failed ancestry.
All request/result/log/media hashes are verified on resume. Exclusive suite locks
prevent concurrent owners. Defaults never choose GPU via environment variables
or monkeypatching; the service uses an explicit typed opt-in specification.

The manifest provides explicit finite total attempts/time/growth, filesystem
reserve, available-memory floor, per-attempt time and conservative per-kind
estimates. The example admits a full reference's substantial pool+concat storage;
it is **not** admitted on a small VM merely because the script exists. Monitoring
counts declared disjoint growth roots relative to frozen baselines and checks
free space per filesystem, available RAM/cgroup headroom, cumulative worker time
and process-group deadlines. No media or retained failures are deleted to fit.
Polling is0.2s and can overshoot between observations/termination; it is not a
kernel quota or process-tree RSS guarantee. Other task-created storage must be
included explicitly; run-root accounting is not a total-task resource certificate.

All selected FFmpeg children, including spawned production workers, resolve the
frozen same-directory ffmpeg/ffprobe pair through an explicit worker PATH; command
records retain executable paths. Renamed tool fallback is refused. With **CPU-only
cells and no build receipt**, the suite permits an explicitly recorded local
build for the parent VM smoke and labels it CPU_SUPPLEMENTAL_UNPINNED. This is not
n9.0.2/WSL GPU qualification and is not accepted for a GPU matrix.

## Outputs and verification

Every successful master gets a strict complete software decode, dimensions,
codec/profile/alpha-layout check, exact count and rational nearest-timebase CFR
PTS check. Streaming validation retains frame/alpha hashes and edge/halo/temporal
and correctly composited difference metrics, never a whole decoded raw clip.
FFV1's source is the real production gray-mask finishing path compressed losslessly
before encode, not lossy ProRes or a376MB four-second RGBA file. F timers explicitly
include fixture decode+conversion+encode/container; fixture preparation, strict
validation and views have separate timings. Service timers wrap the actual
service call including production validation/publication, with external strict
validation excluded. Inclusive production phase spans are not additive partitions.

`views` runs after the timed matrix is terminal. It retains the actual transparent
native master, reuses a MOV as its comparison MOV, or creates a clearly labeled
comparison **PROXY** MOV for an MKV; that proxy does not prove native FFV1 Studio
compatibility. Separately validated opaque dark/light/checker MP4s use straight
alpha before dropping alpha. Full views default off to avoid redundant multi-GB
artifacts; changing that choice requires a fresh frozen manifest/envelope.

Numbered immutable JSON/CSV exports and an artifact-role/hash index include every
planned cell, retained failed/partial artifacts, selected tools/device/settings,
measurement route and timer boundaries, skips, pairs, validation and outstanding
visual/Studio status. Skipped/failed/unvalidated/reused/unknown measurements have
null throughput; no fresh observations are added by export. TECHNICAL_COMPLETE
means the technical matrix succeeded, not operator promotion. COMPLETE_WITH_SKIPS
and INCOMPLETE/HOLD cannot be reported as a fully exercised target matrix.

## Tests and current qualification boundary

```bash
python -m pytest -q tests/unit/test_wsl_experiment_suite.py
# Parent only, after media/capacity authorization, outside-Git pytest basetemp:
EWP_SUITE_MEDIA_TESTS=1 python -m pytest -q \
  --basetemp "$PRIVATE_TEST_ROOT" tests/integration/test_wsl_suite_cpu_flow.py
```

The integration test uses a synthetic0.1s6-frame source, CPU B/F0, real preflight,
compressed fixture, lossless oracle, views/proxy, resume/readback and artifact
mutation refusal. Its explicit32MiB growth envelope and10GiB reserve use real
production admission, not a mocked disk guard. It requires a clean committed
checkout. It does not exercise WSL/Vulkan, full/32 performance or Studio. Unit and
static checks alone never establish those runtime claims.
