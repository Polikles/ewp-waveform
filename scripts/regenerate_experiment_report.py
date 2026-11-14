#!/usr/bin/env python3
"""Text-only recovery of retained portable reports; never resumes a campaign."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ewp_waveform.application.portable_experiments_reporting import regenerate_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--records",
        required=True,
        type=Path,
        help="retained report JSON, diagnostics JSON or measurements JSON (<=64MiB)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new text-only recovery directory; must not already exist",
    )
    args = parser.parse_args()
    try:
        path = regenerate_report(args.records, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Report-only recovery failed: {type(exc).__name__}: {exc}\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
