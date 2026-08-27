# FFmpeg spike — capability matrix

Environment: FFmpeg 6.1.1-3ubuntu5, CPU only, 2026-08-27. First pass: synthetic `lavfi` noise. Second pass: 8 s podcast speech cuts (s0e00, s2e9). Operator QA: noise direction was right but too thick in the center; speech is the comparison target. Media is not in git.

Ratings: `full` / `limited` / `experimental` / `unsupported`.

## Styles

| Style | Rating | FFmpeg approach | Notes |
|---|---|---|---|
| `classic` | **limited** | `showwaves=mode=p2p` + optional `drawbox` center line | On speech, a thin stroke that shows oscillation vs filled blobs. Not a whole-file ribbon. No real `stroke_width` API. |
| `mirrored` | **limited** | `showwaves=mode=cline` (`draw=scale`) | Symmetric. Translucent body. For the iuris look, map to **`filled`** (`draw=full`) instead. |
| `filled` | **full** (baseline) | `showwaves=mode=cline:draw=full` | Operator-confirmed direction. Speech envelopes are thin in quiet, thick in bursts. |
| `segmented` | **experimental** | Low-width `cline` + nearest scale + optional column gaps | Slim bars were an experiment, not a defined product graphic. Do not default to this. |

`showwaves=n=N` is **not** a safe envelope control: it changes how many samples are consumed per frame and **breaks FPS/duration** (n=16 → 8 frames for 3 s).

## Effects

| Effect | Rating | Approach | Notes |
|---|---|---|---|
| glow `low/medium/high` | **full** (baseline) | `split` + `gblur` σ=4/8/16 + `overlay` | Halo is visible; alpha of the blur is real (checkerboard shows through the halo). Halo color is a bit white/desaturated versus `#C7E6EC`. Medium (σ=8) is the proposed default. |
| particles | **unsupported** | — | No maintainable particle system. A `geq`+`random` sparkle graph is not motion, physics, or interaction. Do not ship a fragile graph to claim parity. |

## Output

| Format | Rating | Notes |
|---|---|---|
| ProRes 4444 MOV | **full** (encode path) | 8 s speech: 240 frames @ 30 fps, 480 @ 60 fps. 10-bit request vs 12-bit probe still open. |
| PNG RGBA sequence | **full** (encode path) | Use `-fps_mode cfr`. Operator: PNG stills OK. |

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
