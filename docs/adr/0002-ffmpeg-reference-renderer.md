# ADR-0002 — FFmpeg as reference renderer and permanent alternate backend

- **Status:** Accepted
- **Date:** 2026-08-26

## Decision
FFmpeg is the MVP/reference renderer behind a renderer abstraction. A later custom renderer reuses the same public job/config/result model. FFmpeg remains selectable afterward.

## Rationale
FFmpeg provides a fast evidence-based baseline without defining product UX/config syntax.

## Consequences
Some high-level styles/effects may be limited in FFmpeg; capability limitations must be explicit.
