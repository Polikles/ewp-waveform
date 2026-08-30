# Changelog

The project follows Semantic Versioning. Development is currently an internal beta / pre-MVP; there is no public release.

## Unreleased

### Added

- Fixed-axis spectrum (`iuris-spectrum`) uses an application log-Hz span: `auto` from source energy or explicit `fmin_hz`/`fmax_hz`, drawn with mirrored bars. Scroll signatures are unchanged.
- Scroll jobs resume from validated workdir checkpoints: reuse completed chunks, reject stale signatures, emit `W_JOB_RESUMED`.
- Envelope jobs split into 60 s logical chunks with window+FIR preroll and FFmpeg copy-concat of published segments (ADR-0006).
- Equivalent-job SKIP: complete dests with a matching signature are skipped, listed in `outputs`, and re-validated; empty leftovers are rerendered.
- Published MOV/PNG are probed for codec, alpha, size, and frame count before publish.
- First identifiable CLI: `waveform doctor|inspect|capabilities|dry-run|preview|render`.
- Frozen exit codes 0/2/3/4/5/6.
- Scrolling RMS envelope renderer (5 s window, mirrored bars, glow) and experimental `showfreqs` spectrum path.
- Scroll path is translation-only of a frozen envelope (no vertical bounce). Auto-gain so speech fills the canvas.
- Operator-adopted scroll default is `iuris-default` as rendered in `*ad0c99b500c0.mov`: 60 fps, dense RMS (oversample 4), temporal-Nyquist sinc LOD (~0.09 cyc/px), shutter 0, 12× raster, medium glow.
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
