# Batch Layout Example

Input:

```text
audio/
├── s0e00-Damian.wav
├── s0e00-Guest.wav
├── s0e01-Damian.wav
└── interview.mp3
```

Groups:

```text
s0e00 -> Damian, Guest
s0e01 -> Damian
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
