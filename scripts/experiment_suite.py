#!/usr/bin/env python3
"""Thin opt-in adapter; application owns the complete experimental lifecycle."""

from ewp_waveform.application.experiment_suite import main

if __name__ == "__main__":
    raise SystemExit(main())
