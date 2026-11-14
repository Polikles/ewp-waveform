# Single-file combined FIR candidate and focused target campaign

## Scope and rationale

The new opt-in candidate selects **device RGBA8 + within-file batch2 + ordinary
completed-call timing** together. Earlier individually measured output, batch and
timing comparisons are separate AB/BA pairs, not additive speedups. This combined
candidate has no native CUDA performance result yet.

These controls compose without changing the FIR algorithm:

- `_alpha` operates on independent batch images; the production stateful raster
  generator is still consumed once, sequentially. Its temporal state is not reset
  at batch boundaries. A final odd frame uses the live batch prefix.
- Device output uses the existing separate float32 operations and half-up
  quantization, then the existing straight-RGBA LUT. Alpha-zero RGB remains zero;
  nonzero-alpha RGB remains unpremultiplied. RGBA8 downloads **four bytes/pixel**,
  not one; the independent device-alpha8 control remains available.
- Ordinary timing removes diagnostic CUDA events/per-phase explicit sync, not
  completion. Transfers remain blocking and one explicit completion synchronize
  remains at the finish-call boundary. No asynchronous overlap, pinned staging,
  multi-file concurrency or GPU FFV1 rescue is implemented.

The adapter preserves original production analysis/raster generation, horizontal
supersampling, overscan, geometry, frame order, CPU ProRes settings, application
validation and publication. It refuses pool execution, PNG/dual-output, non-ribbon
routes, competing finishing adapters and unbounded durations. Its identity includes
backend/device/output/batch/timing/algorithm; ordinary production defaults do not
change. Existing independent controls remain separately selectable.

## Timers and admission

Both sides run through **actual serial `service.render`**, not a standalone codec
or an old pipeline-only timer. Lazy Torch import, context creation, independent
small/production-size qualification on every encode, worker setup, normal
validation and publication are included in service wall. External frozen preplan,
strict comparative decoding and views remain outside; the supervisor also retains
launch-through-exit cold worker wall. Inclusive encode/finishing spans are
non-additive and never called encoder-exclusive CPU time.

Control retains the demonstrated host-reuse/batch1/diagnostic assembly improvement.
Candidate is the combined tuple above. The allocating host-reference control remains
separately selectable in the existing individual campaign, not the denominator here.
Each tuple also has a separate qualification gate before the timed campaign. Every
observation uses a new namespace and per-encode qualification is deliberately not
reused across files. Analysis-cache hooks are disabled on both FIR service sides.
Initialization is part of application cost, not hidden in a prior warmup. Shared
verified dependency/tool preparation is still reused by the existing runner.

The default repeated order is AB then BA, with two fresh observations per side.
The first validated control supplies exact original-raster and pre-encode RGBA
hashes, plus strict decoded-RGBA comparison, to every later observation in that
pair. Incomplete/failed original-input shorts block dependent CUDA service32.
Service32 is explicit jobs1/32s at25..57s, **not** stock pool2 production32 or a full
source render. Technical equality does not establish native Resolve acceptance.

## Narrow next commands

WSL, current-code CPU worker-policy/LUT plus independently qualified CUDA combined:

```bash
python3 scripts/run_experiments.py --audio "/mnt/d/test-waveform/s0e00/s0e00-Damian.wav" --optimize-single-file --cuda --max-growth-gib 6
```

Omit `--cuda` for CPU only. The CPU shortlist includes direct GEQ/LUT4s (native Windows repair coverage),
serial-service GEQ/LUT4s, then independent
jobs2/jobs1 GEQ32 and serial GEQ/LUT32. No old-source/new-source comparison is
performed. Failed LUT qualification or a failed optional LUT short does not
suppress the independently admitted GEQ jobs-policy or CUDA checks. Six-frame
`--cpu-smoke` never admits32s cells.

CUDA only, short first and then32s if all matched shorts succeed:

```bash
python3 scripts/run_experiments.py --audio "/mnt/d/test-waveform/s0e00/s0e00-Damian.wav" --cuda --cuda-combined --cuda-combined-service32 --max-growth-gib 6
```

Omit `--cuda-combined-service32` for short-only. Do not append `--optimize`,
`--preflight-only`, `--full` or `--reference-only`. Neither focused command runs
Vulkan qualification or revisits the retained independent Vulkan failure. Neither
requests CUDA acquisition; valid existing preparations are reverified/reused.

Native Windows CPU-only counterpart, retaining selected pinned FFmpeg preparation:

```powershell
py -3 scripts/run_experiments.py --audio "D:\test-waveform\s0e00\s0e00-Damian.wav" --prepare-ffmpeg --optimize-single-file --max-growth-gib 6
```

## VM.1 exercise, not target performance

An existing PyTorch2.9.1+cpu environment was discovered and reused without
installation. Real CPU Torch tests exercised the combined route with nonzero FIR
blur, odd13x9 output geometry, horizontal supersample3, overscan, fractional
horizon/reflection, hidden input RGB, straight alpha, all half-byte quantization
neighbors and ordered partial batches2/2/1. Tiny encoder tests verified decoded
ProRes equality. A five-frame actual application-service pair also used real
per-encode small/production-size CPU qualification and normal publication; source,
original raster, pre-encode RGBA and decoded output matched the control exactly.
Its production raster test selected zero glow to keep the workload tiny; the
separate odd-geometry test covers nonzero finishing blur.

The maintained runner's focused CPU smoke completed with four validated native
six-frame renders and separate deduplicated views. This is functional execution,
not an original-input or service32 timing result. The integrated reporter retains
the six named pair declarations; the strict reporter intentionally refuses
undeclared control changes rather than inventing pair statistics.

Repository-wide lint/type checks, unit/regression and integration gates passed.
The selected optional-CPU suite passed76 checks. Native CUDA qualification,
combined4s/32s timing, source-scale GPU behavior, native Windows execution and
Resolve Studio import/alpha/playback remain pending. No full CUDA media was regenerated
and no accepted baseline/preview retention hold was released.
