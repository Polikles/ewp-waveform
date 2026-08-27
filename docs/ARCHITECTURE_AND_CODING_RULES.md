# Architecture and Coding Rules

Condensed reference:

1. Modular monolith.
2. CLI/future GUI are adapters over one application API.
3. Domain models are UI/backend independent.
4. FFmpeg details stay in FFmpeg adapter.
5. Inputs are immutable.
6. Intermediate data stays in workdirs.
7. Publish only validated media + schema-valid results.
8. Separate visual preset/performance/application/preview/benchmark config.
9. Use registries for renderer/style/effect/encoder extension.
10. Plugin-ready, no arbitrary plugin loading in MVP.
11. Performance settings do not intentionally change appearance.
12. Preserve timing/effect continuity across chunks/resume.
13. Use typed models and `pathlib.Path`.
14. Never `shell=True` for FFmpeg/ffprobe.
15. Avoid hidden network access.
16. Use small coherent Conventional Commits.
17. Reference requirements/ADRs when relevant.
18. Update changelog for public contract changes.
19. Do not vendor external binaries or commit private/generated media.
