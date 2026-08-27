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

**Style** — Primary waveform representation (classic/mirrored/filled/segmented).

**Visual Preset** — TOML configuration defining intended appearance.

**Workdir** — Temporary or explicitly persistent intermediate/checkpoint directory.
