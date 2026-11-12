# Operator instructions

These files describe internal-MVP checkout-based installation and operation of
`waveform` 0.3.1 with uv, Python >=3.12,<3.13 and system FFmpeg. Ubuntu/WSL is a
reference recipe, not a blanket clean-host qualification. They are not the
architecture spec (`docs/`).

1. [`install.md`](./install.md) — checkout/uv recipe, restored-environment notes and qualification boundaries.
2. [`runbook.md`](./runbook.md) — daily CLI, outputs, SKIP/resume, limits, future host QA checklist (not a completed deployment test).

Version 0.3.0 adds opt-in [experiment tooling](../docs/24-experiments.md), preserving the opt-in mapping7 ribbon, separate Moving mouth,
selectable appearance/reflection/horizon and foreground modes. Existing CLI
defaults and transparent MOV/PNG outputs remain unchanged. See
[`../WORK_STATUS.md`](../WORK_STATUS.md) for bounded operator feedback and the
separate performance qualification; automatic MP4 export and full manuals remain future
work.

Developer quality gates remain in [`../DEVELOPMENT.md`](../DEVELOPMENT.md).
