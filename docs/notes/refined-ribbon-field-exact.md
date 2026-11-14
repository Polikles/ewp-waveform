# Exact refined-ribbon field micro-optimization

This is a bounded mapping-revision-7 optimization, not a new visual algorithm or
an application-throughput claim. Baseline: `98e68e1480a585b6bc594543530383eade8048f1`.
Only `RefinedRibbonMapping` changes; other mappings, render signatures, raster,
normalization, publication, and encoding are unchanged.

## Retained implementation

- Retain one instance-local fixed geometry table of
  `float(slot - self.center) - lobe_center`, keyed by the complete geometry
  dependencies: center, the lobe-center tuple, and carrier length. Changing carrier
  gains does not invalidate geometry; the gains are still read every evaluation.
- Evaluate the original `strength * exp(-0.5 * (offset / width) ** 2)` terms with
  lobe-major list comprehensions, then transpose for each original slot's `sum`.
  Every slot sees the same terms in the same lobe order. In particular, division
  still precedes squaring, and Python's native float `sum` is not replaced by a
  differently rounded accumulator. All 129 × 21 field exponentials remain.
- All descriptor, level, width, contrast, noise, absolute-time and idle inputs are
  evaluated as before. This is not a field/output/packet memo. The preexisting
  finite descriptor ring is not a new optimization here.
- Correct that ring's configuration identity to include `n_bands`,
  `feature_weights`, and lobe count as well as sequence identity/capacity.
  An independent uncached oracle exposed stale descriptors after replacing public
  configuration attributes. The new state-replacement test failed against the
  original source and passes with the fix. Immutable tuple-valued configuration
  replacements between evaluations are covered; concurrent configuration writes
  are not a supported synchronization contract.

## Descriptive micro measurements

Prepared Python 3.12.3 interpreter, existing dependencies, synthetic 64-band,
120-frame sequence, 60 fps, and identical input/settings per pair. Six sequential
paired batches alternate AB/BA order. `perf_counter_ns` spans 120 completed Python
field calls per cell; import/construction/warmup/oracle/profile/tracemalloc are
excluded. Baseline is loaded from the exact Git source, including its already
implemented descriptor ring. Random-access/state tests use a separate frozen
arithmetic oracle which bypasses descriptor memoization entirely.

| Completed call | Baseline median µs | Candidate median µs | Reduction |
| --- | ---: | ---: | ---: |
| composition, visual noise 0 | 407.24 | 311.52 | 23.5% |
| composition, visual noise 0.35 | 413.15 | 311.36 | 24.6% |
| `apply_at`, sequential 120-frame sweeps | 487.12 | 406.20 | 16.6% |
| active `idle_at` | 403.84 | 312.64 | 22.6% |

These are shared-host micro costs, not render FPS, service wall time, isolated CPU
qualification or statistical significance. Actual application comparison remains
with the integrating agent. Separate cProfile runs identify the original inner
generator/reduction overhead; instrumented profile wall is not throughput.

The temporary lobe-major terms trade bounded allocation for fewer generator
resumptions/unpacks. `tracemalloc` around one cold composition observed baseline
5,608-byte peak / 1,296-byte retained and candidate 182,792-byte peak /
87,736-byte retained. Construction is excluded. The retained geometry is one
21 × 129 table per instance; replacement does not accumulate prior geometries.
These are traced Python allocation bytes, not process RSS or whole-render peaks.

### Rejected temporal precomputation

A lazy finite-support exponential/prefix-total table was implemented and tested
with the original arithmetic, then measured against the geometry candidate without
that table. Six alternating paired synthetic sweeps observed medians 393.89 µs
without and 394.76 µs with it (0.22% slower, a descriptive near-tie). No worthwhile
benefit was established, so the temporal table was removed. The shipped temporal
loop and its `total += weight` reduction remain unchanged. Earlier exploratory
geometry variants and the temporal screen are retained separately from the final
candidate measurements; they are not final-candidate throughput evidence.

## Verification and limits

`tests/unit/test_ribbon_field_exact.py` freezes original composition and temporal
arithmetic, checks binary64 field bytes (not approximate comparison), and exercises
three detail settings, four frame rates, three noise amounts, different sequences,
random/repeated access, public configuration replacements, origin/seed/rate,
nonzero idle, silence, fresh chunk workers, pickle/thread evaluation, bounded
geometry, malformed texture, empty carrier and zero-lobe floor behavior.

Final scoped visual/ribbon/style tests: **203 passed, 13 skipped**; the skips are
existing optional `jsonschema` checks, unavailable in the prepared environment.
Repository-wide Ruff and mypy (`src tests`, 216 files) passed, as did formatting
checks for changed Python files and `git diff --check`. No dependencies were
installed. No original workloads, FFmpeg or media generation were performed.
Full application benchmarking, broad integration gates and integration/review are
not claimed by this field-only worktree.
