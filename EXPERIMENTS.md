# Portable experiments — canonical operator guide

This is the maintained startup guide for WSL and native Windows. The package is
opt-in: production renderer defaults, output identities and accepted looks do not
change. GUI work and additional render styles remain future roadmap items; the
operator already has GUI graphic references.

## Start with one command

From a clean current `Polikles/ewp-waveform` checkout:

WSL:

```bash
python3 scripts/run_experiments.py --audio "/mnt/d/test-waveform/s0e00/s0e00-Damian.wav" --optimize --cuda --optimize-compact --max-growth-gib 6
```

Native Windows, in PowerShell:

```powershell
py -3 scripts/run_experiments.py --audio "D:\test-waveform\s0e00\s0e00-Damian.wav" --prepare-ffmpeg --optimize --optimize-async-depth 4 --optimize-ffv1-gpu --optimize-compact --max-growth-gib 6
```

No environment activation, exports, manifest editing or private startup documents.
Git, a Python bootstrap and available `uv` (or a pre-existing locked Python3.12
project environment) are prerequisites. WSL keeps its installed FFmpeg/ffprobe
baseline; Windows `--prepare-ffmpeg` explicitly permits isolated pinned acquisition
without requiring a preinstalled pair or replacing system tools.
The driver discovers/selects the locked Python3.12 project environment; if it is
missing it uses available `uv` for frozen isolated project setup. It does not
silently modify a global Python installation or borrow an STT/WhisperX environment.
A missing prerequisite is an actionable report, not an implicit driver installer.
The WSL command reuses the already verified CUDA preparation; it does not opt into
a CUDA download. Only append `--install-cuda` if a new private preparation is
actually needed. Omit `--cuda` for the CPU shortlist. No Linux NVIDIA display
driver, CUDA toolkit compiler or global Python dependency is installed.
The old `scripts/run_wsl_experiments.py` command remains a compatibility entry.

## Optimization scope and reading the results

`--optimize` is the new bounded speech25..29s shortlist, not a rerun of the historical
backend-discovery matrix. It compares actual direct ProRes versus FFV1 output,
separate encoder/filter-thread settings, and requested qualified Windows queue
settings. With `--cuda`, it adds separately qualified host-output, device-output,
batch1/2 and instrumentation-cost pairs. `--optimize-compact` adds separate fixed
output-crop and guarded earlier-finishing-domain pairs. Every shortlist pair uses
fresh AB/BA observations; production32/full are not automatically repeated.
`--full`/`--reference-only` cannot be combined with this shortlist.

Details, exact scopes, transfer sizes, crop placement and pending assessments:
[optimization first campaign](docs/notes/render-optimization-first-campaign.md).
Native FFV1 MKV and changed finishing/crops remain experimental, not native Resolve
Studio qualification. Use CPU/FFmpeg ProRes for ordinary asset production.

The operator's supplied four-second CPU, Windows Vulkan ProRes and WSL CUDA FIR
previews were accepted on2026-11-14, including contrasting-background frames.
[Recorded supplied acceptance and baselines](examples/experiments/operator-accepted-baselines-20261114.json)
are observations, not VM.1 target remeasurements. MP4 byte equality does not establish
MOV-master byte equality. No repeated reassessment of unchanged references is
needed; new outputs, full episodes and native experimental Resolve behavior remain
separate assessments. The small and padded Vulkan blur failures remain blocking.

`measurements-*.json` preserves compact complete critical phase/settings/transfer
measurements and precedes verbose/raw diagnostics in the2MiB ZIP. Oversized critical
exports refuse packaging explicitly instead of silently dropping comparison data;
raw ordered call records remain in the full report JSON. Service/pipeline time,
cold worker envelopes, external verification and MP4 generation remain separate.

## Missing uv / bootstrap Python 3.14 (first native Windows run)

The invoking Python only runs the stdlib bootstrap. Python 3.14 is not a supported
worker: the frozen application and CUDA closures require Python 3.12. `uv` selects
that interpreter and installs locked packages into private storage; it does not
upgrade the invoking Python, global site-packages, drivers or an STT environment.
Missing uv now reports the platform-specific install, why it is needed, a
**new-terminal** instruction and the exact quoted original rerun command.

In native Windows PowerShell, the explicit system-user tool prerequisite is:

```powershell
winget install --id astral-sh.uv --exact
```

Close and reopen PowerShell (existing terminals retain their old PATH), return to
the checkout, run `uv --version`, then rerun exactly:

```powershell
py -3 scripts/run_experiments.py --audio "D:\test-waveform\s0e00\s0e00-Damian.wav" --prepare-ffmpeg
```

Alternatively, **without changing PATH or global Python**, explicitly prepare the
isolated tool/runtime first (no audio, qualification or rendering):

```powershell
py -3 scripts/run_experiments.py --setup-only --setup-uv --prepare-ffmpeg
```

`--setup-uv` creates a new bootstrap venv and installs pinned `uv==0.12.6` from
PyPI (binary only, no dependencies, no global pip/cache). Its executable is hashed
and reused on subsequent commands without requiring activation or PATH changes.
This is an explicit network opt-in, not a hidden installer. It requires the
bootstrap Python's standard `venv`/`ensurepip` support. Failures retain the attempt
and commands; they do not repair a shared Python installation.

Linux/WSL's explicit uv tool prerequisite is:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a **new** shell, verify `uv --version`, and rerun the original WSL command.
The same `--setup-only --setup-uv` PATH-neutral alternative works on Linux/WSL.
See the official [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

## Preparation capacity is not render capacity

Before any acquisition the driver prints and retains `preparation-policy.json`.
`--setup-max-growth-gib` (default24) bounds **new** managed environment, wheel-cache,
interpreter and temporary allocation above its captured preparation baseline.
`--max-growth-gib` (default8) separately bounds campaign media/evidence. The
persistent store defaults to `OUTPUT_ROOT/managed-dependencies`; `--managed-root`
can place it on another filesystem, disjoint from campaign run/media paths.
The shared `--reserve-gib` (default10) protects free space on each relevant
filesystem, including evidence-only run/media locations when the managed store is
on another disk. Growth-accounting roots are separate from free-reserve roots.
Known campaign metadata is admitted before acquisition and monitored during setup;
separate preparation allowances cannot override an already-exceeded campaign cap.
These are configurable operator policies, not inferred VM RAM/disk
capacity or target-size measurements. The8GiB policy is for short screening, not
a prediction that any full render fits.

Admission occurs **before** downloads: conservative planning headroom is2GiB for
the application closure and16GiB Linux /10GiB Windows for CUDA wheels, extraction,
cache and an environment-copy fallback. A private uv bootstrap reserves256MiB;
FFmpeg uses the committed archive+expanded caps. Existing verified bytes do not
need fresh-install headroom. Estimates are not guarantees: live sampled disk/RAM
checks still stop work; they are not kernel quotas and may miss temporary peaks.
No CUDA download is attempted just because a CUDA flag was parsed.

Accounting reports **logical bytes** separately from **allocated bytes**. POSIX
uses allocated blocks, globally deduplicated by `(device,inode)` across cache,
environments, hardlinks and overlapping roots. It does not sum cache+environment
logical sizes independently (uv normally hardlinks these on one filesystem).
Where allocated-block telemetry is unavailable, including this implementation on
native Windows, the conservative logical fallback is explicitly labelled and
`allocated_bytes` is unavailable, not fabricated. Filesystem free-space change is
an independent observation, not equivalent to a namespace's logical byte total.

For a bounded, read-only accounting check (at most1,000,000 entries and `--timeout`
seconds), use the default output root, including old runs and managed storage:

```powershell
py -3 scripts/run_experiments.py --inspect-storage
```

For WSL the same inspection uses its own output root, not the Windows path:

```bash
python3 scripts/run_experiments.py --inspect-storage
```

Advanced placement: append multiple roots to measure their union with global
hardlink/overlap deduplication, rather than adding separate totals.

A bound/refusal never claims a partial total. The reported14,062,545,214-byte
supervisor growth versus roughly7.09GB filesystem-free delta has **not** been
reconciled on the target. Hardlink/overlap/logical accounting is a concrete reason
not to equate those numbers, not proof of this particular target's cause.

## Reuse preparations, not failed attempts

During active installation, uv can enumerate, rename and clean temporary
extraction trees while the supervisor accounts for their storage. A verified
disappearance of an enumerated descendant is an **incomplete observation**, not
proof of a capacity breach. The supervisor retains these samples, resamples with
a bounded policy and requires a complete final reconciliation after the owned
process tree stops. Observed growth, free-reserve and RAM violations still stop
work immediately, including a violation already visible in an incomplete sample.
Permission errors, unexpected I/O errors and loss of required persistent roots
remain global fail-closed errors; they are not ignored as installation churn.

`FAILED_STORAGE_OBSERVATION` / `GLOBAL_STORAGE_OBSERVATION` means accounting could
not establish usage. It is distinct from `REFUSED_RESOURCE_LIMIT` /
`GLOBAL_RESOURCE_ADMISSION`, which means an actual admission/limit check refused
work. A wrapper exit125 alone does not establish storage exhaustion. Preserve
`run-20261114T125421Z-13c9bb22` and `report-eb2e18b1b60f.md` unchanged: its reported
WinError3 under uv's temporary CPython extraction is not evidence of a disk or
budget breach. The source race is covered deterministically; native Windows
execution of the repair remains a target retry, not a Linux qualification claim.

From the updated clean checkout in the same native Windows PowerShell location,
first use this bounded setup/reuse check (no audio, qualification or rendering):

```powershell
py -3 scripts/run_experiments.py --setup-only --prepare-ffmpeg
```

Then collect the independent bounded preflight, without resuming the old run:

```powershell
py -3 scripts/run_experiments.py --audio "D:\test-waveform\s0e00\s0e00-Damian.wav" --prepare-ffmpeg --preflight-only
```

Use the same output/managed roots as before (repeat any previous explicit root
flags). Do not delete a valid old interpreter or environment to force the retry.

Managed environments are keyed by committed lock/recipe bytes, required Python,
platform, architecture and backend, then the verified interpreter bytes/version.
Every reuse rechecks installed RECORD payload hashes and the locked versions;
CUDA admission checks the **entire platform closure**, not just torch's version.
No installer is called on a matching reuse. Managed FFmpeg payloads are keyed by
the complete committed tool-lock hash and EXE/DLL verified on every acquisition
request. Neither case reuses old render timings or bypasses hardware qualification.

`--cuda --install-cuda` first checks the verified registry, then automatically
probes up to the eight newest retained candidates: legacy
`OUTPUT_ROOT/run-*/cuda-env` and matching managed setup-attempt environments,
including preparations left by failed campaigns. Runtime setup similarly checks
legacy `python-env` and managed attempts across older request keys. Older registry
pointers locate candidates only: cross-key candidates must pass native interpreter
identity and the current locked dependency/RECORD probe before a new receipt is
registered. Enumeration is bounded; candidates beyond the eight newest are not
implicitly considered verified. Only a successful independent dependency probe
registers a preparation; a failed/changed environment is not synced or repaired.
Use the same output/managed root across campaigns. Failed run events, setup
attempts and source evidence remain intact; new campaign IDs stay separate.

The key includes the complete `pyproject.toml` and `uv.lock`: even project-version
or dev-only recipe changes invalidate an exact-key match. A source commit change
alone does not. The recent startup repair commits through `7575a2f` have identical
recipe keys, so key invalidation is not established as the actual Windows cause
without its old receipt and selection logs. `<backend>-reuse-selection.jsonl`
now records search/miss/invalidation decisions. If a new environment really is
needed, the runner first searches the existing managed Python store offline;
an independently checked retained CPython3.12 is selected explicitly and Python
downloads are disabled. A newer available patch is not reason to reacquire it.
Changing output/managed roots can still hide prior preparations; repeat the same
root flags or explicitly select the retained environment rather than deleting it.

To automatically discover/verify a retained WSL CUDA preparation **without any
CUDA installation**, use (no audio or rendering):

```bash
python3 scripts/run_experiments.py --setup-only --cuda
```

`--cuda` alone also reuses a verified preparation during a new campaign. Normally
no environment paths need to be supplied. For a nonstandard existing placement,
`--verify-environment PATH --cuda --register-environment` performs the same
independent verification/registration without CUDA installation. Use the actual
platform's interpreter, never a Windows interpreter from WSL or vice versa.
Alternatively a new campaign can select an explicit placement using
`--cuda --cuda-python PATH` (never combine with `--install-cuda`). Dependency-only
verification writes a new `dependency-check-*` report outside the old run and
establishes **no CUDA device/runtime success**. A CPU-only Torch environment is not
a matching CUDA closure. Omit `--cuda` when verifying a normal application worker.

## Frozen optional tools and dependencies

The selected CUDA compatibility control is PyTorch2.9.1+cu128, not the latest
upstream release. The upstream release API observed v2.15.0 (2026-10-28), but the
selected official CUDA12.8 index directly supplied Python3.12 Linux x86-64 and
Windows x64 wheels for2.9.1. Both platform-specific full transitive closures are
committed with hashes under `requirements/`, constrained to the application's
existing `uv.lock` runtime closure. Startup reuses a freshly verified matching
managed preparation or installs a new private worker; it never re-resolves
dependencies or modifies an existing STT environment. It retains setup commands, timing and receipts.
The installer download may use several GiB; free-space/growth admission can refuse
it. Global disk/RAM/ownership refusal stops dispatch; ordinary optional dependency
failures remain distinct from independent CPU/Vulkan execution. `--cuda-python` can select an
existing isolated matching worker environment instead. CUDA driver/device/runtime
execution still must pass the actual qualification probe.

Native Windows `--prepare-ffmpeg` selects the retained BtbN monthly shared Win64 GPL
build `n9.0.2-39-g7adfbe40dc-20261031`, release `autobuild-2026-10-31-12-59`,
source `7adfbe40dcde598f93a6963d2f7b22cd75202ccc`. Its85,920,857-byte archive is
SHA256 `1d9823c35c7a7e2f54d1438cf61030d6efabe3278de01c191309d1e828bb74df`.
The provider digest and every installed EXE/DLL hash are frozen in
`src/ewp_waveform/ffmpeg/portable_ffmpeg_lock.json`; missing/changed assets fail
without switching to floating latest. The upstream FFmpeg download page observed
9.0.2 as current stable. Selected-build CPU controls are not replaced by the
installed baseline. Download/extraction/hash reuse were tested on VM.1; actual
Windows executable encoder inventory and GPU runtime probes remain mandatory.
Embedded encoder names in a PE file do not qualify the complete codec matrix.

Use `--ffmpeg PATH --ffprobe PATH` to select another existing same-directory pair
explicitly; the original installed baseline is still recorded separately. The
historical Linux `--build-ffmpeg` workflow is not the portable startup contract;
this package avoids an unbounded WSL graphics-stack/build repair campaign.

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
`--repeats` defaults to2 and accepts even values2–10: the speech shortlist uses
sequential AB then BA (two fresh observations per side by default). Onset, quiet
and tail algorithm/qualified-backend screens run once per side and are labelled
n=1, not repeated-performance evidence. `--no-production32` explicitly omits the
stock pool2 check; short serial outputs do not replace that evidence.
`--full` is an explicit later stock-CPU full confirmation, never an automatic
rerender after a report/wrapper change. `--reference-only` selects the installed
CPU build for its explicit full reference after shorts.
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
policy, storage and encoder settings within pairs. Stock service attempts select
a fresh task-owned analysis-cache directory per observation; actual hit/miss data
remain observations (some routes may not use that cache). Custom FIR/FFmpeg-raster
algorithm controls explicitly disable their analysis-cache hooks. Do not call
an intended cache selector an observed hit or subtract overlapping timings.
Short speech, onset, quiet and
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

## 64×32 blur failures and independent backend results

The operator's November 14, 2026 native Windows preflight selected the RTX 3090:
transfer, ProRes, FFV1 and same-build checks passed; NumPy finishing succeeded.
Blur's aggregate failed, but its 1400×280 case passed (maximum code error1,
mean0.0010102040816326531; unchanged limits maximum2 and mean0.6).
Those are reported target observations, not a remeasurement by this checkout.

The finite-kernel reference was independently checked against a scalar sum and
actual software-Vulkan execution at both sizes. No reference arithmetic defect
was demonstrated. The pinned shader uses storage-image reads without clamping tap
coordinates; with radius48, the64×32 probe crosses boundaries everywhere. This is
a source-level boundary hazard, **not proof of the actual RTX driver behavior**.
The target's64×32 output is still needed to distinguish implementation/driver
boundary behavior from other target-specific problems.

The runner keeps every geometry's verdict and now records per-frame/spatial
metrics, byte lengths, differences and tolerances. A failed64×32 numerical check
also runs one bounded160×128 padded/cropped diagnostic. A passing diagnostic does
not replace the original result, relax limits, or qualify an unpadded workload.
Any real failing requested geometry still blocks blur. Independently passing
transfer/ProRes/FFV1 and finishing routes remain eligible; they are not suppressed
because blur's aggregate failed. A global resource or unverified process-ownership
condition is a separate explicit stop, never labelled an optional backend failure.

To collect the new target diagnostics using existing valid preparation, start a
new bounded preflight (do not resume or edit the old failed run):

```powershell
py -3 scripts/run_experiments.py --audio "D:\test-waveform\s0e00\s0e00-Damian.wav" --prepare-ffmpeg --preflight-only
```

The same selected build is reverified/reused when available. The existing legacy
run-local FFmpeg preparation is also eligible for verified reuse; no new download
is required when its complete pinned payload is valid.

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
The entire effective inherited worker environment is authenticated with an aggregate
hash (values are not serialized); it is not limited to named CUDA/BLAS selectors.
Even an unlisted NumPy/Python flag or another inherited value change refuses reuse.
Only shell `_`/`SHLVL` bookkeeping is dropped from workers. Fixed worker Python-path
and bytecode overrides, selected-tool PATH and per-attempt cache staging remain
explicit transformations. A different terminal/session can therefore require a
new campaign if its effective inherited environment differs.
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

## Qualification boundaries still pending

The operator reports that P/main `7575a2f4cabc83d1269b3d80246b7698e631abad`
reused the retained WSL CUDA environment without installation, executed on the
RTX3090, and passed all10FIR oracle cases at64×32 and1400×280 with zero alpha-byte
and composite-byte error (`report-92946a5906ee.md`). These are reported target
results, not a remeasurement on VM.1. The bounded WSL CUDA timing campaign may
proceed independently: neither Windows bootstrap nor Windows/WSL Vulkan repair
is its prerequisite. Do not use `--full` to request CUDA timing; it remains the
stock CPU full route. Preserve the independent WSL Vulkan failure.

VM.1 cannot establish CUDA or native Windows GPU success. Native Windows Job
Object kernel behavior, selected executable codec inventory, actual NVIDIA Vulkan
runtime, Resolve import/alpha/playback and operator visual assessment require the
target machine. Acquisition/hash readback and static/mocked Windows tests are
not hardware qualification. The upgraded operator WSL release and actual dzn
capabilities also remain unknown until its new preflight runs.

The CUDA finisher remains bounded to32seconds per prototype render. Its new
batch1/2/output/timing variants are explicit optimization experiments; their target
performance and full-source CUDA confirmation remain pending. `--full` is a
stock CPU route, not a way to relabel a CPU full render as GPU confirmation.
No CUDA hardware is exposed on VM.1, so the existing full reference is reused
as reference metadata rather than repeated for a wrapper/report change.

## Existing VM.1 reference and platform choice

[Current full VM.1 reference](examples/experiments/vm1-current-reference.json):
stock FFmpeg8.0.1,23,741frames1400×280/60transparentProRes4444;
service304.7343798769998seconds. MOV SHA256
`00652a1b5255b8c1cbe0bc82381bd151f7e56d2b3aecfe87683d25ed3d79da78`.
Service timing is distinct from worker envelopes and external verification/viewing.
The older WSL control differs in platform and FFmpeg build, so it cannot isolate
platform performance or predict CUDA/native Windows gains.

Use the CPU/FFmpeg ProRes route for ordinary production regeneration. Supplied short
WSL CUDA and Windows Vulkan ProRes previews are accepted; their new optimization
variants and experimental native Resolve behavior still need qualification. Choose
the eventual platform from actual cold end-to-end timings, usable transparency,
Resolve compatibility, operational friction and maintenance cost. VM.1 CPU tests,
static Windows tests and mocked devices do not establish native Windows/GPU success.
