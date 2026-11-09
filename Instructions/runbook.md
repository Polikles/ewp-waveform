# Operator runbook (FFmpeg MVP)

Use this after `Instructions/install.md`. Technical architecture stays in `docs/`. This file is how to run the tool on real audio without changing code.

**Status:** accepted internal MVP, development version 0.1.3, checkout-based delivery only. Default look remains limited versus the Iuris et Logos boards. There is no public release or generally qualified deployment target.

## What this tool does

It reads WAV/MP3 (source files are never modified) and writes transparent waveform assets:

- ProRes 4444 `.mov` (production default)
- PNG RGBA sequence (`--format png`)

Compose those assets later in DaVinci Resolve or another NLE. This tool does not edit audio, transcribe, or assemble the final podcast video.

## Defaults you will actually use

| Choice | Name | Meaning |
|---|---|---|
| Scroll envelope (podcast target) | `iuris-default` | 60 fps, 5 s window, mirrored bars, medium glow. Limited vs brand mirrored line. Locked from operator pick `*ad0c99b500c0.mov`. |
| Fixed-axis spectrum | `iuris-spectrum` | Frequency on X (log-Hz, auto span). Vertical motion only. Experimental. |
| Performance | `balanced` | 60 s chunks, 2 encode processes, FFmpeg threads 0 (auto; pinned to 1 per process when jobs>1). |

Playhead envelope and particles are not available. GPU is not used.

## File names and grouping

- One source file → one waveform job.
- A file containing several speakers is still one input; no diarization,
  speaker separation or multi-speaker composition is required.
- `s0e00-Damian.wav` groups as project `s0e00`, track `Damian` (first `-`).
- Ungrouped names are valid (`interview.wav` → project and track `interview`).
- Directory input is a batch. Recursion is off unless `--recursive`.
- Tracks in the same project whose durations differ by more than 3 frames at the target FPS fail the batch (`E_PROJECT_TIMELINE_MISMATCH`).

## Everyday commands

All commands from the checkout, with `uv run` in front.

```bash
# Environment
uv run waveform doctor
uv run waveform capabilities

# See how files will group
uv run waveform inspect "/path/to/audio"

# Read-only plan: signatures, dest paths, SKIP vs PROCESS; creates no output/work/cache/results
uv run waveform dry-run "/path/to/audio" --preset iuris-default --output-dir "/path/to/out"

# Short real render (uses the production path, not a fake preview)
uv run waveform preview "/path/to/file.wav" --start 0 --duration 8 --output-dir "/path/to/out"

# Full render
uv run waveform render "/path/to/audio" --preset iuris-default --format prores4444 --output-dir "/path/to/out"

# Both formats
uv run waveform render "/path/to/file.wav" --format prores4444 --format png --output-dir "/path/to/out"

# Spectrum
uv run waveform render "/path/to/file.wav" --preset iuris-spectrum --output-dir "/path/to/out"

# Catalog
uv run waveform preset list
uv run waveform preset show iuris-default
uv run waveform performance show balanced

# After a failed long job: inspect leftover workdirs, then remove them when done
uv run waveform clean --workdirs --dry-run
uv run waveform clean --workdirs
```

Clip controls `--start` and `--duration` belong to `preview` and `dry-run`, not
`render`. To check a preview destination, repeat its exact clip flags, preset, FPS
and output directory in `dry-run`. `preview` does not accept `--performance` or
`--keep-temp`; it uses the application default performance profile. Full `render`
accepts both and always targets the full file.

Exit codes: `0` success, `2` config/CLI, `3` input, `4` capability, `5` render/output, `6` partial multi-job failure.

## Outputs

If you pass `--output-dir DIR`, files land under `DIR/<project>/`.

If you omit it, the tool writes `<source-parent>/waveform-output/<project>/`.

Typical files:

```text
<project>/<stem>_<preset>_<12-hex>.mov
<project>/<stem>_<preset>_<12-hex>_png/frame_000001.png
<project>/<stem>_<preset>_results.json
run_<id>_results.json
```

The 12-hex suffix is the short render signature. Same source + same visual settings → same name → second run is `SKIPPED` and keeps the existing file. `--force` writes `_v002` instead of overwriting.

ProRes at 1400×280 is large (spike order-of-magnitude: tens of GB per hour). Preview first. Do not keep workdirs on success (default). Failed jobs keep a workdir for resume.

## Resume

If a long scroll job dies after some 60 s chunks:

1. Do not delete the workdir (`ewp-*` under the process temp dir, or a profile `workdirs.root`).
2. Run the same `render` command again (same source, preset, fps).
3. Valid chunks are reused. The result includes `W_JOB_RESUMED` and `resume_history`.
4. If you changed the preset, source file, or visual contract, the checkpoint is discarded and the job starts clean.

`clean --workdirs` deletes those intermediate directories. It never deletes published MOV/PNG or results JSON.

## Disk and time (honest)

### Retained local reference and visual acceptance

The operator accepts the current renderer as an MVP, not a permanent pixel-perfect
style mandate. Apply [visual development, complete acceptance assets and retention](../docs/23-visual-development-and-retention.md).
Reuse the retained eight-second MVP reference indexed by the private
project-ops manual-tests manifest and canonical run navigation. Source recordings,
reference images, generated MOVs and extracted stills stay in operator-local media
storage, outside Git and review packages. No upload to a model provider is implied.
Use the actual short s0e00 excerpt for a scoped diagnostic, not a replacement
reference on every edit. It is not a complete-s0e00 deliverable: optimization
completion requires a complete render per added/optimized style on the provisional
full s0e00-Damian input, with applicable baseline retained for independent operator
comparison. No mandatory style/color/track/episode Cartesian product is implied.

Record exact source commit/product version, input hash, clip boundaries, resolved
visual/performance settings, tools, output hash/size/time and validation. Stills may
come from that same render. Label automated observations separately from human
review: generating a reference is not a new human acceptance event. Reuse it for
relevant changes rather than regenerating on every commit. Assess shape, layout,
contour, color/alpha, audio response and temporal continuity actually present in
the clip. Small explained differences are allowed if the overall character is
retained; style evolution needs an explicit rationale, and defects remain defects.
Exact same-contract deterministic/functional tests still apply; see
`../docs/12-testing-and-acceptance.md`. Do not blindly refresh failing oracles.

### Capacity admission and reserve

Check free bytes on the actual output AND workdir/scratch filesystems before each
render. On a shared filesystem count their combined peak, not the same free space
twice. Estimate from measured bytes/second at comparable resolution/FPS/style,
including final assets, simultaneous chunk/publish copies, decode/cache needs and
stills. Use a conservative allowance for uncertainty. Built-in `W_OUTPUT_SPACE`
and `doctor` are useful checks, not a guarantee that workdirs fit.

The current roughly 115 GiB VM filesystem uses a 10 GiB minimum operating reserve
and a 20 GiB early-warning level. The reserve leaves room for the OS, shared tools
and failed-job recovery, beyond an ordinary short render's sub-GiB peak. For larger
jobs raise the reserve to at least twice the projected largest active chunk plus
1 GiB if that exceeds 10 GiB. Raise the warning to reserve plus at least 10 GiB or
25% of the planned peak growth, whichever is larger. These are capacity margins,
not test quotas. Reassess when the VM or workload changes. Private ops records hold
current measured capacity, estimates and free-before/after receipts.

Postpone a render if its conservative remaining growth would cross the reserve;
notify the operator. Below the warning level, reassess remaining growth and defer
optional additional renders. During longer selected jobs sample free space and
owned output/workdir sizes at existing chunk/frame progress (for example every
300 frames, or about once per minute). Stop further admission and safely interrupt
if growth threatens the reserve; retain failed-job recovery state. No monitoring
service is required. Never automatically delete baselines, sources, environments
or unreviewed historical evidence; cleanup needs explicit selection and authority.

### Development versions and repository maintenance

`pyproject.toml`, package `__version__`, the editable package in `uv.lock`, CLI and
new results/examples must agree. Historical result versions remain historical.
Version 0.1.0 assigns the accepted MVP/identity-correction development baseline;
there was no prior assigned version beyond 0.0.0 and no public release. Future
compatible bug corrections normally increment patch; new functionality and
intentional pre-1.0 compatibility migrations normally increment minor. Document
the actual promised interface and impact rather than treating every internal hash
change as a public API break. A stable public incompatible API change requires
the applicable SemVer major policy. Do not infer stability merely from MVP status.

EWP-IDENTITY-FIX-001 corrects appearance reuse by adding recipe-v1 to frequency
signatures, including defaults: old assets remain but are not reused. This is an
intentional persisted-output workflow migration accepted by the operator; raster
v13 and time-scroll identity remain unchanged. Product SemVer, TaskPacket snapshot
versions, raster/recipe/results contracts and orchestration G versions are distinct.
Changing a product version does not itself authorize publication, package upload
or a public release.

For this single-developer project, integrate authorized verified work promptly
into main with ordinary history-preserving Git operations. At most one necessary
short-lived task branch; no branch for each render/report/checkpoint or routine
documentation change. Use exact commits and verification refs for evidence.
Retire a completed branch only after its commits are reachable from main and no
unique work, active execution, useful worktree state or branch-name consumer
remains. Delete remote task branches only after exact remote main integration is
verified. Never force removal of a useful/dirty worktree. Record exact identities
and local versus remote publication in private ops. G uses its maintained
integration branch until its finite reusable baseline is qualified and explicitly
accepted; later fresh-VM/project/VPS qualification follows it. Product acceptance is not a
G/main merge gate waiver or permission to delete G's historical branches.

- A few seconds of `iuris-default` at 60 fps is the right smoke test.
- Episode-length ProRes needs admitted capacity for baseline, optimized output and work/recovery copies. Historical size estimates (~10 GB for 6.5 min at 1400×280×60; ~100 GB per 50 min track) are planning context, not a disposal permission. Keep baseline/download and optimized-comparison holds; intermediates need not be archived indefinitely.
- Chunk size and `jobs` (`render --performance balanced` or `maximum`) do not intentionally change the look. They request up to 2 or 4 scroll workers respectively; actual parallelism depends on available chunks. Custom positive-integer `jobs` values do not make serial paths parallel.
- Historical reported wall time (original measurements unavailable for fresh comparison; not a current promise) on `s0e00` (~6.5 min): ~3.5 h at `jobs=1`, ~67 min at `jobs=4` (~10× realtime, ~17% of a 14700K). Further cuts are a product goal; the FFmpeg path will not use the whole machine.
- `benchmark run` is for matrices of short files. Do not point the example manifest at private episode paths inside git.

## Known limits (do not treat as bugs)

- Scroll geometry is **limited** vs brand mirrored line (dense RMS bars, not a pixel match).
- Spectrum is **experimental** (application FFT + log-Hz span, not the particle field).
- Playhead mode is refused.
- Particles enabled in a preset are refused.
- Scroll: `jobs` bounds processes encoding independent `chunk_seconds` chunks
  after the global peak is stored. Ordered concat preserves continuity; `jobs=1`
  and `jobs=2` must match visually.
- Legacy fixed-axis spectrum (the CLI `iuris-spectrum` default) uses a single
  frame stream/encode, not the scroll chunk pool.
- The existing application/script `field_center_out` path can use a process pool
  only when requested `jobs > 1` and expected frames are at least 1,800 (30 s at
  60 fps). Shorter field work remains serial. This is not a general CLI spectrum
  parallelism switch: field layout/geometry, render-path and antialiasing kwargs
  are internal/API controls, not current `waveform` flags. Locked style fixtures
  and the AnalysisFrame/VisualField/raster foundation already exist; ordinary
  preset/CLI delivery and further qualification are separate backlog work.
- GPU is not used.
- 10-bit ProRes request vs 12-bit ffprobe readout remains an open fidelity note.

## Future checkout/host QA checklist (not a qualification result)

Use a **copy** of audio you are allowed to process, or a tiny synthetic fixture.
Keep source recordings, reference images and derived assets outside Git and review
packages; a private repository does not authorize their publication. This checklist
has not been freshly executed on WSL or a clean host by this documentation update.

1. Follow [install.md](install.md) on the specifically selected host; record checkout/version, Python, uv and FFmpeg identities. Prefix commands with `uv run` from the checkout. Require `waveform doctor` to report `doctor: ok`.
2. `waveform capabilities` — expect `domain:time+scroll` limited, `domain:frequency+fixed-axis` experimental, `effect:particles` unsupported, `domain:time+playhead` unsupported.
3. `inspect` a single WAV and a `s0e00-Damian.wav` / `s0e00-Szymon.wav` pair; grouping must split on the first `-`.
4. `preview` 2–8 s of speech at `iuris-default` to `--output-dir`. Record alpha-capable codec/pixel format in ffprobe (`yuva`), content-level alpha verification, and later operator/NLE review separately; metadata alone does not establish a transparent background. Preview uses a **clip** identity (default 8 s). A later full `render` of the same file must **not** SKIP that preview dest. Full-file dests appear only after **all** chunks encode and concat; until then work lives under `<process-temp>/ewp-waveform-work/` by default (Python temp selection honors `TMPDIR`; a performance profile may select `workdirs.root`). Progress is on **stderr** (`chunk N/M frame 300/3600`, …).
5. Repeat `preview` with the same clip flags and destination: expect SKIP. `dry-run --start 0 --duration 8` with matching preset/FPS/output must plan that preview identity; its existence-based SKIP is advisory, not full output validation. `preview --force` must write `_v002`. Full-file `render` has no clip flags and targets a different identity for a shorter-than-source preview.
6. `render --format prores4444 --format png` and confirm both exist plus `*_results.json` and `run_*_results.json`.
7. Use `preview --start 0 --duration 8 --preset iuris-spectrum` on the same source for a short spectrum render; result JSON `analysis.fmin_hz` / `fmax_hz` should be populated.
8. Interrupt a multi-chunk job (tiny `chunk_seconds` in a custom performance TOML, or a longer file) and resume; look for `W_JOB_RESUMED`.
9. Open the ProRes in DaVinci (or another NLE with alpha) on a machine that can play it. Compare to the boards only as a direction check; pixel match is not claimed.
10. `clean --workdirs --dry-run` then `clean --workdirs`.

Long s2e9 / ~2.5 h jobs stay off undersized VMs.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `Required tool is not on PATH: ffmpeg` | `sudo apt install ffmpeg`; new shell; `doctor`. |
| `ffmpeg build lacks prores_ks` | Distro FFmpeg is too thin; install full `ffmpeg` package, not a stripped static build. |
| `E_PROJECT_TIMELINE_MISMATCH` | Same-project tracks differ by >3 frames. Align sources or render separately. |
| `E_RENDERER_CAPABILITY` particles/playhead | Those features are out of this MVP. Disable particles; do not set `time_mode = "playhead"`. |
| `SKIPPED` when you expected a new look | Signature includes preset, fps, and visual contract. Change those or use `--force`. |
| Empty leftover `.mov` | Empty dests are not skipped; rerun should replace them. |
| Disk growth threatens reserve | Postpone further renders; notify the operator and inspect selected disposable workdirs. Never automatically delete baselines, source media, environments or unreviewed evidence. |
| Resume did not reuse chunks | Checkpoint must match source hash and render signature. Stale files are discarded on purpose. |
| CPU stays at a few percent | Check the active path: scroll can use `render --performance balanced` (up to 2 workers) or `maximum` (up to 4), while legacy spectrum and short field renders are serial. `preview` has no performance flag. A custom performance TOML affects only paths that consume `jobs`; it does not enable GPU or general spectrum parallelism. |
