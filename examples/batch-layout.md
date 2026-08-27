# Batch Layout Example

Input:

```text
audio/
├── s0e00-Szymon.wav
├── s0e00-Damian.wav
├── s0e01-Szymon.wav
└── interview.mp3
```

Groups:

```text
s0e00 -> Szymon, Damian
s0e01 -> Szymon
interview -> interview
```

Default output:

```text
audio/waveform-output/
├── s0e00/
├── s0e01/
└── interview/
```

Equivalent completed jobs are skipped by render signature.
