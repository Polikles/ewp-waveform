# ADR-0003 — Configuration-domain separation

- **Status:** Accepted
- **Date:** 2026-08-26

## Decision
Keep separate:
- Application Config
- Visual Preset
- Performance Profile
- Preview Template
- Benchmark Manifest

Use TOML for human-editable configuration. No visual-preset inheritance in MVP.

## Rationale
Appearance, execution, preview, and experiments have different identity/lifecycle semantics.
