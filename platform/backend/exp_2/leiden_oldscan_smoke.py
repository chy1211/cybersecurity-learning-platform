#!/usr/bin/env python3
"""Smoke check for loading the legacy Leiden 18-parameter scan JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = Path(__file__).resolve().parents[5]
PHASE2_DIR = BACKEND_DIR / "exp_2" / "phase2"
sys.path.insert(0, str(PHASE2_DIR))

import step2_1_leiden as leiden  # noqa: E402


REQUIRED_KEYS = {
    "gamma",
    "minCommunitySize",
    "writeProperty",
    "communityCount",
    "modularity",
    "top50_coverage",
    "largest_community_pct",
    "largestCommunitySize",
    "smallestCommunitySize",
    "sizeDistribution",
}


def main() -> int:
    oldscan = (
        WORKSPACE_DIR
        / "論文"
        / "實驗"
        / "Phase2_圖譜結構化"
        / "結果"
        / "leiden_18params_compare.json"
    )
    out = WORKSPACE_DIR / "_tooling" / "rerun_test" / "leiden_oldscan_load.txt"
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = leiden.__doc__ or ""
    errors: list[str] = []
    if "--gamma 1.5" not in doc or "--min_community_size 3" not in doc:
        errors.append("docstring_final_example_not_aligned")
    if "重跑掃描結果" not in doc:
        errors.append("docstring_missing_rescan_note")

    result_dir = out.parent / "scan_out"
    args = leiden.parse_args(["--result-dir", str(result_dir)])
    expected_output = result_dir / leiden.OUTPUT_FILENAME
    if Path(args.output) != expected_output:
        errors.append("result_dir_does_not_control_default_output")

    data = json.loads(oldscan.read_text(encoding="utf-8"))
    rows = data.get("results", [])
    expected_pairs = {(g, m) for g in leiden.GAMMAS for m in leiden.MIN_SIZES}
    actual_pairs = {(row.get("gamma"), row.get("minCommunitySize")) for row in rows}
    if len(rows) != len(expected_pairs):
        errors.append(f"result_count={len(rows)} expected={len(expected_pairs)}")
    if actual_pairs != expected_pairs:
        errors.append("parameter_grid_mismatch")

    lines = [
        "leiden_oldscan_load",
        f"source={oldscan}",
        f"total_configs={len(rows)}",
        f"expected_configs={len(expected_pairs)}",
        "rows:",
    ]
    for row in sorted(rows, key=lambda r: (r["gamma"], r["minCommunitySize"])):
        missing = sorted(REQUIRED_KEYS - set(row))
        if missing:
            errors.append(
                f"missing_keys gamma={row.get('gamma')} min={row.get('minCommunitySize')} keys={','.join(missing)}"
            )
        dist = row.get("sizeDistribution", {})
        large = sum(int(dist.get(key, 0)) for key in ("10-49", "50-99", ">=100"))
        lines.append(
            "gamma={gamma:.1f} minSize={min_size} communityCount={community_count} "
            "modularity={modularity:.6f} largeCommunities={large}".format(
                gamma=float(row["gamma"]),
                min_size=int(row["minCommunitySize"]),
                community_count=int(row["communityCount"]),
                modularity=float(row["modularity"]),
                large=large,
            )
        )

    lines.insert(4, f"status={'PASS' if not errors else 'FAIL'}")
    if errors:
        lines.append("errors=" + ";".join(errors))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if errors:
        print("FAIL leiden_oldscan_smoke " + ";".join(errors))
        return 1
    print("PASS leiden_oldscan_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
