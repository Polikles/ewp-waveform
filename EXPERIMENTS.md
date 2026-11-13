# Portable experiments — canonical operator guide

This is the maintained startup guide for WSL and native Windows. The package is
opt-in: production renderer defaults, output identities and accepted looks do not
change. GUI work and additional render styles remain future roadmap items; the
operator already has GUI graphic references.

## Start with one command

From a clean current `Polikles/ewp-waveform` checkout:

WSL:

```bash
python3 scripts/run_experiments.py --audio "/mnt/d/test-waveform/s0e00/s0e00-Damian.wav"
```

Native Windows, in PowerShell:

```powershell
py -3 scripts/run_experiments.py --audio "D:\test-waveform\s0e00\s0e00-Damian.wav"
```

No environment activation, exports, manifest editing or private startup documents.
Git, a Python bootstrap and a working FFmpeg/ffprobe pair must be available.
The driver discovers/selects the locked Python3.12 project environment; if it is
missing it uses available `uv` for frozen isolated project setup. It does not
silently modify a global Python installation or borrow an STT/WhisperX environment.
A missing prerequisite is an actionable report, not an implicit driver installer.
The old `scripts/run_wsl_experiments.py` command remains a compatibility entry.

The authenticated original WAV is 37,985,180 bytes, 395.6785 seconds, SHA256
`e7088a3dfdfc12323acbc2d4f9d4c0af304b95eaabfe80e45becbcf7bb16348b`.
Audio and generated media remain local, outside Git. A local WSL copy is allowed:
pass its path once and retain that same verified placement for every paired case.
Do not compare WSL `/mnt/d` and Linux-local storage as if only the GPU changed.

## Qualification before costly execution

Startup captures the original Python, PATH, OS release, tools and resources before
environment or managed-tool selection. Original and selected FFmpeg are separately
identified by absolute path, version and executable hash. Guest CPU affinity,
available RAM and limits are observations; host physical RAM is not guest RAM.

Each optional backend must pass its own bounded execution probes before admission.
Vulkan records device/API/extensions/format properties and tests actual transfers,
compute and alpha-capable codecs at small and production geometry. Software
llvmpipe/lavapipe is never counted as GPU. PyTorch CUDA availability, device
enumeration and encoder listings are observations, not execution qualification.
Missing capability, malformed command, execution failure and numerical failure
remain distinct. Exact argv, stderr and explanatory excerpts are retained.
A failed optional backend must not prevent an independent CPU control or another
qualified backend. No silent CPU fallback.

Use `--preflight-only` for a small diagnostic campaign without the timed matrix.
Use `--cpu-smoke` without audio for the tiny synthetic workflow; it is not an
original-input result, a production32 measurement or hardware qualification.
Other optional flags are listed by the same entry point's `--help`.

## What comparisons mean

- Installed CPU: the original system FFmpeg control, not silently upgraded.
- Selected-build CPU: the same FFmpeg pair as the corresponding Vulkan scenario.
  Installed-versus-selected is a build contrast, not GPU speedup.
- Vulkan transfer: production finishing plus upload/download overhead.
- Vulkan blur: GPU halo computation with transfers, qualified independently of codecs.
- Vulkan ProRes: matched CPU/GPU encoder settings on the same selected build, only
  when that executable actually supplies and executes the required Vulkan encoder.
- Vulkan FFV1: lossless codec comparison using a common production-derived fixture;
  preserve hidden RGB and alpha. FFV1 MKV is not assumed natively usable in Resolve.
- New-algorithm CPU oracle: separable finite Gaussian finishing with an explicit
  different algorithm contract from FFmpeg recursive `gblur`.
- CUDA transfer-only: GPU round-trip and staging without replacing finishing.
- CUDA finishing: the same new algorithm as the CPU oracle, with conversions,
  staging, upload, compute and download included. CPU ProRes still encodes the result.
- Production32: actual stock application multiprocessing route, not a proxy codec loop.

Changing FFmpeg build, platform, storage or several pipeline stages is labelled as
such. The new algorithm versus stock FFmpeg is an algorithm comparison; CPU oracle
versus CUDA isolates its execution backend. A combined pipeline comparison is not
an isolated kernel or encoder speedup. Native Windows is a genuine alternative to
WSL/Dozen, not just an OS label on a Linux-only command.

## Timing and screening

Keep fixed source, clip bounds, settings, geometry1400×280, cadence60fps, cache
policy, storage and encoder settings within pairs. Short speech, onset, quiet and
tail screens precede expensive full confirmation. A clip called quiet is not proof
of exact digital silence; synthetic all-zero qualification is separate.
Keep sequential counterbalanced repetitions and report sample counts and spread,
not the best repetition. GPU synchronization must bracket measurements; CUDA
imports/context/warm-up are not hidden from cold cost. Batching is a separate
explicit experimental variable, not folded into the batch1 backend claim.

Service wall surrounds the actual application render/validation/publication call.
Worker/process envelopes include additional startup. Environment preparation,
imports/context creation, transfers/conversions, steady processing, encoding,
external verification and previews have separately labelled costs. Inclusive
spans are non-additive. Cold end-to-end cost matters because these assets are
temporary and regenerated; a fast steady kernel alone is insufficient.

Default screening does not repeat the complete original-input reference merely
because this driver or a report changed. Full-source confirmation follows useful
qualified short candidates and explicit resource admission. The portable historic
VM reference remains measured source `81afcb46c339587b53700ef47c03f0e4361047ac`,
not a later wrapper commit.

## Review output and acceptance

The driver prints its exact main Markdown report path even after partial failure
when storage is writable. The report includes the actual failure reason and
relevant stderr excerpt, original/selected identities, each scenario's backend,
costs, correctness status and concise hash-deduplicated visual navigation.
Return the main report and the small diagnostic bundle of relevant JSON/text
logs. Do not send the WAV, multi-GB media, credentials or an entire environment.

Useful distinct output-changing candidates retain their native transparent output,
a short transparent comparison MOV when the native container differs, and correctly
composited opaque MP4 previews on contrasting backgrounds. Identical native outputs
share review navigation. Ordinary players that discard alpha are not appearance
oracles. Check halo edges, lower reflection, horizon, silence and usable straight
alpha; hidden RGB can matter independently of visible composites.

Byte-identical faster MOVs remain preferred technical-integration candidates after
applicable review. Output-changing algorithms stay opt-in until operator visual
assessment and native Resolve Studio import, alpha/compositing and playback
acceptance. Numerical metrics support assessment, never approve appearance.
No new production output profile is promoted by this package.

## Safe continuation and new campaigns

Use `--resume` with the exact printed run path. Unchanged completed successful
sessions are authenticated and read back without retiming renders. Source,
environment, input, tools, frozen settings and retained output identity must match.
Failed or uncertain started attempts are preserved, not automatically rerun.
Use a new explicitly identified campaign after environment/source/tool changes.
Do not edit an old manifest, erase failure markers or move media behind a resume.

In particular, preserve the original operator campaign `run-20261113T155324Z-6296beff`
and its successful CPU reference plus later failed GPU preflight. The upgraded
WSL environment is a different campaign, not recovery by rewriting history.

## Actual operator observations and unresolved WSL issue

[Portable operator evidence](examples/experiments/operator-wsl-history.json) records
reported results, not VM.1 remeasurements. On WSL Ubuntu24.04 and system
FFmpeg/ffprobe6.1.1-3ubuntu5, full CPU service wall was377.193828seconds; separate
external verification168.174019seconds. The23,741-frame1400×280/60 MOV hash is
`cd7cb383df63e7f4f933d620c2abf92db387de2276c15313ac68baac2d30bafb`.
GPU preflight then failed because only software llvmpipe was exposed.

The operator subsequently described Ubuntu as “26”; its exact release remains
unknown until the new target inventory captures `/etc/os-release`. Do not assume
26.04 or26.10. System FFmpeg8.0.1 now lists `ffv1_vulkan`, but not
`prores_ks_vulkan`. RTX3090 selection succeeds through Microsoft Direct3D12/Dozen,
yet gray64×32 and RGBA1400×280 upload/download stop before output frames:

```text
Device 0 selected: Microsoft Direct3D12 (NVIDIA GeForce RTX 3090)
auto-inserting filter 'auto_scale_0' ... before Parsed_hwupload_0
Impossible to convert between the formats supported by the filter
'graph -1 input from stream 0:0' and the filter 'auto_scale_0'
Task finished with error code: -38 (Function not implemented)
frame=0
WARNING: dzn is not a conformant Vulkan implementation, testing use only.
```

This establishes failed negotiation/execution, not a demonstrated hardware-speed
result. A mismatch between FFmpeg requirements and actual dzn format capabilities
is a hypothesis, not an established root cause. Compare exact device API version,
extensions, format features and image-usage support with the selected FFmpeg
build's requirements. Do not infer support from Mesa's global version or assume
newer FFmpeg alone fixes it. No Linux NVIDIA display drivers are installed in WSL,
and this task does not attempt an unbounded graphics-stack repair.

## Existing VM.1 reference and platform choice

[Current full VM.1 reference](examples/experiments/vm1-current-reference.json):
stock FFmpeg8.0.1,23,741frames1400×280/60transparentProRes4444;
service304.7343798769998seconds. MOV SHA256
`00652a1b5255b8c1cbe0bc82381bd151f7e56d2b3aecfe87683d25ed3d79da78`.
Service timing is distinct from worker envelopes and external verification/viewing.
The older WSL control differs in platform and FFmpeg build, so it cannot isolate
platform performance or predict CUDA/native Windows gains.

Use a working CPU route for immediate production regeneration. WSL CUDA and native
Windows Vulkan are candidates to measure, not winners selected in advance. Choose
the eventual platform from actual cold end-to-end timings, usable transparency,
Resolve compatibility, operational friction and maintenance cost. VM.1 CPU tests,
static Windows tests and mocked devices do not establish native Windows/GPU success.
