#!/usr/bin/env python3
"""Run one ordinary full-file CPU serial/LUT render with prepared tools only."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ewp_waveform.application.production_render import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
