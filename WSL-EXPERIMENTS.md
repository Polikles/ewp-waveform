# WSL experiments — complete operator guide

This is the only operator startup guide for the opt-in experiment suite.
The production renderer remains modular; one script owns discovery, environment
selection, tool selection, sequencing, validation, views, reporting and resume.
Do not assemble a run from helper scripts or hand-edit manifests/source commits.

## Start from a clean GitHub checkout

Clone `Polikles/ewp-waveform`, enter the checkout, then run:

```bash
python3 scripts/run_wsl_experiments.py --audio "/absolute/path/s0e00-Damian.wav"
```

That is the complete experiment startup command. There is no activation step,
manual export, private startup file, transferred archive, source-pin substitution
or reconstruction of appearance settings. The driver discovers the exact clean
checkout commit/tree and uses the scenario definitions committed with it.

The required original WAV has SHA-256
`e7088a3dfdfc12323acbc2d4f9d4c0af304b95eaabfe80e45becbcf7bb16348b`.
It is 395.6785 seconds and the complete reference has 23,741 frames. The WAV and
all generated media stay local, outside Git; this repository does not distribute
private recordings. A different recording is not silently substituted.

The command starts real rendering when prerequisites and resource admission pass.
Allow time for one full stock CPU reference, a real 32-second production-path
measurement, bounded matched experiments and separate validation/view generation.
Do not start another instance on the same run directory or delete partial files.

## Prerequisites and automatic environment selection

Use Linux under WSL2 for GPU qualification. A normal `python3` must run the
standard-library startup; production execution requires Python 3.12 and the exact
runtime dependencies in `uv.lock`. The driver first captures the original
host/Python/PATH/tool inventory, before environment selection or tool building.

It selects a working checkout `.venv` automatically. If that is unavailable and
`uv` is installed, it internally runs frozen project environment setup with
Python 3.12. This can fetch the locked project packages/managed interpreter; it
does not change locked versions, replace global Python/FFmpeg or install drivers.
An already prepared Python 3.12 environment can instead be selected with
`--python /absolute/path/to/environment/bin/python`. Both the original bootstrap
Python and selected project interpreter/dependencies are recorded separately.
Pre-existing editable-distribution labels are recorded, not confused with the
actual source version or silently relabelled.

Git and a clean tracked checkout are required. Keep personal notes/results outside
it. FFmpeg/ffprobe and the production CPU path are needed for an installed-tool
reference; known absent capabilities produce explicit skips, not fake timings.
The selected experiment tools must support their CPU controls, lossless FFV1
oracle and viewing path. Advertised GPU support still requires actual device,
transfer, alpha/lossless and cadence probes.

Startup collects actionable missing requirements in its report. If it stops,
open the exact printed report and inventory, supply only the listed prerequisites
using your maintained WSL/project installation procedure, then start a fresh run.
Do not edit failed receipts, change the old run's manifest, or manually invoke the
builder/suite to bypass a refusal. No automatic Linux NVIDIA driver installation,
CUDA repair or global FFmpeg replacement is performed. Working WhisperX/CUDA is
not evidence of Vulkan or Vulkan ProRes support.

## What is measured

A. Original installed-tool baseline: the explicitly captured original default
FFmpeg/ffprobe pair renders the complete authenticated stock CPU reference once,
if the required production capabilities are available. Those absolute paths and
hashes remain frozen even after project environment/tool selection changes PATH.

B. Selected-toolchain CPU controls: the selected FFmpeg build runs the same-host,
same-build short CPU controls used by the GPU pairs. If the original and selected
tools are different, the optional short A/B comparison is labelled a toolchain
contrast. Identical binaries are not claimed to be different builds.

C. GPU experiments: transfer control; CPU versus Vulkan blur with controlled
transfer topology; matched CPU versus Vulkan ProRes; and conditional CPU versus
GPU FFV1 using a compressed production preencode oracle with every RGBA byte,
including alpha/hidden RGB, checked. The real production32 stock path is separate.
See [chapter 25](docs/25-wsl-experiment-suite.md) for exact timer/oracle contracts.

One full installed reference is followed by bounded shorter experiments, not a
full render per pair. WSL's actual affinity/cgroups/RAM/storage and GPU are used;
no VM eight-CPU allocation is imposed. The reference workload's jobs2/threads0
settings stay frozen within pairs, while automatic hardware-dependent choices
and observed process/encoder behavior are reported separately.

VM.1 versus WSL is an environment reference. Installed versus new FFmpeg is a
build contrast. Neither alone isolates GPU acceleration. Only the declared
same-host/same-build pairs with fresh successful validated observations receive
paired numerical changes. Unknown options, malformed graphs, wrong devices,
alpha/lossless violations and incomplete outputs are failures, never unsupported
successes or silent CPU fallbacks. Known missing optional capabilities are skips.

## Optional flags — still one driver command

- `--reference-only`: one complete installed-tool stock CPU reference, no short
  matrix. Used for the fresh VM.1 environment reference through this same entry.
- `--cpu-smoke`: tiny synthetic six-frame CPU service/FFV1/oracle/views/report
  workflow. Omit `--audio` to generate its fixture automatically. This is not an
  authenticated full reference, production32 result or GPU qualification.
- `--ffmpeg /absolute/bin/ffmpeg --ffprobe /absolute/bin/ffprobe`: select another
  existing matching tool pair for experiments; the original baseline is unchanged.
- `--build-ffmpeg`: explicitly allow the existing isolated pinned-source builder
  when the installed selection lacks the requested experimental capabilities.
  Source/build/prefix locations are generated automatically outside Git; system
  tools are preserved. It is not a dependency/driver installer. Prerequisite
  diagnostics include C compiler, make, Git, nasm, pkg-config, x264 development
  files, Vulkan headers and glslc supporting the required Vulkan1.4/SPIR-V target.
  Vulkan header/build-target success does not establish the runtime ICD/device.
  Build failure is retained and never automatically retried in that namespace.
- `--device 'RTX 3090' --expect-device-regex 'RTX\s*3090'`: explicit expected device;
  a requested selector is not proof of the GPU actually used. Software Vulkan is
  rejected. Actual GPU experiments are target-only, not executed on VM.1.
- `--output-root /absolute/external/results`: optional parent for automatically
  generated metadata/run/build directories. Default is
  `~/.local/state/ewp-waveform-experiments`, outside the checkout.
- `--media-parent /absolute/external/media`: optional separate parent for bulky
  media. `--media-root` is an alias for this parent, not a hand-created suite root.

For example, a CPU reference with separated local media uses the same driver:

```bash
python3 scripts/run_wsl_experiments.py --audio "/absolute/path/s0e00-Damian.wav" --reference-only --output-root "/absolute/results" --media-parent "/absolute/media"
```

## Results and the one main report

The driver prints absolute run, suite, media and any build locations. It always
prints the exact main Markdown report path on completion or partial/preflight
failure. Its numbered report identifies original host/tool observations, selected
project environment/tool provenance, VM.1 reference, suite status, comparable
paired results, limitations, validation and hash-deduplicated native MOV/MKV,
comparison-proxy and dark/light/checker MP4 navigation. JSON/CSV and immutable
suite reports remain available alongside their referenced evidence.

Initial observations remain in `initial-inventory.json`; selected observations
are separate. System installations are labelled observed installed tools, not
fabricated pinned-source build receipts. Actual isolated builds have actual
source/compiler/configuration/binary/library receipts.

Service wall includes production validation/publication. External verification,
fixture preparation, views and process envelopes have separate costs; overlapping
phase spans must not be summed. For a full MOV matching authenticated historical
bytes, prior complete-media validation can be reused after whole-file hash
verification; that is not a new decode or an earlier render relabelled as current.
Unexpected differences remain retained for investigation, not image tuning or
blind rerender. Byte-identical native media can share canonical navigation under
the scoped safe dedup policy; no general historical cleanup is performed.

Full viewing copies default off to avoid duplicate multi-GB media. A transparent
MOV is not an opaque ordinary-player preview. Short dark/light/checker MP4s are
correctly composited views. A comparison MOV proxy for MKV does not establish
native FFV1 Resolve compatibility.

## Safe continuation

Use the exact driver run directory printed by the first command:

```bash
python3 scripts/run_wsl_experiments.py --resume "/absolute/path/to/run-UTC-random"
```

No original audio/environment/tool flags or edits are needed; all selections are
frozen. Use the same clean checkout at the recorded commit and the same run/media
locations. The driver verifies source/script/interpreter/dependencies, input,
tools/libraries, manifests, ledgers, requests/results and retained artifacts before
continuation. Completed readback adds no fresh measurement.

Only safe unattempted work continues. FAILED or uncertain STARTED work is retained
and fences replay; do not delete a marker or repeat a partial render. Inspect the
report and logs, reconcile uncertainty externally, and use a new namespace for a
corrected experiment. Resume cannot adopt a copied/relocated/edited run or
silently rebuild a changed environment/toolchain.

## Qualification and promotion boundary

The entry point is tested through real CPU execution from a fresh clean checkout
and the fresh full VM.1 reference; versioned current-reference metadata records
the exact tested source, tools, timing, hash and validation route. Consult that
metadata and the operational report for actual coverage rather than treating this
guide as a WSL/RTX3090 performance result.

Actual WSL original/selected tool discovery, optional source build, Vulkan device
and codec probes, GPU pair timings/utilization, target filesystem behavior and
Resolve Studio import/alpha/playback remain target-only checks until executed.
VM tests or mocked devices do not qualify them. Technical validity, file-byte
identity, decoded equality, operator visual assessment and Resolve acceptance are
independent axes. Byte-identical measured optimizations can follow technical
review; other output changes stay visual/Studio pending. No numerical metric
alone promotes a profile or changes production defaults.
