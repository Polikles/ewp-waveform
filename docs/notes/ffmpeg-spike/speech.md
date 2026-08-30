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

## Strobing and remaining clip (operator, 2026-08-28)

60 fps was only slightly better. Both fps **strobed**, and peaks still looked cut off.

Cause of the strobe: a 3 px bar + 1 px gap sliding across the pixel grid beats 3 frames (phase 0 / 0.33 / 0.67). Integer-aligned frames look gappy; half-pixel frames look filled-in. That is contrast pumping, not a decode error.

Cause of remaining clip: amplitude **0.95** put typical peaks ~11 px from the frame edge, so `gblur` σ=8 still hit the crop. The 95th-percentile auto-gain plus 0.95 fill stacked.

Changes: amplitude **0.80**; 4× horizontal supersample + `scale=flags=area` before glow; visual contract v3.

Watch: `*f3217e311b57.mov` (30 fps) and `*a4e87708204d.mov` (60 fps). Still check at t=6 s: peak cores ~30 px from the frame edge; row 0 alpha is 0 (glow fully inside). Consecutive 60 fps frames no longer alternate gappy vs filled-in.

## Gapless bars + calculated height (operator, 2026-08-28)

Clipping remained (hard rectangular ceiling + 3+1 lattice). Operator: vertical size should be calculated; bars thicker, maybe no visible gap.

- Peak half-height = `canvas/2 − glow_overscan(σ)` (σ=8 → 26 px). Amplitude 1.0 fills that safe region.
- Soft-clip on (preset already requested it): 95th percentile → knee 0.88, louder samples compress toward 1.
- Sqrt mapping runs **before** normalize so perceptual scale does not bunch peaks at the ceiling.
- Mirrored stroke **6 px**, **gap 0**. Visual contract v4.

Watch: `*728223528a30.mov` (30 fps) and `*493363baea48.mov` (60 fps). t=6 s: peak cores ~33 px from the frame edge, row 0 alpha 0. Consecutive 60 fps frames keep similar bar density (no gappy/filled-in pump).

## Envelope lerp (operator, 2026-08-28)

30 fps still jittery, 60 fps better but snap remained. Cause: `round(world_1x)` nearest-neighbour on 1-bin-per-column RMS. Geometry was supersampled; envelope was not.

Fix: `sample_bin()` linear interpolation; gapless path draws one ss-pixel column per interpolated sample; vertical coverage on bar ends. Visual contract v5.

Watch: `*5b43502ac546.mov` (30 fps) and `*40e84d4929f6.mov` (60 fps).

## Envelope smoothing (operator, 2026-08-28)

Lerp removed nearest-neighbour snap, but hop-scale spikes were hair-thin and strobed again. Operator: smooth the scrolling envelope; visible bars/spikes belong on the fixed-axis render.

`signal.smoothing` (already 0.15 in `iuris-default`) is now applied as **0.15 seconds** of Gaussian-approx blur (not 15 % of the viewport — that turned the wave into a tube). Visual contract v6. Spectrum path unchanged.

Watch: `*941113acaca9.mov` (60 fps, oversample 4). Scroll diagnostic Δpx is constant 4.666… at 60 fps.

## Envelope reconstruction AA (operator, 2026-08-28)

Dense 4× envelope restored shape but sub-pixel spikes strobed (glow off did not fix it). Scroll timing unchanged.

Same 8 s / 60 fps / oversample 4 / smoothing 0:

| File | Filter |
|---|---|
| `*iuris-aa-none_d484fdc73371.mov` | none |
| `*iuris-aa-area_1252481bb37a.mov` | area, support 1 output px |
| `*iuris-aa-lanczos2_d8c292d5723f.mov` | lanczos a=2 |

Operator: 1–2 px kernels still hairy. Lanczos keeps 1 px features (that's the main lobe). Next:

| File | Filter |
|---|---|
| `*iuris-aa-area2_05fa28be1df8.mov` | area, 2 px |
| `*iuris-aa-area3_00ae365bd7ec.mov` | area, 3 px |
| `*iuris-aa-lanczos3_ff44ab484843.mov` | lanczos a=3 |

`signal.envelope_aa` is independent of `signal.smoothing`.

## 12x raster + 200 deg shutter (operator, 2026-08-28)

area@3 still shimmered: 4.67 px/frame 3-phase beat. Raster supersample 12x; shutter 200 deg (`avgblur` before glow). Fractional hop (no truncated integer hop). Scroll Δ still 14/3 px/frame.

Watch: `*iuris-default_07cbef24e059.mov`.

## Crisp hybrid shutter (operator, 2026-08-28)

200° shutter made the base look out of focus. New graph: 12x raster, area-downsample, then `0.75*sharp + 0.25*light_horizontal_gblur`; glow from that mask, overlay **under** the sharp-ish base. Envelope AA back to 1.0 px. Default shutter 60°.

| | shutter | AA support | file |
|---|---|---|---|
| A | 0° | 1.5 | `*iuris-abc-a_a8cea6f69661.mov` |
| B | 60° | 1.0 | `*iuris-abc-b_81f708930774.mov` |
| C | 90° | 1.0 | `*iuris-abc-c_ff8080a0283d.mov` |

## Motion-Nyquist envelope LOD (operator, 2026-08-28)

Remaining strobe is 1–4 px needles above temporal Nyquist (0.107 cyc/px at 280 px/s / 60 fps). Sinc LPF on amplitude-vs-X at 0.85× that (~0.091 cyc/px). Raster stays 12× and crisp; shutter 0 for this eval.

**Adopted as `iuris-default` for now:** `*iuris-default_ad0c99b500c0.mov`.

## No-glow comparison (operator, 2026-08-28)

Shape of the dense envelope is better, but spikes strobe with medium glow. Comparison (same hop/oversample/60 fps, glow disabled):

`app-render/s0e00/*iuris-default-noglow_54d802329ca0.mov`

Local preset (not in git): `local-renders/ffmpeg-spike/iuris-default-noglow.toml`.

## Denser envelope + 60 fps default (operator, 2026-08-28)

Smoothed envelope killed stutter but looked too rubbery. Remaining 30 fps judder is ~9.3 px/frame vs ~4.7 at 60 fps — do not fix by quantizing scroll.

- Default canvas FPS is **60**.
- `envelope_oversample = 4`: hop is `sr * window / (width * 4)` so four **real** RMS bins per output pixel.
- `smoothing = 0`.
- Fractional timestamp scroll unchanged. Lerp only between adjacent dense bins.
- Diagnostic: `iter_scroll_timing` (frame, t, phase, frac, expected Δpx, envelope position) must have constant Δ.

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
