# 02 — Requirements

## Requirement ID glossary

- **FR** — Functional Requirement
- **NFR** — Non-Functional Requirement
- **CLI** — command-line interface
- **IN** — input discovery/inspection
- **GROUP** — grouping/timeline consistency
- **RENDER** — rendering/job behavior
- **STYLE** — waveform styles
- **EFFECT** — visual effects
- **NORM** — visualization normalization
- **OUTPUT** — encoded outputs/publication
- **RESULT** — result data contract
- **RESUME** — chunking/checkpoint/recovery
- **PREVIEW** — preview
- **CONFIG** — configuration
- **BENCH** — benchmarking
- **DET** — determinism
- **MAINT** — maintainability
- **PERF** — performance
- **PORT** — portability
- **TEST** — testing/acceptance

## Functional requirements

### CLI

- **FR-CLI-001** — Preferred executable is `waveform`; a material collision requires an ADR before changing it.
- **FR-CLI-002** — `waveform render INPUT` accepts one file or one directory.
- **FR-CLI-003** — Directory processing is non-recursive by default.
- **FR-CLI-004** — Recursion requires an explicit flag and must not follow directory symlinks.
- **FR-CLI-005** — CLI provides `preview`, `inspect`, `dry-run`, `doctor`, and `capabilities`.
- **FR-CLI-006** — CLI overrides have highest effective priority.
- **FR-CLI-007** — Warnings/errors use stable descriptive identifiers.
- **FR-CLI-008** — Exit behavior distinguishes success, config/input/capability/render failures, and partial multi-job failure.
- **FR-CLI-009** — CLI provides `preset`, `performance`, `benchmark`, and `clean` commands as specified in `05-cli-specification.md`.

### Input/grouping

- **FR-IN-001** — WAV and MP3 are required MVP inputs.
- **FR-IN-002** — Additional FFmpeg-readable audio may be supported after validation.
- **FR-IN-003** — Source media is immutable.
- **FR-IN-004** — Multichannel input downmixes to mono by default with `W_AUDIO_STEREO_DOWNMIX`.
- **FR-IN-005** — Explicit split-channel mode emits `W_CHANNEL_SPLIT_ASSUMPTION`.

- **FR-GROUP-001** — Default grouping uses `<project>-<track>` split on the first configured separator.
- **FR-GROUP-002** — Default separator is `-`.
- **FR-GROUP-003** — Grouping is configurable.
- **FR-GROUP-004** — Ungrouped filenames remain valid single-track projects.
- **FR-GROUP-005** — Tracks in a project are expected to share a common timeline.
- **FR-GROUP-006** — Duration mismatch is evaluated against target FPS.
- **FR-GROUP-007** — Difference <=1 frame is accepted.
- **FR-GROUP-008** — Difference >1 and <=3 frames is accepted with a warning.
- **FR-GROUP-009** — Difference >3 frames rejects the group unless explicitly overridden.

### Rendering/styles/effects

- **FR-RENDER-001** — One source track normally maps to one canonical waveform asset.
- **FR-RENDER-002** — Public job/config models are independent of FFmpeg syntax.
- **FR-RENDER-003** — FFmpeg is the MVP/reference renderer.
- **FR-RENDER-004** — FFmpeg remains selectable after a custom renderer is introduced.
- **FR-RENDER-005** — FPS is canonical job state and part of render identity.
- **FR-RENDER-006** — Initial default FPS is 30.
- **FR-RENDER-013** — 30 and 60 are supported production FPS values. FPS remains part of render identity. Other rates are out of FFmpeg MVP unless an ADR accepts them.
- **FR-RENDER-007** — Renderers expose relevant capability information.
- **FR-RENDER-008** — Unsupported requested capabilities are not silently ignored.
- **FR-RENDER-009** — Custom rendering should support independent base/effect passes where beneficial.
- **FR-RENDER-010** — Base-pass reuse should allow effect recomputation/benchmark sweeps.
- **FR-RENDER-011** — Renderer identity and visual-contract version are part of render identity.
- **FR-RENDER-012** — Every intended visual output has a deterministic render signature.

- **FR-STYLE-001** — Initial style registry: `classic`, `mirrored`, `filled`, `segmented`.
- **FR-STYLE-002** — Styles are registry-based and extensible.
- **FR-STYLE-003** — Style interface can support custom geometry/mapping/rendering.
- **FR-STYLE-004** — Visualization **domain** is part of render identity: `time` (envelope vs time) or `frequency` (fixed frequency axis).
- **FR-STYLE-005** — Time-domain **mode**: `scroll` is the current animated target (sliding envelope window). `playhead` (full-file envelope + cursor) is deferred for later viz and GUI scrubber.
- **FR-STYLE-006** — Frequency-domain **fixed-axis**: X is frequency (low left, high right), Y is band amplitude; silence is flat; motion is vertical only. Frequency span is `auto` (from typical source energy) or a project-fixed min/max so speech energy sits near the center. This domain is a first-class choosable default alongside scrolling envelope, and is the intended particle-collision field for the custom renderer (especially music).

- **FR-EFFECT-001** — Effects are conceptually separate from styles.
- **FR-EFFECT-002** — Glow is an initial effect family.
- **FR-EFFECT-003** — Particle configuration exists in schema even if FFmpeg support is incomplete.
- **FR-EFFECT-004** — Multiple effects should be composable.
- **FR-EFFECT-005** — Particle motion is extensible (e.g. float/fall/rain/rise/radial/reactive).
- **FR-EFFECT-006** — Particle interaction is extensible (`none`, waveform-reactive, amplitude-reactive, frequency-axis collision). Collision with the fixed-axis wave is a custom-renderer target (especially music). FFmpeg does not implement particle interaction.
- **FR-EFFECT-007** — Effects may declare continuity/context requirements.

### Normalization

- **FR-NORM-001** — Visualization normalization never modifies source/publication audio.
- **FR-NORM-002** — Within-project and across-project visual normalization are distinct.
- **FR-NORM-003** — Scaling is resistant to isolated amplitude outliers.
- **FR-NORM-004** — Custom pipeline supports soft clipping or equivalent continuous limiting.
- **FR-NORM-005** — Analysis exposes metrics sufficient for automated comparison/tuning.
- **FR-NORM-006** — Schema can represent `none`, `auto`, `project`, `reference`.
- **FR-NORM-007** — Thresholds/transfer functions are benchmark-derived before becoming stable defaults.

### Output/results

- **FR-OUTPUT-001** — Alpha transparency is mandatory for canonical production assets.
- **FR-OUTPUT-002** — MVP supports ProRes 4444 MOV with alpha.
- **FR-OUTPUT-003** — MVP supports PNG sequence with alpha.
- **FR-OUTPUT-004** — Repeated `--format` requests multiple outputs in one job.
- **FR-OUTPUT-005** — Output format is not part of visual render identity.
- **FR-OUTPUT-006** — Formats for one render identity are visually equivalent within codec-appropriate tolerance.
- **FR-OUTPUT-007** — Incomplete outputs are never exposed as completed assets.
- **FR-OUTPUT-008** — Publication occurs only after output and result validation.
- **FR-OUTPUT-009** — Default output root is `<source-directory>/waveform-output/`.
- **FR-OUTPUT-010** — Project groups use output subdirectories.
- **FR-OUTPUT-011** — Output names include source/preset identity and short render signature.
- **FR-OUTPUT-012** — Matching completed equivalent jobs are skipped.
- **FR-OUTPUT-013** — Forced rendering versions outputs as `_v002`, `_v003`, etc.

- **FR-RESULT-001** — Every successful job publishes schema-valid `*_results.json`.
- **FR-RESULT-002** — Full source SHA-256 is stored.
- **FR-RESULT-003** — Results record render identity, config, seed, analysis, execution, warnings, validation, outputs, performance, and resume history.
- **FR-RESULT-004** — Application/schema versions are independently versioned.
- **FR-RESULT-005** — Multi-job runs should create a run-level summary.
- **FR-RESULT-006** — Runtime timestamps do not affect visual identity.

### Chunking/recovery

- **FR-RESUME-001** — Rendering supports chunked processing.
- **FR-RESUME-002** — Initial default chunk duration is 60 seconds and benchmark-tunable.
- **FR-RESUME-003** — Chunk size is a performance setting, not intended appearance.
- **FR-RESUME-004** — Chunk assembly duplicates/omits no canonical frames.
- **FR-RESUME-005** — Chunk boundaries introduce no visible/timing discontinuity.
- **FR-RESUME-006** — Interrupted jobs can resume from validated checkpoints where possible.
- **FR-RESUME-007** — Resume validates source hashes, render signature, checkpoint schema, chunk integrity, and renderer compatibility.
- **FR-RESUME-008** — Resumed jobs emit `W_JOB_RESUMED` with source-timeline boundary.
- **FR-RESUME-009** — Graceful cancellation preserves recoverable state where practical.
- **FR-RESUME-010** — Successful-job workdirs are removed after final validation/publication by default.
- **FR-RESUME-011** — Failed/interrupted workdirs are retained for recovery by default.
- **FR-RESUME-012** — Persistent work roots are opt-in.
- **FR-RESUME-013** — Stateful, overlap, and hybrid strategies are documented/benchmarked.
- **FR-RESUME-014** — Absolute-time deterministic evaluation is investigated where useful.
- **FR-RESUME-015** — Continuity mechanisms may differ by render/effect pass.

### Preview/config/benchmark

- **FR-PREVIEW-001** — Preview uses the real production render path.
- **FR-PREVIEW-002** — Preview supports single files and grouped projects.
- **FR-PREVIEW-003** — Group previews use a shared source-time interval.
- **FR-PREVIEW-004** — Optional templates can compose one/two/three preview assets.
- **FR-PREVIEW-005** — Preview composition does not affect canonical waveform identity.

- **FR-CONFIG-001** — Human-editable configuration uses TOML.
- **FR-CONFIG-002** — Application config, visual preset, performance profile, preview template, benchmark manifest are separate.
- **FR-CONFIG-003** — No preset inheritance in MVP.
- **FR-CONFIG-004** — Built-in presets are immutable.
- **FR-CONFIG-005** — Preset lookup: explicit path > project > user > built-in.
- **FR-CONFIG-006** — Source-qualified preset references should be supported.
- **FR-CONFIG-007** — Presets are validated.
- **FR-CONFIG-008** — Presets support import/export.
- **FR-CONFIG-009** — Backup export should be self-contained/resolved.
- **FR-CONFIG-010** — Reset removes override and reveals built-in.
- **FR-CONFIG-011** — Preset writes are atomic and do not silently overwrite.
- **FR-CONFIG-012** — Performance config is recorded but not visual identity.
- **FR-CONFIG-013** — Fully resolved configuration can be shown before rendering.

- **FR-BENCH-001** — Performance and visual benchmarks are separate families.
- **FR-BENCH-002** — Benchmark manifests support multiple inputs/renderers/variants/formats/performance settings.
- **FR-BENCH-003** — Requested benchmark matrix expands automatically.
- **FR-BENCH-004** — Benchmark dry-run reports job/output count.
- **FR-BENCH-005** — Dry-run should estimate disk/time when evidence exists.
- **FR-BENCH-006** — Estimates are labelled and omitted when evidence is insufficient.
- **FR-BENCH-007** — Performance benchmarks record resource/time/output/drift metrics.
- **FR-BENCH-008** — Future GPU benchmarks record VRAM/GPU utilization.
- **FR-BENCH-009** — Visual benchmarks support style/effect/normalization sweeps.
- **FR-BENCH-010** — Benchmarks never silently mutate canonical presets.
- **FR-BENCH-011** — Saving a tested variant as a preset is explicit.
- **FR-BENCH-012** — Dedicated chunk-boundary benchmark uses aggressive chunk sizes.
- **FR-BENCH-013** — Dedicated resume benchmark compares uninterrupted vs resumed output.
- **FR-BENCH-014** — Continuity-strategy benchmark compares stateful/overlap/hybrid where supported.
- **FR-BENCH-015** — Long-duration endurance target is approximately three hours.

## Non-functional requirements

- **NFR-DET-001** — Rendering is deterministic by default for stable source/config/renderer-contract/seed/FPS.
- **NFR-DET-002** — Chunk/workers/threads/output format/performance profile do not intentionally alter appearance.
- **NFR-DET-003** — Randomized effects use deterministic seed by default.
- **NFR-DET-004** — Unavoidable deviations use explicit measurable tolerances.

- **NFR-MAINT-001** — Modular monolith with explicit boundaries.
- **NFR-MAINT-002** — Thin CLI over stable application API.
- **NFR-MAINT-003** — Registries over unbounded hard-coded branching.
- **NFR-MAINT-004** — Plugin-ready architecture; no external plugin loading in MVP.
- **NFR-MAINT-005** — Typed public/non-trivial internal functions.
- **NFR-MAINT-006** — Repository documentation is English.
- **NFR-MAINT-007** — Small coherent traceable commits.

- **NFR-PERF-001** — Long inputs avoid unnecessary whole-file decoded-memory scaling.
- **NFR-PERF-002** — Parallelism is configurable.
- **NFR-PERF-003** — Performance defaults derive from benchmark evidence.
- **NFR-PERF-004** — Processing model supports typical 20–80 minute files and ~3 h endurance input.

- **NFR-PORT-001** — Reference: Ubuntu 24.04 WSL2 and bare metal.
- **NFR-PORT-002** — Core does not depend on WSL-specific APIs.
- **NFR-PORT-003** — Future containerized Windows/macOS use remains possible.

- **NFR-TEST-001** — Schemas/render/determinism/chunk/resume/output validation receive automated coverage.
- **NFR-TEST-002** — FFmpeg/filesystem/process orchestration receive integration tests.
- **NFR-TEST-003** — Visual equivalence may use tolerances rather than byte equality.
- **NFR-TEST-004** — Source immutability is tested.
