# ADR-0004 — Deterministic render identity

- **Status:** Accepted
- **Date:** 2026-08-26

## Context
Batch reruns need reliable SKIP while alternative presets/settings and multiple encoders coexist.

## Decision
Compute deterministic render signature from stable inputs defining intended visual output.

Include source identity, clip start/duration (full file is `clip_duration=null`), normalization context, resolved visual config, seed, FPS, renderer identity, and visual-contract/algorithm versions. A preview interval is a different identity from a full-file render.

Exclude output format/path, chunk size, workers, threads, performance profile, and wall-clock timestamp.

## Consequences
Equivalent completed jobs can be skipped and multiple encoders can share one visual identity.


## Fixed-axis recipe identity correction (EWP-IDENTITY-FIX-001)

The application resolves existing fixed-axis controls before signature/destination
selection and SKIP. A version-1 `fixed_axis_recipe` identifies the effective
geometry, band mapping, contour/layout, active spatial smoothing, tilt/compression,
recenter/taper/slot smoothing, supersampling, field geometry, bar spacing/colors/
center stroke, and resolved sampling/AA where applicable. Existing fallback and
pack defaults are reused by execution. Inactive controls canonicalize away;
field omitted bands and explicit 64 bands are equivalent. Preset color/glow and
signal settings remain in the existing preset identity.

Physical-AA MASK_FAST/RGBA_2D are representation choices, not separate visual
identities. A requested path that changes resolved AA can change identity.
Coverage taps are identified for ribbon; bars/segmented currently consume only
the resolved supersample, not tap count. This correction does not implement new
raster behavior. Jobs, threads, chunk/cache/workdir choices, output format/path
and timings remain excluded.

All application frequency identities, including defaults and the existing
experimental temporal routes, deliberately migrate to the recipe-bearing payload.
Old frequency filenames cannot be trusted: an old nondefault look may already
occupy the old default signature. They are not reused under the new identity;
old files are not deleted or renamed. Time-scroll signatures and visual raster
contract version 13 remain unchanged. No frozen raster baseline is regenerated.

`render_signature` is a low-level payload hash: a caller supplying effective
fixed-axis controls must pass their resolved recipe. `planned_destinations`
automatically resolves the default frequency recipe; `render_job` supplies the
actual resolved recipe. The same recipe is stored for success, failure and SKIP
in `resolved_visual_config.fixed_axis_recipe`. Analysis-cache inputs and raster
algorithms remain unchanged. This is an identity migration, not a raster-version
change or a general canonicalization/validation redesign of preset dictionaries.
