# FFmpeg spike — findings (synthetic)

Date: **2026-08-27**. CPU only. FFmpeg **6.1.1-3ubuntu5**.

Visual media for this run lives **outside the repo** (`waveform-rendering/local-renders/ffmpeg-spike/`). This file is the committed testing result.

## Method

Common canvas: **1400×280**, **30 fps**, waveform color **`#C7E6EC`**.

Audio (unless noted):

```text
anoisesrc=duration=D:color=pink:amplitude=0.7:sample_rate=48000
tremolo=f=1.4:d=0.85
```

Alpha (luma-as-alpha, not `colorkey`):

```text
format=rgba
geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='max(r(X,Y),max(g(X,Y),b(X,Y)))'
```

ProRes:

```text
-c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le
```

PNG sequences used `-fps_mode cfr -r 30`.

`showwaves` is a **per-frame window of PCM samples** across the width. A 220 Hz sine looks like several cycles of an oscilloscope. Pink noise looks like a dense amplitude band. That is the FFmpeg-native animated waveform, not a static whole-file ribbon (`showwavespic`).

## Styles

### classic — limited

```text
showwaves=s=1400x280:mode=p2p:rate=30:colors=0xC7E6EC:scale=sqrt
+ luma-as-alpha
+ drawbox center line (y=139, h=2, color 0xC7E6EC@0.6)
```

3 s encode: 90 frames, ~1.00 s wall.

Looks like a thin oscilloscope with a center line. There is no real stroke-width or geometry API.

### mirrored — limited

```text
showwaves=s=1400x280:mode=cline:rate=30:colors=0xC7E6EC:scale=sqrt
```

Symmetric about the center. Checkerboard stills show a **see-through body** (`draw=scale`).

### filled — full (baseline)

```text
showwaves=s=1400x280:mode=cline:rate=30:colors=0xC7E6EC:scale=sqrt:draw=full
```

3 s encode: 90 frames, ~1.00 s wall. Opaque filled band; checkerboard only shows through true background. Closest to the intended iuris mirrored/filled look.

### segmented — experimental

Low-resolution `cline` + nearest-neighbor upscale. Optional `geq` punches vertical gaps (`mod(X,28)<18`).

```text
showwaves=s=48x280:mode=cline:rate=30:colors=0xC7E6EC:scale=sqrt:draw=full
scale=1400:280:flags=neighbor
+ luma-as-alpha
+ geq gaps
```

On a checkerboard this reads as discrete bars. **3.033 s / 91 frames** for 3 s of audio (expected 90). Do not treat as FPS-safe until that extra frame is eliminated (`-fps_mode cfr` / explicit `-r` after scale, or avoid shrinking width).

### Unsafe: `n`

`showwaves=n=4|16|64` reduced frame count (27 / 8 / 3 frames for 3 s). Do not use `n` to fake an envelope while keeping the timeline contract.

## Glow — full (baseline)

```text
[wave]split=2[base][g]
[g]gblur=sigma=S:steps=3[gb]
[gb][base]overlay=format=auto:shortest=1,format=rgba
```

| Level | sigma | 3 s wall |
|---|---|---|
| low | 4 | 1.33 s |
| medium | 8 | 1.38 s |
| high | 16 | 1.33 s |

Stills show a real halo. Checkerboard shows the halo alpha. Overlay did **not** strip the alpha channel in this build. Halo is slightly white versus the waveform color. Medium is the proposed FFmpeg default.

## Particles — unsupported

A second `geq` using `random(X+Y*1400+N*9973)` did not produce a usable particle system (no motion model, no interaction, no persist). FFmpeg MVP should **fail clearly** if particles are requested (`FR-RENDER-008`).

## Timeline

| Clip | Expected frames | Observed |
|---|---|---|
| 3 s ProRes filled | 90 | 90 |
| 5 s ProRes filled | 150 | 150 |
| 5 s PNG + `fps_mode cfr` | 150 | 150 |
| 30 s ProRes filled+glow | 900 | 900 |
| 30 s PNG + `fps_mode cfr` | 900 | 900 |

Earlier PNG smokes without `cfr` reported `dup=1`. Product PNG output should force CFR.

## Chunking

Uninterrupted 6 s: 180 frames, 6.000 s.

Naive:

```text
asplit=2
atrim=0:3 / atrim=3:6
asetpts=PTS-STARTPTS
showwaves… (each)
concat=n=2:v=1:a=0
```

Concat: **180 frames, 6.000 s** (count OK).

Visual: at **t=3.00 s** the concat output is **only drawn on the right half** of the canvas. t=2.90 and t=3.10 look full-width. The uninterrupted clip is full-width at t=3.00.

Conclusion: `showwaves` has a **warm-up / partial window** at stream start. Application-layer chunking must **preroll extra audio and discard warm-up frames** (overlap). Do not concat raw encoder segments at the logical boundary.

Glow/blur would need the same preroll (and more, because `gblur` is spatial; temporal glow is not in this graph).

## Resources (CPU, this VM)

Filled+medium glow, 1400×280, 30 fps, pink-noise 30 s:

| Output | Wall | CPU user+sys | Peak RSS | Size | Speed |
|---|---|---|---|---|---|
| ProRes 4444 | 12.81 s | 67.91 s | 166 MB | 377 MB | 2.34× |
| PNG sequence | 11.19 s | 51.20 s | 82 MB | 109 MB / 900 files | 2.68× |

Linear extrapolation **only as a disk warning**, not a profile default:

- ~12.5 MB/s ProRes → on the order of **45 GB / 60 min** at this canvas
- PNG ~3.6 MB/s → on the order of **13 GB / 60 min**

Long-file and speech measurements wait for samples. Peak RAM stayed ~170 MB on 30 s; this graph is not a whole-file decode, which is good for `NFR-PERF-001`.

3 s style encodes were ~1.0 s wall and ~170 MB RSS (survey).

## Answers to `docs/21` completion questions (partial)

1. **Maintainable styles:** `filled` (cline+draw=full) yes; `classic` as p2p stroke yes with limits; `mirrored` yes if we use `draw=full` or accept translucency; `segmented` only experimental.
2. **Alpha:** luma-as-alpha + ProRes 4444 / PNG RGBA worked in this build. `colorkey` was not needed. 10-bit request vs 12-bit probe remains an open fidelity question.
3. **Costs:** see resource table. Glow did not change 3 s wall time much versus base (~1.0 vs ~1.3 s). ProRes size is the production risk.
4. **Continuity:** naive chunk concat fails visually at the join. Preroll/overlap belongs in the **application** layer.
5. **Application responsibilities:** discovery, signatures, overlap/preroll, CFR PNG, capability refusals (particles), not FFmpeg CLI in the public model.
6. **Custom renderer motivation (already):** particles, true stroke geometry, per-bar segmented control, temporal glow, pixel-identical chunk joins without preroll hacks. FFmpeg remains a valid MVP baseline for filled+glow.

## Still open (needs samples and/or operator eyes)

- Speech / silence / transients
- 30 / 60 / 180 min endurance
- ProRes vs PNG visual delta on the same identity
- Glow color match
- Segmented extra-frame bug
- Operator visual sign-off of `local-renders` (this checkpoint)
