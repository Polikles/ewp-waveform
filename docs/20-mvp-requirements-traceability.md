# 20 — MVP Requirements Traceability

| Requirement family | Primary spec | Planned evidence |
|---|---|---|
| FR-CLI-* | `05-cli-specification.md` | CLI unit/integration |
| FR-IN-* | `04-input-discovery-and-grouping.md` | ffprobe/input integration |
| FR-GROUP-* | `04-input-discovery-and-grouping.md` | grouping/timeline tests |
| FR-RENDER-* | `03-architecture.md`, `10-rendering-and-effects.md` | renderer protocol/integration |
| FR-STYLE-* | `10-rendering-and-effects.md` | capability/regression |
| FR-EFFECT-* | `10-rendering-and-effects.md` | effect regression |
| FR-NORM-* | `11-normalization.md` | analysis/visual benchmarks |
| FR-OUTPUT-* | `08-output-formats.md` | output/fidelity tests |
| FR-RESULT-* | `07-results-data-model.md` | schema tests |
| FR-RESUME-* | `18-recovery-and-workdirs.md`, `22-chunking-and-continuity.md` | chunk/resume integration |
| FR-PREVIEW-* | `19-preview-system.md` | preview integration |
| FR-CONFIG-* | `06-configuration.md` | precedence/schema/write safety |
| FR-BENCH-* | `13-benchmarking.md` | benchmark manifest/dry-run |
| NFR-DET-* | `12-testing-and-acceptance.md` | deterministic regression |
| NFR-MAINT-* | `03-architecture.md`, `AGENTS.md` | architecture/static checks |
| NFR-PERF-* | `13-benchmarking.md` | performance/endurance |
| NFR-PORT-* | `14-dependency-baseline.md` | WSL/bare-metal validation |
| NFR-TEST-* | `TESTING_STRATEGY.md` | quality gate |

## Initial ADR links

- ADR-0001 -> NFR-MAINT-001/002
- ADR-0002 -> FR-RENDER-002/003/004
- ADR-0003 -> FR-CONFIG-*
- ADR-0004 -> FR-RENDER-012, FR-OUTPUT-012/013, NFR-DET-*
- ADR-0005 -> FR-OUTPUT-009..013
- ADR-0006 -> FR-RESUME-*, NFR-DET-002
- ADR-0007 -> FR-OUTPUT-001..008
- ADR-0008 -> FR-IN-003, FR-NORM-001
- ADR-0009 -> FR-GROUP-001..004
- ADR-0010 -> NFR-MAINT-003/004
- ADR-0011 -> FR-RENDER-009/010, FR-EFFECT-004, FR-RESUME-015
