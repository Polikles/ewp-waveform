# 25 — Opt-in experiment technical contracts

The sole operator startup, continuation and troubleshooting guide for WSL and
native Windows is [EXPERIMENTS.md](../EXPERIMENTS.md). Ordinary startup uses
`scripts/run_experiments.py`; the WSL command is a compatibility entry.
Do not assemble a session with lower-level builder/suite commands or edit a
manifest/source pin. Those interfaces are implementation/diagnostic helpers.

## Current portable workflow amendment — 0.6.0

Individual backend qualification precedes the timed matrix and optional failures
are isolated. Preserve the installed-tool CPU control and selected-build CPU
controls. New finite-Gaussian CPU-oracle/CUDA finishing is deliberately a different
algorithm from production FFmpeg recursive blur; transfer and algorithm controls
separate those variables. CPU ProRes remains an explicit encoding cost.
Native Windows uses platform-appropriate process-tree ownership, paths and
resource discovery rather than Linux `/proc`/pidfd assumptions.

Default short screening does not automatically rerender a complete reference.
Retain the real production32 multiprocessing route; full confirmation is a later
screen-qualified choice. Original and changed environments use different campaign
identities. Historical failed attempts, reported WSL reference and VM.1 actual
source/timer identities stay immutable. The older WSL implementation's contracts
below remain applicable to historical session recovery; its former all-GPU-preflight
failure fence is not the portable workflow's independent-backend policy.


This suite is experimental tooling, not a production GPU renderer/profile.
Production APIs, presets and defaults remain unchanged. VM tests do not establish
WSL/RTX3090 runtime qualification. Operator appearance assessment and actual
Resolve Studio native import/alpha/playback are independent promotion gates;
numerical metrics cannot approve output-changing profiles.

## Authenticated workload contract

`examples/experiments/vm-reference.json` preserves the complete resolved mapping7
appearance and historical full-media evidence. Explicit visual_noise 0.35 and
noise_seed 1729 are required, not reconstructed from defaults. Stock full renders
use 1400×280, 60 fps, transparent ProRes4444, balanced jobs2/threads0/chunk60 and
23,741 frames on the authenticated full source. The historically measured 0.2.1
full render remains historical: 318.452082 process / 318.095615 service seconds,
2,848,387,115-byte MOV. A separately versioned current VM reference names its real
source, timing and output hash; metadata added later does not relabel that source.

The driver discovers the clean current Git commit/tree and freezes interpreter,
dependencies, input hash, observed installed tools, selected tools, versioned
scenario order, settings and resource admission. Initial environment inventory is
captured before project environment selection or optional building and never
replaced by selected-tool observations.

## Distinct measurements

1. Installed-tool environment baseline: one stock full CPU render with the exact
   original default FFmpeg/ffprobe pair when production capabilities are available.
2. Selected-toolchain CPU controls: short CPU service and codec controls with the
   same build and WSL host used by GPU candidates.
3. GPU experiments: matched same-host/same-build pairs only.

VM.1 versus WSL is an environment reference, not isolated GPU acceleration.
Installed versus selected build is a toolchain contrast, not isolated acceleration.
Only known, fresh, successful, validated PROCESS records with matching workloads
and timer scope qualify for paired percentages; skips/failures/reuse have null
throughput. Sequential ABBA observations are descriptive, not significance claims.

| Scenario | Route and comparison |
|---|---|
| FULL | Actual unbounded stock service; reference recipe; real production pool2. |
| PRODUCTION32 | Stock service [25,57), 1,920 frames; actual pool2 above 1,800 threshold. |
| A / B | Original installed versus selected-build short CPU service; build contrast. |
| B / C | Same-build CPU versus gray upload/download before unchanged CPU finishing. |
| C / D | Same transfers; CPU blur versus mono Vulkan Gaussian sigma16,size97,planes1. |
| E0 / E1 | Common CPU finishing, yuva444p10le and alpha_bits16; CPU versus Vulkan ProRes. |
| F0 / F1 | Common compressed production-finished RGBA oracle; CPU versus GPU FFV1 codec package. |

Short analysis/normalization/EMA/causal history is interval-local, not a
full-context excerpt. Noise time origin is actual source start. Four-second cells
remain serial; jobs2 is a frozen workload factor, not a global CPU limit. No
VM eight-CPU cap is imposed on WSL. Hardware-dependent automatic threading and
actual sampled process observations are recorded separately from requested options.

## Tool provenance and capabilities

Suitable installed tools are not rebuilt. Observed installation provenance is
explicitly labelled OBSERVED_INSTALLED_TOOLS, never a fabricated pinned build
receipt. The optional internally managed separate-prefix builder uses FFmpeg
n9.0.2, commit `946fcce07b6dcd0331c8cc609192aeff5e1924f8`. It installs no prerequisites,
replaces no system tool, and installs no driver. Missing compiler/header/shader
prerequisites are collected before configure/build. Source, build and prefix
remain isolated outside the product checkout. A real build records source,
compiler, SPIR-V compiler, configure evidence and actual binary/library identities.

CUDA/WhisperX/NVENC success does not establish Vulkan. On WSL, real two-frame probes
at 64×32 and 1400×280 verify transfers, controlled blur, codec decoding/alpha/PTS
and the selected hardware device; software Vulkan devices are rejected. GPU media
probes are not run on a non-WSL VM. Missing advertised optional capabilities may
produce explicit skips; unknown options, malformed graphs, wrong devices,
timeouts, incomplete output and alpha/lossless violations are failures/HOLD.
No CPU fallback is silently labelled GPU success.

FFV1 requires every RGBA byte, including hidden RGB, to match its lossless oracle.
ProRes compares decoded alpha against the common 10-bit input, permitting at most
one input code step and preserving transparent/active extrema. Nonexact valid
quantization is assessment-pending, not alpha-exact. Blur/color changes remain
visual/Studio pending even when technically valid.

## Validation, costs and retention

Stock service timers include production validation/publication and exclude setup,
external strict checks and views. Codec timers include common fixture decode,
conversion/upload, encode and container. Fixture preparation, external verification
and derivative generation have separate costs. Inclusive phase spans overlap and
are not additive. Service CPU uses Linux self plus waited-child getrusage deltas;
sampled thread/RSS/process observations may miss transient peaks and are not a
complete process-tree peak measurement.

A byte-identical full MOV may reuse authenticated prior complete native-plane,
alpha and cadence validation after complete file SHA-256 authentication. Its
current service render/production validation and timing remain fresh; no new full
decode or historical retiming is claimed. Unexpected bytes retain their outputs
and get strict validation; do not tune/retry to force agreement. Other masters
receive strict complete software decode, exact dimensions/count and rational CFR
PTS checks. Streaming oracles avoid retaining full decoded raw clips.

Views retain native transparent masters and dark/light/checker MP4s. A MOV master
is its own comparison MOV; MKV may receive a labelled comparison proxy, which does
not establish native FFV1 Studio compatibility. Full views default off. Artifact
navigation groups equal SHA-256 values while retaining aliases. No global deletion
is performed; byte-identical media deduplication requires authenticated canonical
identity and the established scoped retention policy.

Immutable numbered JSON/CSV/Markdown exports include every planned cell, skips,
partial/failure evidence, paired eligibility, tools/device/settings, separate
costs, native/proxy/view roles and outstanding acceptance gates. The common driver
always prints its exact main report path, including preflight failures.

Safe resume is bound to one known directory and frozen source/input/tools/settings.
Exclusive locks prevent multiple owners. Only unattempted work is continued;
FAILED or uncertain STARTED attempts are retained and fence dispatch. Completed
readback is never another observation. Resource admission uses actual current
storage/RAM/cgroups, conservative per-kind peak estimates, finite attempts/time,
growth limits and reserve. Polling is not a kernel quota and may overshoot.

## Maintainer verification

`tests/unit/test_run_wsl_experiments.py` covers stdlib startup, discovery and common
workflow guards. Existing suite/probe/reporting tests cover frozen scenario and
oracle contracts. The opt-in `tests/integration/test_wsl_suite_cpu_flow.py` exercises
real CPU service/FFV1/preflight/views/resume and mutation refusal on a tiny synthetic
source; it is not full/production32/WSL/GPU qualification. Use the common driver
for actual original-input CPU smoke/reference execution. All test media/workdirs
must remain in admitted private locations outside Git.

The read-only `render_retained_export` helper can present an authenticated old JSON
snapshot without bypassing live session source guards. Such a report is explicitly
HISTORICAL / UNVERIFIED-MEDIA DIAGNOSTIC: JSON checksums alone prove neither trusted
ledger ancestry nor current media validity, and never authorize resume.
