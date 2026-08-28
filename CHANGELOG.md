# Changelog

The project follows Semantic Versioning. Development is currently an internal beta / pre-MVP; there is no public release.

## Unreleased

### Added

- First identifiable CLI: `waveform doctor|inspect|capabilities|dry-run|preview|render`.
- Frozen exit codes 0/2/3/4/5/6.
- Scrolling RMS envelope renderer (5 s window, mirrored bars, glow) and experimental `showfreqs` spectrum path.
- Scroll path is translation-only of a frozen envelope (no vertical bounce). Auto-gain so speech fills the canvas.
- Default production FPS is **60**. Time+scroll uses a denser real RMS hop (`envelope_oversample`, default 4) plus an output-pixel reconstruction filter (`envelope_aa`, default `area` @ 1 px) so sub-pixel spikes do not strobe. `signal.smoothing` stays 0. 30 fps remains supported but is not expected to match 60 fps at this scroll speed.
- Initial specification baseline.
- Core documentation and ADR set.
- Draft schemas and TOML examples, including an application config schema.
- Repository governance and traceability rules.
- EWP Waveform Community License 1.0, licensing overview, contributor terms, and notices.
- FFmpeg spike note convention under `docs/notes/ffmpeg-spike/`, including an environment and `lavfi` smoke-test record.
- FFmpeg spike synthetic CPU findings: style/glow capability ratings, chunk warm-up seam, 30 s resource sample.
- Speech-cut spike follow-up; 30 and 60 documented as supported production FPS (`FR-RENDER-013`).
- FFmpeg spike analysis of Iuris et Logos reference boards (style names, speaker colors, 1/2/3-speaker layouts).

### Changed

- Merged engineering workflow and legal contribution rules into `CONTRIBUTING.md`.
- Status documents now treat the license as adopted and describe internal betas rather than a release candidate.
- `FR-CLI-005` includes `capabilities`; `FR-CLI-009` covers `preset`, `performance`, `benchmark`, and `clean`.
- Default look is **mirrored** vertical bars + medium glow @ 30 fps per the brand boards. `lowpass=80` rejected. `iuris-default` style is `mirrored`. FFmpeg cannot draw that geometry faithfully yet.
- Visualization domain: time+scroll (current podcast target), time+playhead (later), frequency fixed-axis (second choosable default, `iuris-spectrum`). `FR-STYLE-004`–`006`.

### Fixed

- None.
