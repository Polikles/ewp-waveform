# Documentation Index

## Normative precedence

If documents conflict, use this order:

1. Accepted ADRs with a later acceptance date.
2. `02-requirements.md`.
3. Detailed numbered specifications in `docs/`.
4. JSON Schemas under `schemas/`.
5. Examples under `examples/`.
6. Roadmap/TODO material.

Contradictions must be resolved explicitly.

Current operator clarification: [23 — Visual development, acceptance assets and
retention](23-visual-development-and-retention.md), accepted 2026-11-04. It clarifies
02/10/12/13 for this scope; same-contract equivalence and configuration-domain
separation remain in force. Historical spike notes are evidence, not current
appearance acceptance or retention authority.

## Documents

1. `01-product-scope.md` — product purpose and boundaries.
2. `02-requirements.md` — functional/non-functional requirements.
3. `03-architecture.md` — modular-monolith architecture.
4. `04-input-discovery-and-grouping.md` — discovery/grouping/timeline rules.
5. `05-cli-specification.md` — public CLI contract.
6. `06-configuration.md` — config/presets/performance/templates/benchmarks.
7. `07-results-data-model.md` — canonical result model.
8. `08-output-formats.md` — alpha/output/fidelity contract.
9. `09-state-errors-and-logging.md` — states, diagnostics, logging.
10. `10-rendering-and-effects.md` — styles/effects/passes/capabilities.
11. `11-normalization.md` — visualization normalization.
12. `12-testing-and-acceptance.md` — acceptance gates.
13. `13-benchmarking.md` — performance and visual benchmarks.
14. `14-dependency-baseline.md` — initial tooling baseline.
15. `15-glossary.md` — canonical terminology.
16. `16-risk-register.md` — known project risks.
17. `17-definition-of-done-mvp.md` — FFmpeg MVP DoD.
18. `18-recovery-and-workdirs.md` — workdirs/checkpoints/recovery.
19. `19-preview-system.md` — preview assets/compositions.
20. `20-mvp-requirements-traceability.md` — requirements map.
21. `21-ffmpeg-baseline-plan.md` — FFmpeg research spike.
22. `22-chunking-and-continuity.md` — continuity contract/strategies.
23. `23-visual-development-and-retention.md` — visual evolution, complete acceptance assets, alpha verification and retention.
24. `24-experiments.md` — opt-in exact/approximation experiments, frozen factors, bounded recovery and target recipes.
99. `99-roadmap.md` — deferred work.

Additional:

- `ARCHITECTURE_AND_CODING_RULES.md`
- `TESTING_STRATEGY.md`
- `adr/`
- `notes/` — committed testing-result notes (evidence, not specification)

Operator install/runbook (not architecture): `Instructions/`.

All repository documentation is written in English.
