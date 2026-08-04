#!/usr/bin/env python3
"""Smoke check for Table 16 dual-test markdown output."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(BACKEND_DIR / "exp_2"))

from exp_2_layer2_method2 import (  # noqa: E402
    compute_statistics,
    cosine_similarity,
    format_table16_markdown,
)


def _legacy_layer2_dir() -> Path:
    return (
        WORKSPACE_DIR
        / "論文"
        / "實驗"
        / "實驗8.3_Leiden三層驗證"
        / "結果"
        / "layer2"
    )


def _load_real_intermediate_stats(layer2_dir: Path) -> tuple[dict, str]:
    pairs_path = layer2_dir / "layer2_pairs.csv"
    cache_path = layer2_dir / "layer2_method2_embeddings_cache.json"
    pairs = list(csv.DictReader(pairs_path.open(encoding="utf-8")))
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    sims_in: list[float] = []
    sims_cross: list[float] = []
    for pair in pairs:
        name_a = pair["name_a"]
        name_b = pair["name_b"]
        if name_a not in cache or name_b not in cache:
            continue
        sim = cosine_similarity(cache[name_a], cache[name_b])
        if pair["pair_type"] == "in":
            sims_in.append(sim)
        elif pair["pair_type"] == "cross":
            sims_cross.append(sim)

    return compute_statistics(sims_in, sims_cross), "legacy_pairs_and_embedding_cache"


def _synthetic_stats() -> tuple[dict, str]:
    return compute_statistics(
        [0.82, 0.79, 0.76, 0.74, 0.71, 0.69],
        [0.62, 0.60, 0.58, 0.55, 0.53, 0.50],
    ), "synthetic_samples"


def main() -> int:
    layer2_dir = _legacy_layer2_dir()
    out = WORKSPACE_DIR / "_tooling" / "rerun_test" / "table16_dual_test_sample.txt"
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        stat, source = _load_real_intermediate_stats(layer2_dir)
    except Exception as exc:
        stat, source = _synthetic_stats()
        source = f"{source} fallback_reason={type(exc).__name__}"

    table = format_table16_markdown(stat)
    required = ["Welch_t", "Welch_p", "Mann_Whitney_U", "Mann_Whitney_p", "Cohen_d"]
    missing = [token for token in required if token not in table]
    if missing:
        out.write_text(
            "table16_dual_test_sample\n"
            f"status=FAIL missing={','.join(missing)}\n"
            f"source={source}\n"
            f"{table}\n",
            encoding="utf-8",
        )
        print("FAIL table16_dual_test_smoke")
        return 1

    out.write_text(
        "table16_dual_test_sample\n"
        "status=PASS\n"
        f"source={source}\n"
        f"n_in={stat['n_in']} n_cross={stat['n_cross']}\n"
        f"{table}\n",
        encoding="utf-8",
    )
    print("PASS table16_dual_test_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
