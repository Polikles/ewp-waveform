# 15 — Glossary

**Application Config** — General behavior such as discovery, output defaults, and workdir policy.

**Benchmark Manifest** — TOML definition of automated experiment matrices; distinct from a future project manifest.

**Canonical Frame** — Intended RGBA frame before format-specific encoding in the custom-renderer model.

**Continuity Strategy** — Method preserving temporal state across chunks (stateful, overlap, hybrid, etc.).

**Effect** — Composable processing distinct from base waveform style, such as glow or particles.

**Performance Profile** — Runtime/resource settings such as chunk size and parallelism; does not intentionally define appearance.

**Preview Template** — Non-canonical composition settings used for quick visual evaluation.

**Project** — Related source tracks sharing timeline/normalization context.

**Render Job** — One canonical waveform asset from one source track.

**Render Signature** — Deterministic intended visual identity; excludes format/performance settings.

**Renderer** — Backend that executes a canonical job, initially FFmpeg and later a custom renderer.

**Style** — How amplitude is drawn (classic/mirrored/filled/segmented).

**Visualization domain** — What the horizontal axis means: `time` (envelope vs time) or `frequency` (fixed frequency axis).

**Scroll envelope** — Time-domain mode: a sliding window of recent amplitude; the shape moves as speech proceeds.

**Playhead envelope** — Time-domain mode: whole-file envelope stays still; a cursor moves. Deferred.

**Fixed-axis spectrum** — Frequency-domain mode: left = lower Hz, right = higher Hz; amplitude moves vertically; silence is flat.

**Visual Preset** — TOML configuration defining intended appearance.

**Workdir** — Temporary or explicitly persistent intermediate/checkpoint directory.
