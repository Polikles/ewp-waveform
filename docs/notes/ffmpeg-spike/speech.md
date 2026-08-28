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
| `szymon_lp80_glow_med_30.mov` | **rejected** (`lowpass=80` sine beads) |

Stills: `speech/frames/` and `speech/composites/`. Frame counts: 240 @ 30 fps, 480 @ 60 fps for 8.000 s.

## What changed vs noise

Speech envelopes are **thin in quiet, thick in bursts**. Classic vs filled is obvious. Glow low/medium/high are distinguishable (high halo is clearly larger). Noise had hidden that.

## Operator follow-up

`lowpass=80` rejected. Brand boards supersede the earlier “filled + glow medium is the look” decision: that was the least-bad `showwaves` sausage, not linia lustrzana.

**30 fps** remains the preview default; **60 fps** is fuller detail. Long episodes stay on the operator workstation.

## Application scroll (operator, 2026-08-28)

`waveform preview` `iuris-default` on `s0e00-Szymon_08-20.wav` (8 s):

- Heights staying put after the bar grid was locked to the envelope is **confirmed**.
- Remaining defects on `*65340e3ea877_v002.mov`: motion looked **chopped**; some bars **clipped / cut off** at the frame edge (glow `gblur` truncated at the canvas).
- Fix: draw on a padded canvas (`glow_overscan`, σ=8 → 26 px), `gblur` then `crop` back to 1400×280; place bars at a **fractional** scroll phase with coverage-antialiased edges.
- Still check (t=6 s, 30 fps `*ed7111fcb7b1.mov`): tallest solid bar inset ~11 px; edge rows have glow alpha only (no solid 255). Previous `*v002` still at t=2 had zero alpha on rows 0–3 (glow truncated).
- 30 fps at this window is still ~9.3 px/frame (~2 bar periods). That is stepped, not a `tmix` smear (`tmix=frames=8` already rejected). Watch 60 fps `*e0c0b6911bb7.mov` (~4.7 px/frame) for smoother travel.

## Motion (“too fast”) and busyness

Not a trivial FFmpeg fix. `showwaves` draws about `1/fps` seconds of PCM across the width, so at 30 fps you see ~33 ms of raw speech (glottal detail) racing by.

Tried on the same 8 s Szymon cut:

| Graph | Result |
|---|---|
| current default | busy, readable envelope, fast motion |
| `lowpass=f=80` then filled+glow | **rejected** (sine beads) |
| `lowpass=f=40` / `20` | too thin / dead |
| `tmix=frames=8` | smeared ghosts; reject |

`lowpass=80` is **rejected** as a look (operator: sine waves, not the brand). Slowing motion needs a **phrase-length envelope window** (see `reference.md`), not a PCM lowpass.

## 30 vs 60 fps

Both encode cleanly. **They are not the same picture.** `showwaves` maps about `1/fps` seconds of PCM across the width, so 60 fps shows a shorter time window (more zoomed-in / smoother sausages) and 30 fps shows more of the syllable in one frame. That is why FPS is already in render identity (`FR-RENDER-005`, `FR-RENDER-013`).

DaVinci comparison of the same clip at 30 vs 60 is still an operator test (this VM does not run Resolve).

## `segmented`

Board **impuls segmentowy** is discrete rounded columns of a phrase envelope. The slim-gap sausage was the wrong experiment. FFmpeg stays **experimental** for this style.

## Long jobs

Not run here: full s2e9, 60 min, 2.5 h. Disk and ProRes size rule them out on this VM. Short s2e9 cut at 4:10 looks consistent with s0e00 Damian (same filled+glow graph, speech-shaped, not noise-sausage).
