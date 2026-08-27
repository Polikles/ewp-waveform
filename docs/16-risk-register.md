# 16 — Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| FFmpeg alpha varies by build | Opaque/invalid assets | `doctor`, capability checks, integration tests |
| ProRes/PNG differ materially | Inconsistent edit assets | canonical visual contract + fidelity tests |
| FFmpeg cannot express desired styles/effects | Fragile filter graphs | keep FFmpeg baseline, document limits, custom renderer |
| Chunk seams/reset state | Visible production defects | continuity contract + torture benchmarks |
| Resume differs from uninterrupted | Hidden defects | checkpoint validation + resume benchmark/warning |
| Single transient suppresses long waveform | Poor visual consistency | robust normalization + soft clipping |
| PNG sequence explodes disk usage | Failed long jobs | free-space checks + benchmark dry-run estimates |
| Signature omits visual input | Incorrect SKIP | ADR + signature tests |
| Performance settings alter appearance | Non-reproducible result | invariance tests |
| Future GPU path is nondeterministic | Backend mismatch | explicit tolerances + GPU validation |
| Public plugins destabilize API/security | Maintenance/security burden | plugin-ready only, defer public API |
| Benchmarks mutate defaults | Unreviewed behavior | explicit save/adopt only |
| License/commercial-use misunderstanding | Users treat the project as OSI Open Source or ignore the revenue threshold | keep LICENSE/LICENSING.md/CONTRIBUTING.md aligned; public release still requires those terms to remain visible |
| Failed workdirs consume disk | Disk exhaustion | cleanup/reporting + configurable persistent mode |
