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

## Next task, not a completed result

Follow the dedicated [current CPU/CUDA comparison scope](../../EXPERIMENTS.md#current-cpucuda-service-comparison-scope--2026-11-15).
The new comparison implementation and parent verification are pending in this record.
CPU recursive FFmpeg blur versus CUDA FIR is an intentional algorithm contrast;
no cross-algorithm byte-equality oracle or completed performance result is asserted.
Full-source comparison is deferred, conditional on useful, visually close shorts and
separate control/candidate/work capacity admission above the6GiB short budget.
Two speakers' existing mono files remain two independent assets; a convenient
one-command multi-file procedure is backlog only. No scheduler, GUI, other-style,
installation, media cleanup, archive or publication action follows from this record.
