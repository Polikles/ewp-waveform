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


## Internal render lifecycle boundary (REF-002)

`application.render_lifecycle` owns destination selection and reuse validation,
workdir policy selection, final media validation/publication, terminal cleanup and
job-result assembly. `DestinationSelection` and `WorkdirPolicy` carry those
internal decisions; `RenderLifecycle` holds only per-invocation lifecycle state.
The dispatcher still resolves options/appearance, hashes the input initially,
selects the clip and runs the existing scroll/fixed-axis pipelines. Its original
pre-try and try/except/else boundaries remain in place. No pipeline, worker task,
chunk/checkpoint algorithm or analysis cache is extracted here.

Existing helpers remain importable with the same signatures in
`application.render`, forwarding to lifecycle implementations. A typed structural
`LifecycleHooks` view of the live dispatcher module preserves late helper lookups
(including destination planning, probing, hashing, result assembly and clock
helpers), rather than capturing callbacks at import or lifecycle construction.
The shared `shutil` module remains the move/removal patch seam. Workdir key/path
resolution still uses `application.checkpoint`; result elapsed time still uses
`application.results`. There is no duplicate checkpoint or result schema.

The selected-base ordering is deliberately retained: project directory creation
and SKIP validation precede work/clock allocation; all-reused jobs hash only once;
processing jobs perform the existing second source check before rendering, not a
new post-render hash. Partial reuse retains reused outputs first. Each produced
MOV is validated and directly moved before PNG validation; existing PNG removal
still precedes its move. A later failure can therefore leave an already-published
MOV, and a failed PNG move can leave its prior destination removed. This is not
atomic multi-output publication, rollback or stronger validation. The architecture
and recovery documents' atomic-publication sequence describes the intended target,
not a guarantee newly provided by this extraction.

Failure classification, warnings, validation-report precedence and retained-work
existence checks are unchanged. Success cleanup still reports no workdir after
an ignored removal, even if removal did not succeed. Interrupts/unhandled errors
retain the original catch behavior. Public render/service signatures/defaults,
result payload/identity, visual-contract version, output ordering, force versioning
and exact existing equivalence oracles remain unchanged. Behavioral fixes require
separate increments; no performance or operator visual-acceptance claim is made.


## Internal time-scroll pipeline boundary (REF-003)

`application.render_scroll` owns scroll settings, overlapped envelope preparation,
scroll frame iteration, chunk task payloads, checkpoint coordination, encode
scheduling and ordered concat. `render` retains explicit compatibility forwards
and re-exports the same payload classes. A typed `ScrollHooks` view of the live
dispatcher preserves helper/encoder/worker/test monkeypatch lookups, including
changes made during callbacks or frame iteration, without importing the dispatcher
back from the pipeline. The existing `render.encode_scroll_chunk` forward stays
the spawn-pool target; only the existing pickleable task travels to workers.

The pipeline updates caller-owned analysis/normalization reports at the original
assignment boundaries so caught failures retain the same partial reports. It
returns staged MOV/PNG paths; final validation and MOV-before-PNG publication,
source checks, cleanup and result assembly remain lifecycle responsibilities.
Fixed-axis code and shared worker/thread/progress utilities stay in the dispatcher.
There is no new renderer registry, cache, checkpoint schema or result model.

The selected-base envelope math, bin origins, published-region global peak,
canonical partitioning and preroll/postroll, 12x scroll raster, style/opacity,
glow/shutter, thread pinning, PNG numbering, failure injection, stale rejection,
completion-order checkpoint writes and clip-relative resume-boundary reporting
are unchanged. Public signatures/defaults, identity/visual-contract version and
exact oracles remain unchanged. This extraction neither corrects existing failure
windows nor claims performance, operator visual/NLE or aggregate acceptance.


## Internal fixed-axis pipeline boundary (REF-004)

`application.render_fixed` owns the pre-reuse fixed-axis appearance-option adapter,
legacy spectrum and centered temporal frame iteration, field peak/staging, analysis
cache orchestration, the field task payload, thresholded parallel encoding and
ordered concat. The existing appearance resolver, analysis/cache implementation,
raster/plan implementations and FFmpeg adapters are unchanged. The dispatcher
retains shared preset color/glow/opacity overrides, clipping, source checks, timing
allocation and the original catch boundary; lifecycle and scroll implementations
are unchanged. No REF-005 registry or new renderer architecture is introduced.

A typed `FixedHooks` view of the live dispatcher preserves helper, constant,
constructor, module, encoder and test monkeypatch lookups, including replacements
between yielded frames or in progress callbacks. Explicit compatibility forwards
retain the original helper signatures/defaults in `render`; `FieldChunkTask` and
the 1,800-frame threshold are re-exported there. The existing
`render.encode_field_chunk` remains the spawn target. Only the unchanged frozen
scalar task payload enters the pool, never a hook view or lifecycle object. The
new payload definition is importable through both module paths, including the
legacy path used to unpickle an older task.

The fixed pipeline calls the existing lifecycle publication methods through a
small structural view, rather than implementing validation or publication itself.
This keeps MOV-before-PNG publication and the selected-base partial-report failure
windows: temporal analysis is assigned before encode, spectrum analysis only after
publication, and normalization only after publication. Caller-owned initially
empty reports are updated at those exact original assignment boundaries. A failed
PNG publication can still leave a MOV published; this extraction is not rollback
or atomic multi-output publication.

All selected-base analysis calls/data, frequency-span and normalization rules,
cache keys/values/hit/corrupt behavior, physical supersampling/coverage taps,
mask/RGBA selection and forced-path fallback, field geometry/bar/color/glow
controls, pool threshold, canonical field rows, range ordering and PNG numbering
remain unchanged. Public render/service interfaces, identity, visual-contract
version, result and checkpoint schemas remain unchanged. Structural AST checks
are not runtime, visual, performance or operator acceptance.


## Internal built-in pipeline selection (REF-005)

`application.render_pipelines.RenderPipeline` defines only two phases already
present in the dispatcher: `prepare` resolves the fixed-axis recipe before
identity/reuse, and `run` forwards execution inside the existing error boundary.
The immutable `BUILTIN_PIPELINES` mapping contains frozen, stateless adapters for
`frequency` (fixed-axis) and `time` (scroll). It is not a public backend registry,
capability validator, discovery mechanism or runtime registration API. Selection
retains the exact `frequency`/else rule at both original decision points, including
non-frequency fallback for direct internal calls. The service still rejects
particles and playhead with its existing diagnostics before calling render.

`PipelineRun` is a shallowly frozen per-call transport, not a validator or worker
payload. It carries the REF-001 effective context references, resolved common
execution values, entry-time raw contour/failure aliases, and the same mutable
report/clock/lifecycle objects. `RenderOptions` is passed unchanged to preparation;
no option is copied, coerced, defaulted or normalized by the registry. Scroll
preparation does nothing. The fixed adapter forwards to `resolve_fixed_options`;
its execution forwards to `run_fixed_pipeline`. The scroll adapter forwards to
`run_scroll_pipeline`, then calls lifecycle MOV-before-PNG publication at the same
boundary as before. Neither adapter implements analysis, raster, cache, checkpoint,
FFmpeg options, output validation, cleanup or result assembly.

`render.py` retains common preset overrides, source/clip/work/clock orchestration,
compatibility exports/forwards and the unchanged try/except/else boundary. Typed
`PipelineHooks` accesses the live module's original `_fixed_hooks`/`_scroll_hooks`
functions at each original call site. Adapters retain module attribute lookups,
not captured implementation callbacks. No pipeline imports `render` back. All
helper/worker monkeypatch seams, legacy task import paths, spawn targets and the
1,800-frame field-pool threshold remain unchanged. The complete 39-binding raw
entry prefix and deliberate deletion of 21 now-unused fixed aliases remain intact.

The two implemented adapters demonstrate the extension seam: a separately approved
internal path can implement the same two methods and be selected by a reviewed
static built-in table/selection change, while reusing common lifecycle and the
unchanged public service interface. It need not duplicate source checks, identity,
reuse, workdir handling, terminal results or publication implementation. Preparation
and execution remain separate to avoid moving pre-reuse work into the render try
block. Adding capability or identity behavior requires its own explicit review;
this increment adds no future renderer, generic plugin machinery or public loader.
Existing style/effect/encoder registries, unsupported paths, schemas, visual
contract, identity/cache formats and exact oracles are unchanged. No runtime,
performance, visual/NLE or operator-acceptance claim follows from static checks.
