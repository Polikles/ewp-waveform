# AGENTS.md

This file defines implementation rules for coding agents working on **ewp-waveform**.

## 1. Goal

`ewp-waveform` generates deterministic transparent waveform assets for later composition. Files under `docs/`, `schemas/`, `examples/`, `presets/`, and `performance/` are the contract source of truth.

## 2. Scope discipline

Permanent non-goals:

- audio editing/mastering;
- denoising/repair;
- transcription/subtitles/translation;
- diarization/source separation;
- final podcast-video composition;
- publishing/upload.

Deferred features include GUI, public plugin loading, GPU rendering, Docker deployment, Apple Silicon validation, project manifests, and extra output formats.

Do not introduce speculative infrastructure.

## 3. Architectural rule

The project is a modular monolith.

```text
CLI or future GUI
        |
        v
application API
        |
        v
domain/job models + orchestration
        |
        +--> discovery/input
        +--> analysis/normalization
        +--> renderers
        +--> style/effect registries
        +--> workdirs/recovery
        +--> storage/results
```

Mandatory boundaries:

1. CLI is an adapter and contains no rendering/grouping/hash/storage/FFmpeg logic.
2. The application API is shared by CLI, future GUI, tests, and automation.
3. Domain models do not import Typer or renderer-specific libraries.
4. FFmpeg command/filter construction lives only in the FFmpeg adapter.
5. Use `subprocess` argument lists; never `shell=True`.
6. Source files are immutable.
7. Intermediate artifacts belong in workdirs, never final output directories.
8. Publish only validated outputs plus schema-valid results.
9. Keep renderer/style/effect/encoder registries extensible.
10. MVP is plugin-ready but does not execute arbitrary external plugin code.
11. Visual presets, performance profiles, application config, preview templates, and benchmark manifests are separate.
12. Performance settings must not intentionally alter appearance.
13. Chunk partitioning and resume must preserve canonical continuity.

## 4. Coding standards

- Python `>=3.12,<3.13`.
- `src/` layout.
- Type annotations for public and non-trivial internal functions.
- Prefer typed models over unstructured dictionaries.
- Use `pathlib.Path`.
- Avoid global mutable state and hidden network access.
- Keep expensive/optional imports lazy where practical.
- Do not vendor FFmpeg, codecs, GPU runtimes, fonts, or media binaries.
- Do not commit private/generated media, caches, workdirs, or benchmark bundles.

## 5. Change strategy

Work in vertical slices. Before implementation:

1. read requirements, architecture, relevant ADRs and schemas;
2. identify acceptance criteria and requirement IDs;
3. add/update tests first when practical;
4. implement the smallest coherent complete change;
5. run the relevant quality gate;
6. update documentation and changelog when public contracts change.

Do not create empty speculative modules.

## 6. Commits

Use Conventional Commits:

- `feat`
- `fix`
- `docs`
- `test`
- `refactor`
- `chore`

Examples:

```text
feat(render): add deterministic render signatures
fix(resume): reject stale chunk checkpoints
docs(adr): define chunk continuity contract
```

Keep commits small, coherent, auditable, and traceable. Do not split mechanically by file.

Where applicable include:

```text
Refs: FR-RENDER-012
ADR: ADR-0004
```

If a change implements or depends materially on an ADR, identify it in the title and/or body. Update `CHANGELOG.md` for user-visible or architectural-contract changes.

## 7. Testing

Follow `docs/TESTING_STRATEGY.md` and `docs/12-testing-and-acceptance.md`.

FFmpeg/filesystem/output/chunk/resume/process-orchestration changes require integration coverage.

## 8. Definition of done

A change is done only when documented behavior, tests, static checks, data hygiene, source immutability, schema compatibility, and scope discipline are satisfied.
