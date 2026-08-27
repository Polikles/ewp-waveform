# FFmpeg spike — capability matrix

Environment: FFmpeg 6.1.1-3ubuntu5, CPU only, 2026-08-27. Synthetic `lavfi` audio. Manual frame inspection of PNG stills plus checkerboard composites. Media is not in git; see `../local-renders` on the authoring machine.

Ratings: `full` / `limited` / `experimental` / `unsupported`.

## Styles

| Style | Rating | FFmpeg approach | Notes |
|---|---|---|---|
| `classic` | **limited** | `showwaves=mode=p2p` + optional `drawbox` center line | Readable stroke. It is a **current-window oscilloscope**, not a whole-file ribbon. Stroke width is not a real `stroke_width` control. |
| `mirrored` | **limited** | `showwaves=mode=cline` (default `draw=scale`) | Naturally symmetric about center. Body is semi-transparent because `draw=scale` accumulates coverage. |
| `filled` | **full** (baseline) | `showwaves=mode=cline:draw=full` | Best match to a filled mirrored podcast waveform. Opaque body, alpha from luma-as-alpha `geq`. |
| `segmented` | **experimental** | Low-width `cline` + `scale=flags=neighbor` + optional `geq` column gaps | Looks like bars on a checkerboard. 3 s encodes produced **91 frames** (expected 90). Not a per-bar amplitude meter; still a windowed waveform. |

`showwaves=n=N` is **not** a safe envelope control: it changes how many samples are consumed per frame and **breaks FPS/duration** (n=16 → 8 frames for 3 s).

## Effects

| Effect | Rating | Approach | Notes |
|---|---|---|---|
| glow `low/medium/high` | **full** (baseline) | `split` + `gblur` σ=4/8/16 + `overlay` | Halo is visible; alpha of the blur is real (checkerboard shows through the halo). Halo color is a bit white/desaturated versus `#C7E6EC`. Medium (σ=8) is the proposed default. |
| particles | **unsupported** | — | No maintainable particle system. A `geq`+`random` sparkle graph is not motion, physics, or interaction. Do not ship a fragile graph to claim parity. |

## Output

| Format | Rating | Notes |
|---|---|---|
| ProRes 4444 MOV | **full** (encode path) | `prores_ks` `-profile:v 4444`. Requested `yuva444p10le`; `ffprobe` reports `yuva444p12le` / `ap4h`. 3 s → 90 frames; 5 s → 150; 30 s → 900. |
| PNG RGBA sequence | **full** (encode path) | Use `-fps_mode cfr -r 30`. 5 s and 30 s matched frame count. Without `cfr`, earlier smokes showed `dup=1`. |

Cross-format visual fidelity on real speech is **not** measured yet.

## Continuity

| Topic | Rating | Notes |
|---|---|---|
| Uninterrupted `showwaves` | **full** on synthetic clips | Frame count matches `duration * fps` when `n` is left automatic. |
| Naive chunk concat | **limited / fail** | `atrim` 0–3 + 3–6 + `concat` has the right **frame count** (180 / 6 s) but the **first frame of chunk 2 is only half-drawn**. `showwaves` needs a warm-up / preroll. Application overlap must drop the warm-up frames. |

## What this does *not* decide

- Speech, silence, transients, or real episode loudness
- 30 / 60 / 180 min endurance (only a 30 s CPU sample)
- GPU
- Custom-renderer stack
