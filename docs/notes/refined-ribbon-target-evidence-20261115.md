# Supplied refined-ribbon target evidence — 2026-11-15

This additive record supersedes earlier **current-use** statements that the combined
CUDA candidate is unmeasured or the ordinary Windows helper has never succeeded.
Earlier dated failures, tests and acceptance records remain historical, unchanged.
[Curated structured evidence](../../examples/experiments/refined-ribbon-target-evidence-20261115.json)
retains the complete Windows `resolved_visual_config`, analysis/normalization,
resolved performance policy and compact CUDA observations. The two supplied JSON
files were fully parsed and SHA-256 checked locally; the 11,658,952-byte diagnostic
is retained outside Git, not copied into product evidence.

## Native Windows production and bounded Resolve acceptance

The direct user reports successful native PowerShell execution:

```powershell
py -3 scripts/render_refined_ribbon.py --audio "D:\test-waveform\s0e00\s0e00-Damian.wav"
```

The supplied production result identifies
`s0e00-Damian_iuris-ribbon-refined-production_686199051c86.mov` under the helper's
`20261115T131813Z-608051cc5e53/output/s0e00/` namespace. The user confirms that
**this full MOV imported and displayed correctly in Resolve Studio**. This is
import/display acceptance only: exhaustive playback, color management, long-timeline
behavior, exact-artifact download and cleanup are not established or authorized.
This is a native target observation, not simulated Windows or fresh local execution.

Result JSON SHA-256:
`838def7bdabda9a7cb566dbcff767cd67817c141d2417c8bfa9fbe3558784ae1`.
Producing Git commit, whole-MOV SHA-256 and output size are **unknown/null**; do not
borrow the historical VM.1 full-master hash or infer source from the repair checkout.
The reported input is mono 48kHz PCM, SHA-256
`e7088a3dfdfc12323acbc2d4f9d4c0af304b95eaabfe80e45becbcf7bb16348b`,
395.6785s. Reported successful validation: 23,741 frames, 1400×280 at60fps,
395.683333s frame-grid duration, ProRes `yuva444p12le`. This is the ordinary silent
transparent asset route. Alpha-capable metadata and the user's import/display
observation are distinct from an independently rerun all-frame content-alpha test;
no such local media validation was performed.

Effective execution is `ribbon-lut`, serial/jobs1, `ffmpeg_threads=0`, actual LUT
qualification passed (0.5828614s). Zero requests automatic encoder threads; it is
not an observed thread count or process/filter cap. The complete effective look is
retained, not reconstructed from the preset name: mapping7/filled-ribbon-v2,
balanced, custom cyan `#C7E6EC`, amplitude0.82, stroke1, high glow,
smoothing0.06, noise0.35/rate0.8/seed1729, idle0, reflection0.45,
horizon enabled/extent0.96/opacity0.55, physical horizontal supersampling2.
Normalization is auto/soft-clip, observed peak0.016299445951048236; analysis-cache
observation is miss. Other resolved fields remain in the structured record.

The result's 2026-11-15T13:18:17Z→13:19:46Z timestamps give **89s job duration**,
not launcher/bootstrap-to-exit time and not the CUDA service timer. Generator
74.3527036s contains visual-field33.3542760s and raster39.8312216s; these inclusive
phases are non-additive. Blocking FFmpeg feed12.6913214s is not encoder CPU time.
Do not compare the Windows89s to WSL short/service timings.

## Completed WSL RTX3090 combined-CUDA campaign — do not rerun

Supplied diagnostic SHA-256:
`55bd33eeea0fc892b67d08f964c596f4641f269a1c62b0a5a841d93f24a21e6f`.
It reports COMPLETE, no error/failure, clean P
`4b306068ee804a4a2242b66e19e3e9fe1aa83d28`, both GPU qualification gates passed,
and eight successful serial application-service observations on RTX3090. Original
raster, finished/pre-encode RGBA and decoded RGBA hashes agree within each workload.
The independent lossy-ProRes pre-encode losslessness proof remains NOT_PERFORMED;
reference-master equality is not that proof. Preserve the qualification record's
`transfer_qualified=false`; GPU finishing qualification passed, not a separately
promoted transfer-only control.

A = retained CUDA host-reuse/batch1/diagnostic; B = CUDA device-RGBA8/batch2/ordinary.
These are **two implementations of the same FIR finishing algorithm**, not CPU
versus CUDA. Sequential AB then BA gives n=2 per side per interval:

| Workload | A service median | B service median | Descriptive less service wall |
|---|---:|---:|---:|
| [25,29),240frames | 4.351137s | 4.035875s | 7.25% |
| [25,57),1,920frames | 16.651205s | 13.418957s | 19.41% |

Service wall includes initialization/import/context, per-encode qualification,
normal validation and publication. Cold worker envelopes and external verification
have different boundaries. For32s, cold medians are22.382192→20.461032s; external
verification medians are4.658770→5.992483s (initial reference checks are asymmetric).
Views remain separate. These descriptive n2 observations do not isolate GPU arithmetic
or establish CPU superiority/inferiority, full-file speedup or new visual/NLE promotion.

All four native MOV identities within each workload agree in the supplied record:

- 4s: `aef0f75cb66ff779a422bc855d508a4d124327c39697c18dbc014b877a75d17c`.
- 32s: `3f9e7a9bb48981c681902b770182ea55ec9ecba7e70a225777e06b5ccac3808d`.

The diagnostic is self-contained **reported evidence**, with excerpted raw subrecords,
not independent local media/ledger/environment revalidation or signed attestation.
Its FRESH labels describe the original target invocation, not this documentation task.
Prior failed WSL CPU records remain SALVAGED_UNVERIFIED/n0; no historical comparison
is rerun or authenticated by this new CUDA record. The combined control campaign is
closed. Its old flags remain replay interfaces, not the recommended next task.

## Completed matched CPU/LUT versus CUDA FIR screen

The subsequently supplied `report-7f9a02425e04-diagnostics.json` is COMPLETE with
fresh observations on clean P`4326f8e1706f48c760bba0a0fdf4dc43d9dc5750`, tree
`b892827ece0c8fa6c2401dae2e5bfbdc9a133f1f`. Its2,852,654bytes were parsed locally;
SHA-256`76939afa4c904f13be9a5f5c21b89e8edbe80b9a1fba9d16185fdfc059f992f9`.
[Curated numeric record](../../examples/experiments/refined-ribbon-matched-target-20261115.json).
Both independent qualifiers passed on RTX3090, same retained CUDA interpreter,
selected FFmpeg and effective production appearance. A is CPU serial/LUT with
recursive blur; B is CUDA FIR/device-RGBA8/batch2/ordinary. Each interval is fresh
sequential AB/BA, n=2 per side, with same-side repeat references only:

| Interval | CPU service median | CUDA service median | CPU cold-worker median | CUDA cold-worker median |
|---|---:|---:|---:|---:|
| 4s | 3.048876s | 4.056735s | 4.436340s | 5.645239s |
| 32s | 12.563301s | 13.477869s | 18.116119s | 19.348109s |

Service includes lazy initialization, per-encode qualification, normal validation
and publication. Representative qualification costs about0.96s CPU and2s CUDA
are already included, not subtractable ordinary-workflow savings. Cold worker
also includes external verification. These are different finishing algorithms,
not isolated backend arithmetic or cross-side finished-pixel equivalence. Original
raster/config checks remain matched. Diagnostics are reported target evidence,
not local execution or independent media/ledger revalidation. Windows89s remains
an unmatched job-duration observation, not an isolated OS/backend comparison.
No full-source winner or two-duration crossover is inferred; do not rerun shorts.

## Explicit full-source confirmation is prepared, not executed here

The next action is the separate
[full confirmation opt-in](../../EXPERIMENTS.md#explicit-full-source-confirmation--2026-11-15):
one fresh CPU control followed by one fresh CUDA candidate, complete original
source/history/normalization, n=1 per side and separately admitted12GiB growth
with10GiB free reserve. Both native MOVs stay on the operator host. No full-input
CPU or CUDA render was generated on VM.1 for this preparation. Local simulations
and tiny real CPU-Torch fixtures do not qualify native CUDA hardware.

Keep the accepted Windows CPU/ProRes command unchanged. After full costs and
correctness are available, a useful CUDA result additionally needs its retained
native Resolve assessment before promotion; otherwise leave CUDA experimental
and close this single-file style pass around the proven CPU workflow. Unchanged
accepted CPU assets do not need repeated assessment. Two mono recordings still
mean two independent assets; convenient multi-file procedure, GUI and other styles
remain deferred. All historical media holds/source identities remain unchanged.
