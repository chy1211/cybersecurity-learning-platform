"""Retired legacy entry point.

The old retry script accepted provenance-free entity lists and performed
arbitrary fallback retrieval.  B4 intentionally removes that path.  Use
``exp_3_nf1_pipeline.py`` after the linker calibration and freeze preflight
instead.
"""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="retired B4-incompatible retry entry point")
    parser.parse_args()
    raise RuntimeError(
        "nf1_retry_step1.py is retired; rerun the strict B4 NF1 pipeline after freeze"
    )


if __name__ == "__main__":
    raise SystemExit(main())

