#!/usr/bin/env python3
"""Maintained stdlib-first WSL/native-Windows experiment entry point.

Bootstrap may use Python >=3.10. Actual application work uses frozen Python 3.12.
See --help; rendering and orchestration belong to the application API.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ewp_waveform.application.portable_experiments import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
