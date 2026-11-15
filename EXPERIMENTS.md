# Portable experiments — canonical operator guide

This is the maintained startup guide for WSL and native Windows. The package is
opt-in: production renderer defaults, output identities and accepted looks do not
change. GUI work and additional render styles remain future roadmap items; the
operator already has GUI graphic references.

## Current one-file commands

The supplied November15 Windows production MOV **imported and displayed correctly
in Resolve Studio**, per the direct user. The separate WSL RTX3090 combined-CUDA
control campaign is **COMPLETE**; do not rerun it as the next task.
[Curated evidence and exact acceptance limits](docs/notes/refined-ribbon-target-evidence-20261115.md)
retain the reported settings, source JSON hashes and results. Windows producing
commit/whole-MOV hash remain unknown; acceptance is import/display only.

The matched short campaign on clean P4326f8e and the subsequent full-source
confirmation on clean P43682ff are both **COMPLETE**. Report `cf7c9a5277e5` admits
one fresh CPU then CUDA pair, n=1/side AB, not counterbalanced: service
134.836780 / 161.968311s; cold worker176.112998 / 203.427444s. Both validated all
23,741frames. These are whole-pipeline observations with different finishing
algorithms, not medians or isolated kernel acceleration. Costs overlap.
[Completed evidence, exact identities and practical selection](docs/notes/refined-ribbon-cpu-selection-20261115.md)
close this style/workload pass around the usable CPU path. **Do not rerun shorts,
the full pair or another benchmark campaign to close this pass.** No CUDA promotion
or new Resolve review is requested; its full native assessment remains pending.

For ordinary production of this saved refined-ribbon look, use CPU on native
Windows. From the updated checkout in PowerShell, reusing prepared tools/runtime:

```powershell
py -3 scripts/render_refined_ribbon.py --audio "D:\test-waveform\s0e00\s0e00-Damian.wav"
```

The ordinary production helper uses a fresh timestamp/random output directory and
the committed exact visual/serial-LUT settings described below. It is not an
experiment campaign and does not acquire dependencies/tools. The experimental
runner remains the single entry for all qualification/comparison/preparation work.
No environment activation, exports, manifest editing or private startup documents.
For experiment preparation, Git, a Python bootstrap and available `uv` (or a
pre-existing locked Python3.12 project environment) are prerequisites. Ordinary
production requires already prepared tools/runtime and never invokes `uv`.
WSL keeps its installed FFmpeg/ffprobe
baseline; Windows `--prepare-ffmpeg` explicitly permits isolated pinned acquisition
without requiring a preinstalled pair or replacing system tools.
The driver discovers/selects the locked Python3.12 project environment; if it is
missing it uses available `uv` for frozen isolated project setup. It does not
silently modify a global Python installation or borrow an STT/WhisperX environment.
A missing prerequisite is an actionable report, not an implicit driver installer.
The WSL comparison reuses already verified CUDA preparation and does not opt into
a CUDA download. Do not append `--install-cuda` or turn this narrow comparison into
the earlier CPU shortlist. No Linux NVIDIA display driver, CUDA toolkit compiler
or global Python dependency is installed.
The old `scripts/run_wsl_experiments.py` command remains a compatibility entry.

## Explicit full-source confirmation — 2026-11-15

**Completed historical interface/policy, not a next-run request.** The operator
completed report `cf7c9a5277e5`; see the [separate closeout](docs/notes/refined-ribbon-cpu-selection-20261115.md).
The opt-in interface and its safeguards remain available, but no repeat is needed.

`--compare-cpu-cuda-full` is a separate standalone opt-in, not `--full` appended to
the short command. It requires `--cuda` and explicitly supplied growth/reserve
limits of at least12GiB/10GiB. It excludes smoke, other campaigns, setup-only,
preflight and replay overrides. One independently qualified CPU-LUT control A runs
first, followed sequentially by one independently qualified CUDA candidate B in
separate fresh workers, both in the selected retained CUDA interpreter. No short
campaign, repeat or hidden GPU warmup precedes these full renders. Qualification
subprocesses do not share their CUDA context with render workers; each render
still pays its own lazy initialization and per-encode qualification.

Freeze source, interpreter, selected FFmpeg/ffprobe, original input hash, saved
`iuris-ribbon-refined-production` appearance, output filesystem and identically
disabled analysis cache. Both requests use `start=None,duration=None`: independent
complete-source normalization and causal history from source origin through EOF,
not assembly of separately analyzed intervals. The input is the authenticated
395.6785s mono PCM16/48kHz WAV. Expect23,741frames,1400×280/60fps, silent
straight-alpha ProRes4444. CPU remains recursive FFmpeg blur with qualified LUT;
CUDA remains FIR/device-RGBA8/batch2/ordinary timing. No new algorithm, tune matrix,
cross-algorithm finished-pixel identity or historical master hash is imposed.

The12GiB growth policy explicitly admits3GiB control +3GiB candidate +3GiB
simultaneous temporary work +1GiB logs/verification +2GiB headroom. Existing
preparations are baseline storage, not permission for another download. Admission
checks actual output/evidence filesystem placement and the configured10GiB free
reserve before bootstrap; with one shared filesystem this requires at least22GiB
free at admission. These allowances are conservative planning, not a predicted
file size or guaranteed continuous quota. Existing sampled growth/reserve checks,
process-tree supervision and terminal/report checks remain enabled. An impossible
budget refuses rather than bypasses policy; the old6GiB short limit is rejected.

The external verifier completely software-decodes each MOV independently, checks
all-frame content alpha/count, cadence and timestamps, and verifies the single
video stream has no audio. CUDA additionally validates every batch index/live
prefix:11,870full pairs and final one-frame batch at zero-based frame23,740,
11,871calls total. Iterator order is explicit, separately from decoded PTS; tiny
CPU-Torch fixtures exercise ordinal content and borrowed-buffer behavior. This is
not an independent full CUDA pixel oracle. Each new output receives its own
observed file/decoded hashes; repeat-reference and pre-encode ProRes-losslessness
proofs remain unavailable, not fabricated.

Report actual n=1 service and cold-worker wall per side, descriptively. Service
includes lazy imports/context, per-encode qualification, normal validation and
publication; cold-worker time also includes preplanning and complete external
verification. Extra diagnostics are non-additive and never replace/subtract from
complete costs. Parent bootstrap, identity guards and report export remain outside
those per-worker timers. Do not fit a crossover from the completed4/32s results,
require a warmed context or compare the accepted Windows89s job observation as a
matched WSL/OS benchmark. No winner is established before target execution.

Default retained paths (the actual UTC/random token is printed):

- `~/.local/state/ewp-portable-experiments/media-TOKEN/compare-cpu-cuda-full-r01-A/output/s0e00/*.mov`
- corresponding `compare-cpu-cuda-full-r01-B/output/s0e00/*.mov`
- `~/.local/state/ewp-portable-experiments/run-TOKEN/reports/report-ID.md`
- same reports directory: `report-ID.json`, `measurements-ID.json`,
  `report-ID-diagnostics.json`, command companion and optional diagnostic ZIP.

No full MP4 views are automatically produced. Keep both native MOVs locally; no
audio/MOV upload to VM.1 or ChatGPT. Return `report-ID-diagnostics.json` (complete
JSON even if the bounded ZIP refuses), preferably with Markdown and measurements.
Packaging outcome is separate from render outcome. If CUDA shows a worthwhile
complete-cost advantage, assess its retained native output in Resolve before
promotion. Otherwise retain CUDA experimental and finish this single-file style
pass around the already accepted Windows CPU workflow. Do not re-request review
of unchanged accepted CPU assets. GUI, more styles/backends and a convenient
one-command multi-file procedure remain deferred; separate mono recordings need
separate waveform assets, not speaker mixing or diarization.

## Current CPU/CUDA service comparison scope — 2026-11-15

The following short4/gated32 interface is retained unchanged for replay, not the
next task. Its supplied RTX3090 run is complete; see the linked target evidence.
It selects only two four-observation sequences:

| Interval | Frames | Serial-service order | Observations |
|---|---:|---|---:|
| source[25,29) | 240 | CPU,CUDA,CUDA,CPU (ABBA) | 4 |
| source[25,57) | 1,920 | CPU,CUDA,CUDA,CPU (ABBA) | 4 |

Total when independently qualified and short gates pass:8 actual `service.render`
observations, n2/side/interval; qualification and separate views/verification are
additional stages, not render observations. A failed CUDA qualification still
permits fresh CPU short controls in the same selected interpreter, but blocks the
matched32s stage. CPU is the existing jobs1/serial qualified-LUT encoder with
FFmpeg recursive blur. A scoped service adapter disables analysis caching and
hashes original raster bytes identically on both sides. It enables CPU LUT at the
encode hook: the ordinary performance result flag remains false (the normal API
forbids combining that flag with an experiment adapter); the experiment identity,
`lut_setup` and actual per-encode qualification record the effective LUT selection.
No ordinary service guard is relaxed. CUDA is the completed combined
device-RGBA8/batch2/ordinary FIR candidate. Both sides use the **same selected
CUDA-capable Python and FFmpeg**, original input, complete saved production preset
appearance and automatic CPU ProRes encoder-thread policy.
Analysis cache is disabled identically, analysis/normalization is interval-local
per interval, and source bounds/frame counts must be checked before rendering.
This is an intentional **recursive CPU versus FIR CUDA algorithm/workflow contrast**,
not a backend-only or cross-algorithm byte-equality experiment. Require independent
structural/alpha/cadence/source checks and retain side-by-side appearance evidence;
no cross-algorithm exact pixel oracle is imposed. Same-contract controls keep their
existing exact checks. Ordinary production helper/appearance/defaults do not change.

Measure startup/import/context inside each service, per-encode qualification,
validation and publication. Report cold launch-through-exit separately from service;
external strict checks, preplanning and views have separate scopes. Do not compare
these timers with the supplied Windows89s job timestamps. Preserve verified
preparation reuse, ownership/resource refusal and immutable failed-run evidence;
no dependency acquisition or old CPU/CUDA control campaign replay is requested.
Do not append `--optimize`, `--optimize-single-file`, `--cuda-combined`, `--full`,
`--reference-only` or unrelated backend flags to the current command.

Return the printed `report-ID.md`, `measurements-ID.json`,
`report-ID-diagnostics.json`, and the diagnostic ZIP if packaging succeeded.
Do not return audio or multi-gigabyte MOVs. If ZIP packaging refuses, return the
separate intact JSON companions; packaging refusal is not render failure.
First CPU/first CUDA external checks are standalone; their repeats compare only
against their own side. Original-raster SHA-256 work is included on both sides;
CUDA also retains its existing pre-encode RGBA digest. Those observations are not
subtracted from service wall. Cross-algorithm byte identity is never required.

A full control/candidate comparison now has the separate explicitly admitted
[full-source confirmation mode](#explicit-full-source-confirmation--2026-11-15).
The6GiB short limit remains insufficient and is never silently reused for it.
Native experimental Resolve acceptance remains independent. A later convenient
one-command procedure for several selected mono recordings is backlog only:
separate mono tracks produce separate assets, not speaker separation, composition,
a scheduler or GPU-throughput matrix. GUI and other styles remain outside this task.

## Historical optimization campaigns and reading the results

The recipes in this section are retained replay/reference interfaces, **not the
current next command**. Closed supplied campaigns must not be repeated just to
replace evidence. [November15 target evidence](docs/notes/refined-ribbon-target-evidence-20261115.md)
additively supersedes former unmeasured/native-target-pending statements below.

[Exact CPU work reduction and retained negative experiments](docs/notes/single-file-cpu-work-reduction.md)
records the current incremental VM.1 evidence. The short gains are not additive;
the combined32s service reduction is modest, not another stock-to-LUT result.

`--optimize-single-file` is the retained targeted campaign on its **selected source**,
not an old-source/new-source comparison or another codec/filter matrix. It runs
direct GEQ/LUT speech25..29s AB/BA (including the repaired Windows direct seam)
and separate serial-service GEQ/LUT speech AB/BA, then independently compares
jobs2/jobs1 GEQ service32 and jobs1 GEQ/LUT service32 at25..57s. It explicitly
authorizes these bounded32s cells, never a full episode. With `--cuda`, it also runs
the new combined FIR candidate through matched **actual serial application service**4s
then32s AB/BA. Defaults give16 CPU renders plus8 CUDA renders when requested; preparation,
qualification and separate deduplicated views are additional stages. A failed LUT
gate does not suppress GEQ worker-policy or independently qualified CUDA checks.
Omit `--cuda` for the targeted CPU campaign. Existing verified preparations are
reused through the same runner; no new CUDA installation is requested.

Historical WSL CUDA-only control recipe (closed; not the next command):

```bash
python3 scripts/run_experiments.py --audio "/mnt/d/test-waveform/s0e00/s0e00-Damian.wav" --cuda --cuda-combined --cuda-combined-service32 --max-growth-gib 6
```

Omit `--cuda-combined-service32` for short-only. Both sides use actual jobs1
`service.render`, unchanged source analysis/raster, CPU ProRes encoder and normal
validation/publication. Control retains host-reuse/batch1/diagnostic; the combined
device-RGBA8/batch2/ordinary candidate is now measured in the supplied
[November15 COMPLETE campaign](docs/notes/refined-ribbon-target-evidence-20261115.md).
Import/context/setup and
per-encode qualification are inside service wall; external preplan, independent
verification and views are separate, and cold launch-through-exit remains visible.
These are not historical pipeline-only denominators or an additive combination of
earlier speedups. The32s CUDA route is an explicit serial FIR service experiment,
not stock pool2 production32. Exact raster, pre-encode RGBA and decoded RGBA checks
gate matched cells; failed/incomplete shorts block the dependent32s CUDA stage.
[Candidate rationale and CPU-only exercise](docs/notes/single-file-combined-candidate.md).

`--optimize` is the new bounded speech25..29s shortlist, not a rerun of the historical
backend-discovery matrix. It compares actual direct ProRes versus FFV1 output,
separate encoder/filter-thread settings, and requested qualified Windows queue
settings. With `--cuda`, it adds separately qualified host-output, device-output,
batch1/2 and instrumentation-cost pairs. `--optimize-compact` adds separate fixed
output-crop and guarded earlier-finishing-domain pairs. Every shortlist pair uses
fresh AB/BA observations. `--optimize-service32` additionally compares actual
serial jobs1 GEQ/LUT service at25..57s. Per-encode qualification/setup/publication
is included. This adds4 native32s renders (not a ProRes transcode); omit that flag for short-only
screens. Serial records are not the stock jobs2 production32 route. The current
VM.1 jobs2 LUT screen is neutral/slower; the explicit serial `ribbon-lut` profile
is useful. Full-source execution is never silently admitted by this flag.
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
exports refuse **packaging**, not rendering: usable Markdown, the full report JSON
and the separate critical measurements JSON remain authoritative and linked. The
report records `packaging.status` independently of the original render status/error;
a partial/failed ZIP is never advertised as a usable packet. Packet snapshots are
captured before the final packaging outcome; consult the final on-disk report.
Raw ordered call records remain in the full report JSON where originally captured.
Service/pipeline time, cold worker envelopes, external verification and MP4
generation remain separate.

For report-only recovery from retained full report, diagnostic or measurements
JSON (up to64MiB), without environment setup, media access, rendering or resume:

```bash
python scripts/regenerate_experiment_report.py --records /path/to/measurements-ID.json --output /path/to/new-report-recovery
```

The output directory must be new. Originals/failures are untouched, recovered
records are labelled REUSED/not revalidated, and source path/hash plus an exact
`retained-records.json` copy are retained.
Compact/excerpted records cannot reconstruct absent raw calls, commands or logs.
This also works with native Windows paths/`py` in the same checkout.

Direct LUT's selected-tool guard accepts alternate path spellings only when the
host filesystem confirms they identify the same file (for example `.exe`/`.EXE`
on Windows); it never trusts a matching basename, case-folded path or copied bytes.
Single-input/output and exact finishing-geometry guards remain strict. Linux
identity-predicate replay is not native Windows qualification.

For direct native FFV1, `lossless_against_preencode: null` with
`preencode_losslessness_proof.status: NOT_PERFORMED` means that invocation did not
capture an independent finished pre-encode RGBA oracle—not that FFV1 failed a
losslessness comparison. The lossless codec contract, decoded structural validation,
lossy MOV contrast and exact reference-master comparisons are distinct. A tiny
software-FFmpeg regression compares the same finished masks through raw RGBA and
FFV1/decode, including hidden RGB and fractional alpha; it does not retroactively
prove any retained full/direct run or establish native Windows/NLE acceptance.

## November15 bootstrap repair and retained CPU evidence

The supplied WSL run `run-20261115T095928Z-fb528a5f` failed after sixteen CPU
renders and before CUDA. The source defect is reproduced: the dependency-light
bootstrap imported `single_file_campaign -> cuda_combined_experiment ->
render_fixed -> analysis.spectrum -> numpy`, despite populated selected CPU/CUDA
workers. Rendering imports now stay behind worker-only methods/type checking.
No global NumPy installation, working-environment rebuild or CUDA download is the
repair. Future bootstrap/worker failures retain the full chained traceback, failing
stage/frame and actual interpreter executable/version/prefix. The old report did
not retain its original traceback/bootstrap identity; reproduction evidence is
separate, not an invented historical stack.

Original FAILED/SALVAGED_UNVERIFIED records and n=0 statistics remain unchanged.
The bounded supplied ZIP omits original events/requests/results/media and contains
only compact config, so it cannot authenticate these historical outputs on VM.1.
If the full quiescent original run and indexed media remain on WSL, independently
verify their retained exact bytes without resume, rendering, decoding, environment
setup or a current-source equality requirement:

```bash
python3 -S scripts/authenticate_retained_success.py --run "/home/linuch/.local/state/ewp-portable-experiments/run-20261115T095928Z-fb528a5f" --output "/home/linuch/.local/state/ewp-portable-experiments/recovery-cpu-auth-r01"
```

The output directory must be new. This verifies the sealed config, complete event
hashchain, unique request/terminal joins, process exit/shutdown, frozen validation,
frame ordering/reference provenance and indexed artifact hashes, then writes only
a separate authentication report and conservative eligible paired statistics.
It reuses the historical validation of authenticated identical bytes; it is not
fresh timing/pixels or signed third-party attestation. Contained render/service
walls must fit the frozen positive worker envelope (only1ms absolute rounding
allowance); exact-RGBA references and pairs must also agree on alpha hashes.
Contradictory or missing/changed evidence remains ineligible. Do not remove
owner.lock, rewrite the old report, or use
`--resume` to bypass the failure. Optional `--diagnostics` requires an unexcerpted
full original report, not the supplied transformed diagnostic export.

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

## Ordinary full-file Windows CPU render (no experiment campaign)

This is the **recommended ordinary path for the saved stationary refined-ribbon
look**, not a global default change for other styles. The full comparison and
accepted Windows usability evidence are [recorded separately](docs/notes/refined-ribbon-cpu-selection-20261115.md).
For a new asset, start in the updated checkout (use `git pull --ff-only` on a clean
main checkout; preserve local work if Git refuses). Use the prepared-runtime,
reuse-only helper in native Windows PowerShell, with no environment activation:

```powershell
py -3 scripts/render_refined_ribbon.py --audio "D:\test-waveform\s0e00\s0e00-Damian.wav"
```

For another mono recording, invoke the same command separately and replace only
the quoted `--audio` value with that recording's actual existing path. Each input
produces its own transparent MOV asset; do not mix the two speakers' recordings.
The second speaker's filename is not prescribed. A convenient one-command
multi-file procedure and batch/context-amortization tests remain deferred, not
implemented or measured here. Import the printed MOV into Resolve Studio; result
JSON/logs are provenance, not the editing asset. Continue using the already accepted
CPU asset without regenerating or reassessing it just to close this pass.

Native Windows keeps the supplied drive/UNC path in the ordinary CLI and input
discovery; it does not translate it to `/mnt/d/...` or add a blanket path prefix.
Quote paths containing spaces. Another mono filename is equally valid; the example
is not a required recording name. On Linux/WSL the CLI retains its drive-to-`/mnt`
compatibility, and WSL's own `/mnt/d/...` paths stay unchanged. Use a host-native
existing file for the helper's `--audio` argument. This is the primary render input,
not a reference-normalization input; the selected config/preset/performance files
contain no machine-specific audio path and need no path repair.

This runs exactly one ordinary `python -m ewp_waveform render` through the shared
application service, with normal validation and publication. It renders the entire
supplied file, not a preview, matrix, benchmark, CUDA adapter or experimental
`run_experiments.py --full`. It never invokes pip/uv, downloads dependencies/tools,
repairs an environment, activates a shell or changes global PATH. The bootstrap
selects the project's existing locked Python3.12 `.venv`, otherwise independently
reverifies retained runtime preparations in the same default store used above.
On Windows it prefers the previously prepared hash-verified pinned FFmpeg pair;
otherwise it uses an existing same-directory PATH pair. The chosen tools are
hashed, version-checked and placed first on the **child-only** PATH, and each MOV
encode still performs the actual bounded CPU GEQ/LUT qualification.
Missing/changed preparation fails without installing or silently falling back to
another finishing algorithm. Use `--python PATH`, paired `--ffmpeg PATH
--ffprobe PATH`, or `--preparations-root PATH` / `--managed-root PATH` when your
existing preparations are elsewhere; none of these options authorizes acquisition.

Committed settings are separated by domain:

- `presets/iuris-ribbon-refined-production.toml`: a distinctly named saved variant,
  leaving the stock preset unchanged. Mapping7 / filled-ribbon-v2,1400×280/60fps,
  balanced, custom `#C7E6EC`, amplitude0.82, stroke1px, high glow(sigma16),
  smoothing0.06, visual_noise0.35/rate0.8/seed1729, idle0,
  reflection0.45, horizon enabled/extent0.96/opacity0.55. Current ordinary resolution
  retains physical-SS2 (3000×380 gray intermediate including overscan). The explicit
  custom color freezes cyan independently of the foreground auto-color policy.
- `performance/ribbon-lut.toml`: existing CPU serial/jobs1, automatic encoder threads
  (`ffmpeg_threads=0`), qualified LUT, nonpersistent workdirs. The helper copies this
  profile and changes **only** its work root to the fresh output namespace.
- `examples/production/refined-ribbon.toml`: explicit application defaults/grouping
  and ProRes-only selection, preventing accidental inherited PNG/dual-output settings.

The asset is silent, transparent, straight-alpha ProRes4444 MOV, not a composited
video. The new saved-preset name has its own render identity/output filename;
this command does not overwrite or relabel any historical accepted master.
The supplied source identity remains SHA256
`e7088a3dfdfc12323acbc2d4f9d4c0af304b95eaabfe80e45becbcf7bb16348b`,
395.6785seconds/23,741frames at60fps. The helper accepts one file, records its actual
hash, and verifies its bytes/mtime unchanged; it does not assume every supplied
file is that original.

By default a timestamp+random ID creates a fresh
`~/Videos/ewp-waveform/ID/` with `output/`, private `work/`/`tmp/`, resolved
`performance.toml`, and `logs/`. The helper prints the root before encoding and
prints the MOV and result JSON paths after reading the publication back. Logs
retain exact CLI argv, selected runtime/tool/config identities, ordinary CLI
stdout/stderr, qualification in the production result, source immutability and
resource checks. `--output-root PATH` must name a **new** directory; an existing
root is refused without modifications, never resumed/forced/overwritten.
`--evidence-root PATH` optionally separates logs from media and must also be new.
Generated data must be outside the product checkout (ignored external ops storage
is permitted). Failed attempts remain intact; choose another fresh root.
Command failures report the child return code and available error, stderr and
stdout (including input-discovery diagnostics), plus the retained log directory;
the helper itself returns2 on refusal/failure, not the child's exit code. Successful
root/MOV/result paths are printed in the host's native path syntax.

Defaults allow8GiB new output/work/log growth, require10GiB free reserve and permit
up to24hours (`--max-growth-gib`, `--reserve-gib`, `--timeout-seconds`). Sampled
process-tree supervision includes preparation verification, encoding, publication
and final evidence writes. These limits are not kernel disk quotas or a full-file
size/runtime promise; inspect actual target capacity before starting. There is
no fresh local full-source performance claim for this documentation task. The
[supplied November15 Windows production result](docs/notes/refined-ribbon-target-evidence-20261115.md)
now establishes native full-file success and direct-user Resolve import/display
acceptance only, with unknown producing commit/whole-MOV hash. Its89s result-job
duration is not a launcher envelope or a CPU/CUDA denominator. The earlier VM.1
smoke is one synthetic0.1s/six-frame **ordinary full-file** render at the committed
production geometry, with qualified LUT, decoded fractional alpha, silent stream,
schema-valid publication, cleanup, source immutability and collision refusal.
Linux execution and Windows selection mocks alone do not qualify native Windows/NLE;
the separate supplied observation above is the bounded target evidence.
The path-policy regression also follows launcher argv through actual Typer render
parsing and resolved service config under explicitly labelled platform simulations;
it does not execute a Windows filesystem or renderer on the Linux host.
The supplied Windows four-second service LUT result was slower than GEQ; prior
32s pipeline and per-encode qualification timings do not establish full speedup.

The supplied clean P/08b432a Windows campaign completed: serial32s service GEQ
11.550576 -> LUT9.054572seconds (counterbalanced medians,n=2/side); serial4s service
1.909447 ->2.101591seconds. Per-encode LUT qualification costs about0.57seconds,
so short benefit is workload-dependent. The separate jobs2->jobs1 GEQ comparison
30.555886 ->11.527845seconds is a worker-policy contrast, not an isolated LUT gain.
Serial GEQ/LUT native MOV hashes agree in the supplied records; jobs-policy MOV
containers differ while decoded RGBA/alpha/composites agree. These are supplied
Windows observations, not VM.1 target execution or a full-episode speedup. They
supersede the earlier narrower Windows recommendation without rewriting it.

A later one-command operator procedure for multiple selected input files is backlog
only; this helper remains single-file. Two existing speakers' mono recordings
produce two independent assets; no diarization, scheduler or throughput policy.

The **separate historical** WSL combined-CUDA control recipe (closed, not NEXT) is:

```bash
python3 scripts/run_experiments.py --audio "/mnt/d/test-waveform/s0e00/s0e00-Damian.wav" --cuda --cuda-combined --cuda-combined-service32 --max-growth-gib 6
```

It is not the production helper or the new CPU/CUDA comparison. The supplied
[November15 target evidence](docs/notes/refined-ribbon-target-evidence-20261115.md)
reports COMPLETE native CUDA qualification and application-service4/32s results;
those outcomes are not inferred from CPU-Torch tests or simulated dispatch and are
not fresh local target revalidation. Do not repeat the closed campaign. Use the
current intended command at the top only after its new implementation is verified.
Historical notes and retained full-reference acceptance remain unchanged.
