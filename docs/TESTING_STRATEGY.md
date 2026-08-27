# Testing Strategy

## Intended gates

```bash
make check
make test-integration
```

Implementation must make these operational.

## Layout

```text
tests/unit
tests/integration
tests/regression
tests/fixtures
```

Committed fixtures must be redistributable and non-private.

## Unit
Config resolution, signatures, grouping, frame calculations, capabilities, diagnostics, schema/domain models.

## Integration
ffprobe/FFmpeg, media validation, source immutability, workdirs/atomic publication, interruption/recovery.

## Regression
Small visual/timing fixtures. Use documented tolerances when byte identity is inappropriate.

## Benchmarks are not acceptance tests

Correctness tests determine whether contracts are satisfied. Benchmarks measure quality/performance tradeoffs and may justify explicit default changes later.
