# 04 — Input Discovery and Grouping

## Input

Required MVP: WAV, MP3. Additional FFmpeg-readable audio may be validated later.

A single file is always valid.

## Directory discovery

- direct children only by default;
- `--recursive` enables subdirectories;
- directory symlinks are not followed.

## Default grouping

```text
<project>-<track>.<extension>
```

Split on the first configured separator (`-` by default).

```text
s0e00-Szymon-Kowalski.wav
project = s0e00
track = Szymon-Kowalski
```

Ungrouped example:

```text
interview.wav
project = interview
track = interview
```

## Project vs job

Project context supports shared timeline checks/normalization. Each source track normally remains its own RenderJob/asset.

## Frame-aware timeline checks

At target FPS:

```text
<=1 frame        OK
>1 to <=3 frames WARNING
>3 frames        ERROR unless explicit override
```

Diagnostics report both time and frame differences.

## Multichannel

Default: mono visualization downmix + `W_AUDIO_STEREO_DOWNMIX`.

Explicit split-channel mode: `W_CHANNEL_SPLIT_ASSUMPTION`.

Never infer speaker isolation from channel layout alone.
