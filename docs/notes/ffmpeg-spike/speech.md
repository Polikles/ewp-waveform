# FFmpeg spike — speech cuts

Date: **2026-08-27**. Operator QA of noise renders: direction is right; noise made the center too thick to compare styles/glow. Chunk concat seam confirmed. `segmented_gaps` look was unclear as a product use.

Sources (not in git): `waveform-rendering/zz-audio-samples/` (s0e00, s0e01, s2e9). Isolated mono WAV 48 kHz. s2e9 mix/isolates ~50 min.

Cuts (not in git): `local-renders/ffmpeg-spike/cuts/`.

| Cut | Source | Purpose |
|---|---|---|
| `s0e00-Szymon_08-20.wav` | s0e00-Szymon | primary 12 s speech (renders used first 8 s) |
| `s0e00-Damian_25-37.wav` | s0e00-Damian | second speaker |
| `s0e00-mix_08-20.mp3` | s0e00.mp3 | mix (not used in this pass) |
| `s0e01-Szymon_60-72.wav` | s0e01-Szymon | extra speech (not used in this pass) |
| `s2e9-Damian_250-262.wav` | S2E9-Damian @ 4:10 | later-episode speech |
| `s2e9-Szymon_37-49.wav` | S2E9-Szymon | later-episode other speaker (not used in this pass) |

Whole s2e9 (~50 min) and a future ~2.5 h glue file are **out of this VM** (ProRes at 1400×280 is on the order of 45 GB/hour). Keep long jobs off the 28 GB disk.

## Renders to watch

`local-renders/ffmpeg-spike/speech/mov/` (8 s ProRes 4444):

| File | What |
|---|---|
| `szymon_classic_30.mov` | p2p stroke + center line @ 30 |
| `szymon_filled_30.mov` | cline `draw=full` @ 30 |
| `szymon_glow_low_30.mov` | filled + gblur σ=4 |
| `szymon_glow_med_30.mov` | filled + gblur σ=8 |
| `szymon_glow_high_30.mov` | filled + gblur σ=16 |
| `szymon_filled_60.mov` | filled @ 60 |
| `szymon_glow_med_60.mov` | filled + medium glow @ 60 |
| `damian_filled_glow_med_30.mov` | other speaker, same graph |
| `s2e9_damian_filled_glow_med_30.mov` | s2e9 cut, same graph |
| `szymon_lp80_glow_med_30.mov` | optional less-busy envelope (`lowpass=80`) |

Stills: `speech/frames/` and `speech/composites/`. Frame counts: 240 @ 30 fps, 480 @ 60 fps for 8.000 s.

## What changed vs noise

Speech envelopes are **thin in quiet, thick in bursts**. Classic vs filled is obvious. Glow low/medium/high are distinguishable (high halo is clearly larger). Noise had hidden that.

## Operator follow-up (filled + glow medium @ 30)

Accepted as the **reasonable FFmpeg default**. Waveform is a bit busy. **30 fps** is the preview default; **60 fps** is smoother / fuller detail and a separate render identity.

Long episodes stay on the operator workstation. This VM will not process full s2e9 or the ~2.5 h glue file.

## Motion (“too fast”) and busyness

Not a trivial FFmpeg fix. `showwaves` draws about `1/fps` seconds of PCM across the width, so at 30 fps you see ~33 ms of raw speech (glottal detail) racing by.

Tried on the same 8 s Szymon cut:

| Graph | Result |
|---|---|
| current default | busy, readable envelope, fast motion |
| `lowpass=f=80` then filled+glow | less busy, bead-like syllables; **watch** `szymon_lp80_glow_med_30.mov` |
| `lowpass=f=40` / `20` | too thin / dead |
| `tmix=frames=8` | smeared ghosts; reject |

Lowpass ~80 Hz is a candidate mapping for preset `signal.smoothing`, not adopted. Slowing the *scroll* needs a longer display window (application buffer or custom renderer).

## 30 vs 60 fps

Both encode cleanly. **They are not the same picture.** `showwaves` maps about `1/fps` seconds of PCM across the width, so 60 fps shows a shorter time window (more zoomed-in / smoother sausages) and 30 fps shows more of the syllable in one frame. That is why FPS is already in render identity (`FR-RENDER-005`, `FR-RENDER-013`).

DaVinci comparison of the same clip at 30 vs 60 is still an operator test (this VM does not run Resolve).

## `segmented`

The slim-bar `segmented_gaps` graph was an **experiment**: downscale `cline` then punch vertical gaps so bars sit on transparent background. It was intended as “discrete columns”, not as a default podcast look. There is no current EWP use for that graphic. FFmpeg rating stays **experimental**; do not ship it as the iuris default.

## Long jobs

Not run here: full s2e9, 60 min, 2.5 h. Disk and ProRes size rule them out on this VM. Short s2e9 cut at 4:10 looks consistent with s0e00 Damian (same filled+glow graph, speech-shaped, not noise-sausage).
