# FFmpeg spike — environment and content-free smoke tests

Captured **2026-08-27** on the reference-like Linux VM used for this repository.

These results do **not** complete the FFmpeg spike. They record toolchain presence, encoder/filter availability, and tiny `lavfi` alpha smokes. No podcast audio was used. Generated media was discarded and is not in git.

## Host

```text
OS: Ubuntu (Linux x86_64)
Python: 3.12.3
uv: 0.12.6
ffmpeg: 6.1.1-3ubuntu5
ffprobe: 6.1.1-3ubuntu5
libavcodec: 60.31.102
libavutil: 58.29.100
```

FFmpeg was built with `--enable-gpl` and includes `libx264`. Product code still must not assume a version string implies alpha/filter behavior.

## Relevant encoders

`ffmpeg -encoders` includes:

```text
png        PNG, pixel formats include rgb24 rgba rgb48be rgba64be …
prores     Apple ProRes
prores_aw  Apple ProRes
prores_ks  Apple ProRes (iCodec Pro)
```

`prores_ks` reports:

```text
Supported pixel formats: yuv422p10le yuv444p10le yuva444p10le
profile: auto / proxy / lt / standard / hq / 4444 / 4444xq
alpha_bits default: 16
```

## Relevant filters

Present and relevant to the spike:

```text
showwaves
showwavespic
geq
gblur
avgblur
overlay
alphamerge
alphaextract
format
fps
scale
split
concat
loudnorm
ebur128
pan
amerge
aformat
```

`showwaves` is the FFmpeg waveform visualizer. Capability of each product style (`classic` / `mirrored` / `filled` / `segmented`) is still unrated.

## Smoke test A — ProRes 4444 alpha (`lavfi` color)

Command (argument list, no shell interpolation):

```text
ffmpeg -hide_banner -y
  -f lavfi -i color=c=red@0.5:s=320x240:d=1:r=30,format=rgba
  -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le
  prores_alpha.mov
```

Result:

| Check | Observed |
|---|---|
| encode | success, 30 frames, duration 1.000 s, 30 fps |
| mux codec tag | `ap4h` (ProRes 4444) |
| requested pix_fmt | `yuva444p10le` |
| probed pix_fmt | `yuva444p12le` |
| decode one frame to PNG | `pix_fmt=rgba` |

Open question: encode requested 10-bit `yuva444p10le`; `ffprobe` reported `yuva444p12le`. Record and re-check during format-fidelity work. Do not treat this as a production fidelity pass.

## Smoke test B — PNG RGBA sequence (`lavfi` color)

```text
ffmpeg -hide_banner -y
  -f lavfi -i color=c=blue@0.25:s=320x240:d=0.2:r=30,format=rgba
  pngseq/frame_%03d.png
```

Result: 6 frames; `frame_001.png` is PNG color type 6 (RGBA), `ffprobe pix_fmt=rgba`, 945 bytes. `ffprobe` fps on a still PNG is not a video-rate contract.

## Smoke test C — `showwaves` to RGBA PNG (`lavfi` sine)

```text
ffmpeg -hide_banner -y
  -f lavfi -i sine=frequency=440:duration=1
  -filter_complex showwaves=s=640x120:mode=line:rate=30:colors=white,format=rgba
  -frames:v 5
  showwaves_%03d.png
```

Result: success; output `rgba`, 640x120, PNG color type 6. FFmpeg reported `dup=1`. Frame duplication at the start of `showwaves` must be measured against the FPS/timeline contract later.

## Smoke test D — short resource sample (`lavfi` sine, 5 s)

```text
/usr/bin/time -f elapsed_sec=%e cpu_sec=%S+%U max_rss_kb=%M
ffmpeg -hide_banner -y
  -f lavfi -i sine=frequency=440:duration=5
  -filter_complex showwaves=s=640x120:mode=line:rate=30:colors=white,format=rgba
  -c:v png
  timed_%03d.png
```

| Metric | Value |
|---|---|
| wall time | 0.05 s |
| CPU time | 0.03 s sys + 0.11 s user |
| peak RSS | 56068 KB |
| output frames | 151 PNG files (`dup=1`) |
| speed (FFmpeg) | 156x |

This is a synthetic 5-second sine at 640x120. It is **not** a performance-profile default and must not be used as a 30/60/180-minute estimate.

## Not yet measured

- style approximations for `classic` / `mirrored` / `filled` / `segmented`;
- glow maintainability and alpha edges;
- particles feasibility;
- chunk/resume continuity;
- ProRes/PNG visual fidelity on real speech;
- long-input resource envelopes.
