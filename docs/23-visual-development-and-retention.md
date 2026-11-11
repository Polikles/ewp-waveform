# 23 — Visual development, acceptance assets and retention

Operator clarification accepted 2026-11-04. This is the authoritative public
clarification of visual-development and comparison/retention requirements. It
supplements 02/10/12/13, not a claim that new styles, optimization or full acceptance
renders have been implemented or reviewed. Private project operations select
actual input/output locations and execution authority; no private paths belong here.

## Explicit experiment-quality amendment — 2026-11-11

For opt-in experiments, visually close rather than byte-identical output is
permitted, subject to operator assessment and mandatory structural correctness.
[Document24](24-experiments.md) distinguishes exact optimization promises from
intentional approximation, bounded screening from completed style optimization,
and technical validity from appearance/NLE acceptance. Default-path exact tests
remain unchanged. Existing full acceptance requirements and every retention hold
remain in force; short experimental clips are not full-style deliverables.

## Independent inputs and visual choices

One supplied audio track produces one independent visualization asset, even when
that track contains several speakers. Diarization, speaker separation and
multi-speaker composition are not requirements. One/two/three-speaker boards are
downstream composition references, not an instruction to assemble a final scene.

Distinguish presentation mode (moving time/envelope scroll, or the existing
fixed-axis frequency visualization) from graphical variant (classic line, mirrored
line, filled ribbon, segmented impulse), graphical theme and waveform color. The
reference themes include five selectable waveform colors. Broad acceptance of
scroll and fixed-axis frequency looks does not establish acceptance of a whole-file
static time envelope or full reference fidelity of every variant. Existing limited,
experimental and unsupported capability labels remain applicable.

Yellow is unresolved: the reference swatch is `#F2C55B`; existing presets use
`#F2C558`. Neither is made canonical here and no preset changes are authorized.
Historical notes treating these as one token do not resolve the discrepancy.

Every rendered visualization must have a transparent background for DaVinci
Resolve. Record content-level alpha verification separately from alpha-capable
codec/pixel-format metadata and from later operator/NLE import, playback and
compositing review. None of those three alone proves the other two.

## Baseline, optimize, refine

For each added graphical style establish a baseline reasonably faithful to the
reference, then optimize rendering time while keeping appearance reasonably close
to that baseline. Further visual refinement may follow optimization. Existing
accepted looks may also change during optimization; cross-version pixel identity
is not a universal acceptance rule.

Keep technical correctness, declared-contract determinism, timing, continuity,
chunk/worker/resume equivalence, source immutability, recovery and identity/reuse
checks. Structural refactors, telemetry and execution-only performance settings
still preserve the selected visual contract. Intentional appearance changes are
visual algorithm/configuration changes, not hidden changes to execution settings.
Explain visual differences and any necessary oracle, signature or contract-version
amendments explicitly, preserving old evidence and review rationale. Never rewrite
expected results to disguise an unintended regression. Exact same-contract tests
remain exact; MOV container byte equality is not a visual oracle.

## Complete acceptance assets versus short diagnostics

Before appearance-changing optimization identify and preserve the applicable
baseline. At optimization completion provide a complete s0e00 render for each
added or optimized graphical style. The provisional representative acceptance
workload is the full `s0e00-Damian.wav` track (395.6785 seconds), consistent with
the retained reference's original input. Other supplied tracks remain additional
coverage. This does not require a full Cartesian product of every style, color,
track and episode.

The retained eight-second MVP reference remains useful scoped evidence, but is
not a complete-s0e00 deliverable and need not be replaced for routine edits. Short
profiling samples/cold-warm repeats remain useful; full acceptance assets are not
required for every experimental candidate. Future full renders require their own
capacity/time admission and execution authorization. No media is generated here.

The operator must be able to compare baseline and optimized assets independently
of all agent comparisons and reviews. Keep separately identified originals
available, not merely an agent verdict or a combined comparison image.

## Retention and artifact records

A baseline must remain on the VM unless the operator confirms downloading a copy
of that exact identified baseline. Visual acceptance alone does not release it
for deletion. Record actual download confirmation with artifact identity,
location/checksum, date and operator provenance; absent confirmation stays
not_confirmed/unknown. Never infer it. Confirmation satisfies this hold but is
not a cleanup command or an override of other holds.

The optimized render remains available through operator comparison and the
applicable cleanup decision. Renderer intermediates need not be archived
indefinitely; preserve required recovery state until authorized cleanup. Archived
source/edited audio and final assembled visualizations have separate purposes and
retention policies; do not apply intermediate-output disposal rules to them.

Audio, reference PNGs, generated media and other large binary outputs remain
outside Git. Track compact text manifests/references, not media. Records identify
source revision, input identity, style and resolved settings, dimensions/FPS,
output location/checksum/size, measured performance with timer/resource scope,
agent verification and operator review status. Separate agent PASS from operator
visual acceptance, content alpha evidence from metadata/NLE review, and download
confirmation from acceptance. Unknown values stay unknown. Existing result and
manual-test conventions suffice; no new schema/platform/retention service is
introduced by this documentation amendment.
