# FFmpeg spike — fixed-axis spectrum

Operator target: a **second choosable default**. Horizontal axis is **frequency** (low left, high right), not time. No speech → a **flat** line. Speech/music → the line/bars move **vertically**. Speech energy should sit near the **middle** of the axis (`auto` from the source, or project-fixed min/max). This field is the intended **particle collision** surface in the custom renderer (especially music).

That is **not** the scrolling envelope. It does not replace linia lustrzana.

## FFmpeg `showfreqs` (8 s Szymon cut)

Renders were operator-local (`local-renders/ffmpeg-spike/spectrum/`, not in git; directory removed after download).

| Graph | Result |
|---|---|
| `showfreqs` line/bar, `fscale=log`, `ascale=sqrt` | Right *idea*: X is frequency, motion is not a horizontal scroll. Energy hugs the **left** (low Hz) and **bottom**. Not speech-in-the-middle. |
| same + `vflip`/`vstack` mirrored | Flat center line; small left-side bumps. Directionally “fixed axis”. |
| `ascale=lin` + `volume=12` | Clips to a full-height bar. Unusable. |
| `aresample=16000` | Slightly more spread; still not the product look. |

Stock `showfreqs` is a **limited** stand-in (and this FFmpeg build cannot zoom `fmin`/`fmax`). The application now maps an FFT onto a log-Hz span (`auto` or explicit) and draws mirrored bars. Still experimental vs the brand spectrum; particles remain custom-renderer.

## Contour raster experiment (not a preset/schema change)

`draw_envelope_frame` rasterizes each amplitude as an independent vertical span. Even with spatial smoothing and 12× supersample, the silhouette stays column-derived / faceted.

`draw_spectrum_frame` keeps the same per-X amplitude array, reconstructs a mirrored filled contour with Fritsch-Carlson PCHIP (no overshoot of local peaks), and uses the same glow encode path. FFT, span, EMA, and spatial smoothing are unchanged. Production default remains **columns**.

A/B (same clip, not in git):

```bash
uv run python scripts/spectrum_contour_ab.py "/path/to/file.wav" \
  --output-dir "/path/to/output-test-spectrum-ab" --duration 8
```

- A `a-columns/` — current column raster
- B `b-contour/` — PCHIP contour

Results JSON `analysis.spectrum_raster` is `columns` or `contour`. Render signature is unchanged (do not SKIP A onto B).

Operator: contour removed some faceting but the silhouette stayed lumpy/scalloped. Next lever is **spatial scale on the log-Hz axis**, not more temporal EMA and not more contour interpolation.

## Spatial Gaussian scale experiment (not a preset/schema change)

Production still uses three stacked box blurs at `sigma = width/200` (~7 px at 1400). The experiment keeps contour raster, FFT, span, sqrt scale, temporal EMA, glow, and PCHIP, and replaces the spatial LPF with a true Gaussian (edge-clamp, 3σ support):

| | Dir | Spatial |
|---|---|---|
| A | `a-spatial-1x/` | Gaussian at current σ |
| B | `b-spatial-2x/` | Gaussian at 2× σ |
| C | `c-spatial-3p5x/` | Gaussian at 3.5× σ |

```bash
uv run python scripts/spectrum_spatial_abc.py "/path/to/file.wav" \
  --output-dir "/path/to/output-test-spectrum-spatial" --duration 8
```

JSON: `spectrum_spatial_filter`, `spectrum_spatial_sigma`, `spectrum_spatial_scale`. Peak scan uses the same spatial settings as the encode so auto-gain is not a hidden amplitude change.

Operator: C (Gaussian 3.5×, σ≈24.5) made the contour smooth enough. The remaining problem is the **mapping**: a conventional LF mass on the left and a long HF tail, not a designed waveform of broad forms.

## Spectral mapping experiment (not a preset/schema change)

Keep contour raster, Gaussian 1× spatial, temporal EMA, glow, and 95th-percentile gain. Change how FFT energy becomes the silhouette:

- log-spaced bands with **RMS energy** (not per-pixel magnitude lerp);
- tilt pivoted at the log-mid of the span (highs stay visible, not equally tall);
- power compression on band amplitudes;
- PCHIP upsample into the existing contour.

| | Dir | Mapping |
|---|---|---|
| A | `a-mapping-current/` | current pixel log-resample |
| B | `b-mapping-64-tilt/` | 64 RMS bands, +3 dB/oct, compress 0.75 |
| C | `c-mapping-32-tilt/` | 32 RMS bands, +5 dB/oct, compress 0.55 |

```bash
uv run python scripts/spectrum_mapping_abc.py "/path/to/file.wav" \
  --output-dir "/path/to/output-test-spectrum-mapping" --duration 8
```

Playhead envelope remains **later** (full-file shape + cursor / GUI scrubber).
