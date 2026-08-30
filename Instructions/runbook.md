# Operator runbook (FFmpeg MVP)

Use this after `Instructions/install.md`. Technical architecture stays in `docs/`. This file is how to run the tool on real audio without changing code.

**Status:** internal beta. Default look is limited versus the Iuris et Logos boards. There is no public release.

## What this tool does

It reads WAV/MP3 (source files are never modified) and writes transparent waveform assets:

- ProRes 4444 `.mov` (production default)
- PNG RGBA sequence (`--format png`)

Compose those assets later in DaVinci Resolve or another NLE. This tool does not edit audio, transcribe, or assemble the final podcast video.

## Defaults you will actually use

| Choice | Name | Meaning |
|---|---|---|
| Scroll envelope (podcast target) | `iuris-default` | 60 fps, 5 s window, mirrored bars, medium glow. Limited vs linia lustrzana. Locked from operator pick `*ad0c99b500c0.mov`. |
| Fixed-axis spectrum | `iuris-spectrum` | Frequency on X (log-Hz, auto span). Vertical motion only. Experimental. |
| Performance | `balanced` | 60 s chunks, 2 jobs field (unused for parallel encode in this MVP), FFmpeg threads 0 (auto). |

Playhead envelope and particles are not available. GPU is not used.

## File names and grouping

- One source file → one waveform job.
- `s0e00-Szymon.wav` groups as project `s0e00`, track `Szymon` (first `-`).
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

# Plan: signatures, dest paths, SKIP vs PROCESS
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

- A few seconds of `iuris-default` at 60 fps is the right smoke test.
- Episode-length ProRes belongs on a machine with tens of GB free, not a tiny VM disk.
- Chunk size (`--performance balanced`, `chunk_seconds = 60`) does not change the intended look.
- `benchmark run` is for matrices of short files. Do not point the example manifest at private episode paths inside git.

## Known limits (do not treat as bugs)

- Scroll geometry is **limited** vs brand linia lustrzana (dense RMS bars, not a pixel match).
- Spectrum is **experimental** (application FFT + log-Hz span, not the particle field).
- Playhead mode is refused.
- Particles enabled in a preset are refused.
- `jobs` in a performance profile is recorded; this MVP does not fan out parallel encodes yet.
- 10-bit ProRes request vs 12-bit ffprobe readout remains an open fidelity note.

## Fresh WSL VM checklist

Use a **copy** of audio you are allowed to process. Do not commit outputs.

1. Install (`Instructions/install.md`) until `waveform doctor` is `ok`.
2. `waveform capabilities` — expect `domain:time+scroll` limited, `domain:frequency+fixed-axis` experimental, `effect:particles` unsupported, `domain:time+playhead` unsupported.
3. `inspect` a single WAV and a `s0e00-Name.wav` pair; grouping must split on the first `-`.
4. `preview` 2–8 s of speech at `iuris-default` to `--output-dir`. Confirm the `.mov` has alpha in ffprobe (`yuva`).
5. `render` the same clip. `dry-run` immediately after must show `SKIP`. `--force` must write `_v002`.
6. `render --format prores4444 --format png` and confirm both exist plus `*_results.json` and `run_*_results.json`.
7. `render --preset iuris-spectrum` on the same short clip; result JSON `analysis.fmin_hz` / `fmax_hz` populated.
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
| Disk fills with ProRes | Use `preview --duration 8`; delete `waveform-output/` / `benchmark-output/` you created; they are gitignored. |
| Resume did not reuse chunks | Checkpoint must match source hash and render signature. Stale files are discarded on purpose. |
