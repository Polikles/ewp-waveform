# Exact single-file CPU work reduction

This increment preserves mapping7, filled-ribbon-v2, all timestamps and the existing
output identity. It does not promote another finishing algorithm, encoder or style.
The ordinary CPU code benefits whether GEQ or the opt-in `ribbon-lut` profile is
selected. No multi-file concurrency or encoded-packet reuse is involved.

Two small independent changes follow an actual serial speech-service profile:

- Generate stationary PCHIP X coordinates with binary64 vector division followed
  by multiplication. Do not precombine a scale or substitute `linspace`; preserve
  coordinate bytes and keep dynamic-pivot/exotic-width fallback unchanged.
- For single-sample contour intervals, fill exact full-coverage interiors directly
  in uint8 and compute floating coverage only at their at-most-two boundary rows
  per X. Preserve edge subtraction, `rint`, minimum positive alpha and near-full
  rules. Multitap reductions/nonfinite or exotic geometry retain the old path.
  Each result still owns its complete contiguous output; this is not a borrowed
  persistent-frame buffer or allocation-free renderer.

The frozen appearance resolves to 1400x280/60, pale cyan #C7E6EC, amplitude.82,
stroke1, high glow/sigma16, smoothing.06, noise.35/rate.8/seed1729, idle0,
reflection.45 and horizon extent.96/opacity.55. Actual working geometry is a
3000x380 gray raster: 50-pixel overscan and horizontal supersampling2 of1500x380.
The refined mapping actually has129 visual slots; the existing generic analysis
summary's `visual_slots=65` is not the source of truth for its intermediate shape.

## Fresh VM.1 screens

Python3.12.3/NumPy2.5.3, explicitly selected FFmpeg8.0.1,8 visible vCPUs. Every
pair uses original source25..29s or25..57s with interval-local analysis, fresh
per-attempt cache selectors, jobs1/automatic encoder threads and qualified LUT
finishing on both sides. Service wall includes per-encode qualification/setup,
production validation and publication, but not the external comparison or views.
Each short screen isolates one variable; combined results must not be summed.

| Experiment | A median s | B median s | Observations per side |
| --- | ---: | ---: | ---: |
| stationary coordinates only,4s | 3.448032 | 3.141174 | 2, AB/BA |
| interval boundary raster only,4s | 3.550459 | 3.303027 | 2, AB/BA |
| both,32s | 17.123934 | 16.878694 | 2, AB/BA |

All same-context native MOV bytes match. The combined32s complete-time reduction
is only1.43%, descriptive small-n evidence, not a claim of substantial sustained
throughput. Generator wall decreased from about5.80s to4.17s, including field
3.01→2.34s and raster2.78→1.82s; blocking feed rose. These nested/inclusive
partial spans are non-additive and are not encoder-exclusive CPU partitions.
This explains why a generation reduction need not give equal complete-service
savings on an encoder-bound target; native Windows/WSL benefits need their own
current-code measurements. No old jobs2-to-serial or stock-to-LUT gain is credited
as new here.

## Experiments not selected

A fixed-geometry lobe-major field prototype reduced synthetic field-call cost but
its actual4s service medians3.318526→3.408495s were slower. A one-frame threaded
producer/lookahead prototype gave3.210669→3.171497s on4s, then17.384187→17.646281s
on32s. Neither prototype nor its new execution setting is integrated into main.
Their exact outputs, experimental source branches and negative observations remain
retained privately. Temporal-weight precomputation was also a descriptive near-tie
and was removed from the field prototype. No native rewrite, persistent staging or
additional queue framework is selected by these results.

Full-source confirmation and exact executed/publication identities are recorded
separately in the task result; do not relabel a later documentation commit as a
fresh timing. The canonical target command is in `EXPERIMENTS.md`, which measures
current-code worker policy and LUT independently and can add the separately
qualified CUDA combined service candidate.
