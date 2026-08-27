# ADR-0009 — Prefix-based project grouping as MVP default

- **Status:** Accepted
- **Date:** 2026-08-26

## Decision
Default grouping uses `<project>-<track>.<ext>` split at the first configurable `-`. Unmatched single files remain valid.

## Rationale
Matches the current podcast naming convention without hard-coding it permanently.

## Consequences
Regex/directory/manifest grouping remains extensible/deferred.
