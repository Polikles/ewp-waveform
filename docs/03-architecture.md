# 03 — Architecture

## Style

Modular monolith with a stable application-facing API.

```text
CLI / future GUI / automation
            |
            v
      application service
            |
            v
      domain/job models
            |
       orchestration
   /      |      |       \
input  analysis render  storage
                 |
          renderer protocol
          /             \
      FFmpeg           Custom
                         |
                 multi-pass graph
```

## Boundaries

- **CLI:** parse intent/present results only.
- **Application API:** shared interface for CLI, GUI, tests, automation.
- **Domain:** renderer/UI-independent typed models.
- **Discovery:** files, grouping, hashes, timeline checks.
- **Analysis:** loudness/envelope/normalization decisions.
- **Renderer:** backend execution behind protocol.
- **Registries:** renderer/style/effect/encoder extensibility.
- **Workdirs:** temporary/checkpoint lifecycle.
- **Storage/results:** validation and atomic publication.

## Multi-pass custom target

```text
analysis
 -> base waveform pass
 -> glow pass
 -> particle pass
 -> other passes
 -> compositor
 -> canonical RGBA
 -> encoders
```

Pass separation supports effect recomputation, caching/reuse, per-pass continuity strategy, and focused benchmarks.

## Performance invariance

Chunk size, worker count, FFmpeg threads, and future device choice describe how equivalent work is computed. They do not intentionally define appearance.

Wall time and real-time factor are product metrics (`NFR-PERF-005`). The FFmpeg MVP may leave CPU unused; the custom renderer must be built to use available cores and later GPU (`NFR-PERF-006`, ADR-0011).

## Plugin readiness

Use internal protocols/registries in MVP. Public plugin discovery/loading is deferred until compatibility, packaging, versioning, and security contracts stabilize.
