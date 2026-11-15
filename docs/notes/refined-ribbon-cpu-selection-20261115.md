# Refined ribbon: completed comparison and practical CPU selection

## Decision and scope — 2026-11-15

The current optimization pass is closed around the usable **single-file CPU
workflow** for stationary refined ribbon, mapping7 / filled-ribbon-v2, with the
saved `iuris-ribbon-refined-production` appearance. Use the existing
[ordinary Windows command](../../EXPERIMENTS.md#ordinary-full-file-windows-cpu-render-no-experiment-campaign),
not an experiment campaign. Production appearance, code, execution profiles and
other styles' defaults are unchanged. No further render is needed to close this pass.

The full and earlier short observations support CPU as the practical choice for
this implementation, style and workload. They do not establish statistical
superiority, an isolated kernel speedup, a universal platform winner or permanent
rejection of GPU. CUDA stays opt-in for future improvements, other styles and
multi-file throughput work.

## Completed full-source observation

Supplied report `cf7c9a5277e5`, operator run
`run-20261115T183352Z-29e1d9fa`, is **COMPLETE / VALIDATED PAIR**. It executed clean
source `43682ff0c0afa8b32ec1d9f4c5a9d67215bc4ad0`, tree
`6d253be1985a0f668eeed6d44c4a7c11da4ade88`. One fresh CPU control A was followed
by one fresh CUDA candidate B: **n=1 per side, order AB, not counterbalanced**.
These are single observations, not medians or statistical proof.

Both sides used the same target, selected worker interpreter and FFmpeg, input,
saved appearance, full-source normalization and causal history, cache policy and
measurement boundaries. CPU used qualified LUT with recursive FFmpeg blur; CUDA
used FIR, device RGBA8, frame batch2 and ordinary completed timing. This compares
whole pipelines with **different finishing algorithms**, not isolated acceleration
of the same kernel or cross-side finished-pixel equality.

| Observed cost | CPU | CUDA |
|---|---:|---:|
| Service total | 134.836780 s | 161.968311 s |
| Cold worker total | 176.112998 s | 203.427444 s |
| External verification | 38.868175 s | 39.026368 s |

Service includes initialization, per-encode qualification, analysis, original-raster
hashing, normal validation and publication. Cold worker additionally includes
launch/import and external verification. These scopes overlap: **do not add the
columns or subtract qualification into a claimed saving**. No new measurement was
performed for this documentation closeout.

Both native MOVs passed their own complete reported verification: 23,741 frames,
1400×280, 60 fps, zero reported PTS error, silent ProRes4444 with content alpha.
CUDA's final one-frame batch passed: 11,870 full pairs plus one final frame at
zero-based index23,740 (11,871 batch calls). The shared original-raster SHA-256 is
`22783877e992eda7fde8fb1cae93bdacf38e9bbbb4205133ae54fdb9c7a860b1`.
The lossy-ProRes pre-encode losslessness proof remains NOT_PERFORMED.

Native output identities reported by this campaign:

- CPU: 2,848,387,115 bytes; SHA-256
  `00652a1b5255b8c1cbe0bc82381bd151f7e56d2b3aecfe87683d25ed3d79da78`.
  The operator identifies these as the retained accepted full master's exact bytes;
  no repeat visual assessment is required for identical bytes.
- CUDA: 2,745,494,554 bytes; SHA-256
  `65850997e08e011182bc581baf3955f46afd4039a8528105f0d8eedfdb2e0ddf`.
  Full native Resolve assessment is still pending. CUDA is not being promoted, so
  that gate neither blocks the CPU decision nor requests another operator review.

The original report's visual/Studio PENDING and promotion NOT_APPROVED labels are
preserved. This separate practical CPU selection and operator identity/acceptance
record does not rewrite those historical statuses. Supplied text was parsed and
reconciled locally; media, environments and the original ledger were not copied
or independently revalidated. Original host paths are not VM.1 locations.

Source report identities (SHA-256):

- `report-cf7c9a5277e5-diagnostics.json` (10,239,783 bytes):
  `46e729cfabf218e6919cada080155cc832537201d0fbe7c2009a45a31e1c06bc`.
- `report-cf7c9a5277e5.md` (9,809 bytes):
  `1ac7f20439001a890759e6ec4963cb0f8de66e5c1e2d0354b48f7d34df58ed25`.
- `measurements-cf7c9a5277e5.json` (301,189 bytes):
  `b5482d57ab4df92d9dcd01d5669c3139f61c2e3b3fec2aa60e3b0e98c5d1748a`.

## Earlier short comparison and separate Windows usability evidence

The [previous matched WSL screen](refined-ribbon-target-evidence-20261115.md#completed-matched-cpulut-versus-cuda-fir-screen)
remains distinct: report `7f9a02425e04`, clean P`4326f8e`, n=2 per side, AB/BA.
Service medians were 4s CPU3.048876 / CUDA4.056735s and 32s CPU12.563301 /
CUDA13.477869s. These small descriptive samples support the bounded practical
choice; do not pool them with the full n1 or infer a crossover or general GPU limit.

The [ordinary native Windows result](refined-ribbon-target-evidence-20261115.md#native-windows-production-and-bounded-resolve-acceptance)
was SUCCEEDED, validation passed, no warnings, 395.6785s input, 23,741 frames at
1400×280/60fps, saved production appearance and `ribbon-lut` jobs1 / automatic
encoder threads / qualified LUT. The operator explicitly accepted its native
Resolve Studio import and display. Its **89s job duration** is not a matched
bootstrap-to-exit OS benchmark. Its producing Git commit and whole-MOV hash remain
unknown; **the WSL CPU hash above does not identify the Windows asset**.

## Next work — independent of editing

- **Complete and usable:** one-file saved refined-ribbon CPU command, one transparent
  MOV per input; continue editing with the accepted asset. No closing rerender or
  repeated CPU appearance review is necessary.
- **Deferred:** a convenient one-command multi-file procedure and batch-throughput
  testing. The two speakers have separate mono recordings, so each actual input
  produces its own independent asset. For now invoke the same helper separately
  with each recording's actual path; no second filename is assumed. No scheduler
  or new batch feature is introduced. Context/setup amortization is a future
  opportunity, not a demonstrated gain.
- **Separate future work:** other styles, settings and backends, including CUDA.
  This selection does not globally change their defaults or remove safeguards.
- **Remaining experimental gates:** full native Resolve assessment of this CUDA
  output and applicable acceptance of other changed experimental outputs before
  their promotion. They are not prerequisites for using the accepted CPU asset.

All historical failures, source identities, evidence and media-retention holds remain
unchanged. No media transfer, archive or cleanup is authorized by this closeout.
