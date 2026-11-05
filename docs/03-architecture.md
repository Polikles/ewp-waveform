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


## Internal render execution boundary (REF-001, first increment)

`application.render.render_job` retains its explicit legacy signature and returns
its original result dictionary. An explicit `_render_options_from_legacy` adapter
carries all 35 raw keyword values into `RenderOptions`; `_render_job(context,
options)` in the same module consumes those fields and returns `RendererOutcome`
containing the same dictionary. These internal dataclasses are shallowly frozen,
not validators: they preserve references, `None`, `False`, zero and legacy values.
Defaults and effective appearance are still resolved at the original use sites.

`RenderContext` carries the existing job, media, visual preset and performance
profile references. It deliberately does not resolve work paths or destinations;
work policy, lifecycle, clipping, timing, recovery, validation and publication
remain owned by the existing orchestration. The domain has no reverse dependency
on these application types. There is no new renderer protocol, registry or pass
pipeline in this increment.

Service and benchmark continue calling their imported `render_job` symbols, so
those patch seams and helper/worker lookups in `application.render` stay intact.
Typed context/options, callbacks and phase collectors are not new spawn-pool
payloads; existing worker tasks remain unchanged. Product version, visual contract,
identity, output/result schemas and exact equivalence oracles are unchanged. This
boundary makes no performance or visual-acceptance claim.
