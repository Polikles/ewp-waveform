# FFmpeg spike — brand reference vs FFmpeg

Operator dropped `lowpass=80` (“looks like crap”; sine beads are not the target).

Authoring-machine stills (not in git): `waveform-rendering/reference/`

| File | What it is |
|---|---|
| `warianty wizualizacji.png` | Four waveform **styles** + glow levels + 1/2/3-speaker thumbnails + palette |
| `motywy.png` | Visual system: logos, type, **wave motif**, speaker colors, palette, background pattern |
| `1 mówca.png` | Preview composition: one centered wave |
| `2 mówców.png` | Two waves side by side + caption cards |
| `3 mówców.png` | Guest on top, two hosts below |

These boards are the look target. FFmpeg `showwaves` at 30 fps (≈33 ms of PCM across the width) is a different geometry. That is why speech felt too fast/busy, and why lp80 turned into sine blobs.

## Style names (Polish board → registry)

| Board | Glow on board | Registry | Geometry |
|---|---|---|---|
| 1 Linia klasyczna | niski | `classic` | Thin vertical amplitude ticks, mirrored about center, sparse |
| 2 Linia lustrzana | średni | `mirrored` | Vertical bars, mirrored, denser; **motif used on 1/2/3-speaker templates** |
| 3 Wstęga wypełniona | wyższy | `filled` | Smooth filled ribbon / envelope, stronger glow |
| 4 Impuls segmentowy | średni | `segmented` | Discrete separated columns (rounded bars), not a slim cut of a sausage |

All four are **amplitude over a phrase-length time axis**, not a live oscilloscope of the current video frame’s samples.

## Colors (match `iuris-default` palette)

| Name | Hex | Use on boards |
|---|---|---|
| Steel blue | `#3D5D73` | UI / chrome |
| Periwinkle blue | `#6E7BA7` | Speaker 2 wave (blue) |
| Slate teal | `#2F474F` | Background (preview template) |
| Pale cyan | `#C7E6EC` | Speaker 1 wave (default) |
| Soft yellow | `#F2C558` | Speaker 3 wave (board swatch `#F2C55B`, treat as the same token) |

Templates: speaker 1 light cyan, speaker 2 blue, speaker 3 yellow. Tiny sparkles around the bars are the **particle** motif (FFmpeg: still unsupported).

## Composition vs canonical asset

`1/2/3 mówców.png` are **preview/GUI layouts** (logos, titles, captions, dark pattern). `ewp-waveform` still emits a **transparent waveform per track**. Those layouts belong in preview templates (`docs/19`), not in the render identity.

## What FFmpeg can approximate

On the 8 s Szymon cut (operator-local `local-renders/ffmpeg-spike/reference-match/`):

| Graph | vs boards |
|---|---|
| `showwaves` rate=30 `cline` | Wrong time window (too fast). Reject as the look target. |
| `lowpass=80` + `cline` | Sine beads. **Rejected.** |
| `showwavespic` of the clip | **Right time scale**: whole phrase as one mirrored envelope. Closest still. Looks like wstęga, not discrete bars. |
| `showwavespic` + medium glow | Same, with halo. |
| `showwaves` `rate=1` then play at 30 fps | ~1 s of audio per unique frame; motion is slower. Still a connected band, not linia lustrzana. |
| 100-column nearest-neighbor bars | Blocky sausage, not the board’s bar code. |

Faithful **linia lustrzana** (vertical strokes, phrase window, medium glow, optional sparkles) is a **custom-renderer / application envelope** job. FFmpeg MVP can ship a **limited** `showwavespic`-style or long-window envelope as a stand-in, and must not pretend lp80 or 33 ms `showwaves` is the brand.

## Default

Brand default on the boards: **linia lustrzana + średni glow**, speaker-1 pale cyan, 30 fps preview.

`iuris-default` style is **`mirrored`**, glow **medium**, fps **30**. FFmpeg capability for that style remains **limited** until envelope-over-window bars exist.
