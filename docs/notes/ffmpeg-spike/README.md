# FFmpeg spike notes

Evidence for `docs/21-ffmpeg-baseline-plan.md`.

## What to record

Each note should be a testing result that can be reviewed later:

- FFmpeg/ffprobe version and build configuration that matter for alpha, filters, and encoders;
- exact command argument lists (never `shell=True` equivalents in product code);
- filter graphs;
- capability outcome (`full` / `limited` / `experimental` / `unsupported`) per style/effect/format;
- alpha and pixel-format observations;
- frame count, duration, and timing/drift;
- wall time, CPU time, peak RSS, and output size when measured;
- maintainability limits.

Time and resource reports belong here. They are part of the spike record, not disposable console output.

## What not to commit

- generated MOV/PNG/WAV/MP3;
- workdirs;
- private or full podcast episodes.

Synthetic `lavfi` probes are allowed in notes as command text and measurements. Podcast-derived samples stay out of the repository until renderer testing is ready.

## Files

- `environment.md` — host/toolchain and content-free encoder/filter smoke tests.
- `capability-matrix.md` — style/effect/output/continuity ratings.
- `findings.md` — commands, timings, chunk seam, resource table (synthetic noise).
- `speech.md` — podcast cuts, 30 vs 60 fps, motion/busyness trials.
- `reference.md` — Iuris et Logos boards vs FFmpeg; lp80 rejected.

Manual visual media is **not** stored here. On the authoring machine it lives outside the repository under `waveform-rendering/local-renders/ffmpeg-spike/` (`INDEX.md` there lists what to play).
