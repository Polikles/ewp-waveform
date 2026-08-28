# FFmpeg spike — capability matrix

Environment: FFmpeg 6.1.1-3ubuntu5, CPU only, 2026-08-27. First pass: synthetic `lavfi` noise. Second pass: 8 s podcast speech cuts (s0e00, s2e9). Operator QA: noise direction was right but too thick in the center; speech is the comparison target. Media is not in git.

Ratings: `full` / `limited` / `experimental` / `unsupported`.

## Styles

| Style | Rating | FFmpeg approach | Notes |
|---|---|---|---|
| `classic` | **limited** | phrase-length thin ticks (linia klasyczna) | 33 ms `showwaves` is the wrong window. |
| `mirrored` | **limited** | phrase-length vertical bars (linia lustrzana) | **Brand default.** FFmpeg has no faithful bar-envelope yet. `showwavespic` is the right time scale, wrong stroke. |
| `filled` | **limited** | wstęga / ribbon | `showwavespic` of a short clip is the closest FFmpeg still. Not the template default. |
| `segmented` | **experimental** | impuls segmentowy (discrete columns) | Board defines the look. Slim-gap sausage was the wrong experiment. |

`showwaves=n=N` is **not** a safe envelope control: it changes how many samples are consumed per frame and **breaks FPS/duration** (n=16 → 8 frames for 3 s).

## Effects

| Effect | Rating | Approach | Notes |
|---|---|---|---|
| glow `low/medium/high` | **full** as blur | `split` + `gblur` σ=4/8/16 + `overlay` | Maps to niski / średni / wyższy on the boards. Medium is the brand default. Does not create vertical bars. |
| particles | **unsupported** | — | Boards show sparkles around bars. No maintainable FFmpeg particle system. |

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

- Faithful linia lustrzana (phrase-length vertical bars)
- 30 / 60 / 180 min endurance (workstation)
- GPU
- Custom-renderer stack
