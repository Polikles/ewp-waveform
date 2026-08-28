# FFmpeg spike — fixed-axis spectrum

Operator target: a **second choosable default**. Horizontal axis is **frequency** (low left, high right), not time. No speech → a **flat** line. Speech/music → the line/bars move **vertically**. Speech energy should sit near the **middle** of the axis (`auto` from the source, or project-fixed min/max). This field is the intended **particle collision** surface in the custom renderer (especially music).

That is **not** the scrolling envelope. It does not replace linia lustrzana.

## FFmpeg `showfreqs` (8 s Szymon cut)

Renders: `local-renders/ffmpeg-spike/spectrum/` (not in git).

| Graph | Result |
|---|---|
| `showfreqs` line/bar, `fscale=log`, `ascale=sqrt` | Right *idea*: X is frequency, motion is not a horizontal scroll. Energy hugs the **left** (low Hz) and **bottom**. Not speech-in-the-middle. |
| same + `vflip`/`vstack` mirrored | Flat center line; small left-side bumps. Directionally “fixed axis”. |
| `ascale=lin` + `volume=12` | Clips to a full-height bar. Unusable. |
| `aresample=16000` | Slightly more spread; still not the product look. |

Stock `showfreqs` is a **limited** stand-in. Faithful mirrored spectrum with a speech-centered range is application analysis + custom renderer (or a much more carefully specified filter graph later). Do not treat these MOV files as the default look.

Playhead envelope remains **later** (full-file shape + cursor / GUI scrubber).
