#!/usr/bin/env python3
"""Opt-in experiment CLI. See --help; no change to the waveform CLI/defaults."""

from ewp_waveform.application.experiments import main

if __name__ == "__main__":
    raise SystemExit(main())
