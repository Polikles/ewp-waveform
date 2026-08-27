# Changelog

The project follows Semantic Versioning. Development is currently an internal beta / pre-MVP; there is no public release.

## Unreleased

### Added

- Initial specification baseline.
- Core documentation and ADR set.
- Draft schemas and TOML examples, including an application config schema.
- Repository governance and traceability rules.
- EWP Waveform Community License 1.0, licensing overview, contributor terms, and notices.
- FFmpeg spike note convention under `docs/notes/ffmpeg-spike/`, including an environment and `lavfi` smoke-test record.
- FFmpeg spike synthetic CPU findings: style/glow capability ratings, chunk warm-up seam, 30 s resource sample.
- Speech-cut spike follow-up; 30 and 60 documented as supported production FPS (`FR-RENDER-013`).

### Changed

- Merged engineering workflow and legal contribution rules into `CONTRIBUTING.md`.
- Status documents now treat the license as adopted and describe internal betas rather than a release candidate.
- `FR-CLI-005` includes `capabilities`; `FR-CLI-009` covers `preset`, `performance`, `benchmark`, and `clean`.

### Fixed

- None.
