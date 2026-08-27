# 18 — Recovery and Workdirs

## Principle

Intermediate/incomplete data lives outside final output directories.

Typical workdir content:

```text
checkpoint.json
chunk/pass state
temporary frames
temporary encodes
diagnostics
```

## Success lifecycle

```text
render -> validate media -> create/validate result -> atomic publish -> remove workdir
```

## Failure/interruption

Retain workdir for recovery.

## Persistent work root

Opt-in for long benchmarks, endurance tests, deliberate multi-session jobs, and debugging. Default may be ephemeral.

## Resume validation

Require matching:

- source SHA-256;
- render signature;
- checkpoint schema;
- renderer compatibility;
- completed chunk/pass integrity.

Stale/incompatible state is never reused.

## Resume boundary

Final result stores history and emits `W_JOB_RESUMED` with source timestamp for manual review.

## Cancellation

Preferred first interrupt:

1. stop scheduling new work;
2. finish/checkpoint current safe unit where practical;
3. preserve valid work;
4. exit cancelled.

Repeated interrupt may terminate immediately.

## Cleanup

Future `waveform clean` removes abandoned workdirs under explicit criteria without touching completed final output.
