"""Retired legacy entry point.

The B4 semantic-gate threshold/margin calibration was replaced on 2026-07-12 by a model-in-the-loop node picker (the evaluated model chooses among embedding candidates or answers "none"); there is no human gold-labeling or precision calibration step anymore. Use the model-in-the-loop node picker instead.
"""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="retired B4 threshold calibration entry point")
    parser.parse_args()
    raise RuntimeError(
        "calibrate_b4_linker.py is retired; B4 now uses model-in-the-loop node linking (route 2), no threshold calibration"
    )


if __name__ == "__main__":
    raise SystemExit(main())
