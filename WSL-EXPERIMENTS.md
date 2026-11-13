# WSL experiment command compatibility

The single maintained guide for WSL and native Windows is
[EXPERIMENTS.md](EXPERIMENTS.md).

The existing command remains supported:

```bash
python3 scripts/run_wsl_experiments.py --audio "/mnt/d/test-waveform/s0e00/s0e00-Damian.wav"
```

Ordinary launches use the same portable driver as `scripts/run_experiments.py`.
Historical successful-session resume retains its original frozen implementation;
failed campaigns are not rewritten or automatically retried. The original WSL
campaign and its completed CPU reference remain preserved. See the canonical
guide for qualification, CUDA/native Windows options, output review and diagnostics.
