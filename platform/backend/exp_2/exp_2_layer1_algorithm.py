#!/usr/bin/env python3
"""Layer 1 algorithm-level metrics for experiment 2."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any


def load_compare(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    for key in ("results", "configs", "leiden_results", "comparisons"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    raise ValueError(f"Unsupported Leiden comparison JSON format: {path}")


def _as_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bucket_midpoint(label: str) -> int | None:
    cleaned = label.strip().replace(" ", "")
    if cleaned.isdigit():
        return int(cleaned)
    for sep in ("-", "~", "–"):
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            if left.isdigit() and right.isdigit():
                return max(1, round((int(left) + int(right)) / 2))
    if cleaned.endswith("+") and cleaned[:-1].isdigit():
        return int(cleaned[:-1])
    return None


def expand_size_distribution(row: dict[str, Any]) -> list[int]:
    sizes = row.get("communitySizes") or row.get("community_sizes") or row.get("sizes")
    if isinstance(sizes, list):
        return [int(s) for s in sizes if _as_number(s) is not None]

    dist = row.get("sizeDistribution") or row.get("size_distribution")
    if isinstance(dist, list):
        expanded: list[int] = []
        for item in dist:
            if isinstance(item, dict):
                size = item.get("size") or item.get("community_size") or item.get("bucket")
                count = item.get("count") or item.get("community_count") or 1
                if _as_number(size) is not None:
                    expanded.extend([int(float(size))] * int(count))
            elif _as_number(item) is not None:
                expanded.append(int(float(item)))
        return expanded

    if isinstance(dist, dict):
        expanded = []
        for raw_size, raw_count in dist.items():
            size = _bucket_midpoint(str(raw_size))
            count = int(float(raw_count)) if _as_number(raw_count) is not None else 0
            if size is not None and count > 0:
                expanded.extend([size] * count)
        return expanded

    count = row.get("communityCount") or row.get("community_count")
    avg = row.get("averageCommunitySize") or row.get("average_community_size")
    if _as_number(count) is not None and _as_number(avg) is not None:
        return [int(round(float(avg)))] * int(count)
    return []


def config_label(row: dict[str, Any]) -> str:
    if row.get("label"):
        return str(row["label"])
    gamma = row.get("gamma", row.get("resolution"))
    min_size = row.get("minCommunitySize", row.get("min_community_size"))
    if min_size in (None, "", "null"):
        return f"gamma={gamma}"
    return f"gamma={gamma}, min={min_size}"


def summarize_configs(rows: list[dict[str, Any]], selected_gamma: float | None = None, selected_min_size: int | None = None) -> dict[str, Any]:
    table_rows = []
    for row in rows:
        sizes = expand_size_distribution(row)
        # 優先使用儲存的 communityCount（比 len(sizes) 準確）
        community_count = row.get("communityCount") or row.get("community_count")
        community_count = int(community_count) if _as_number(community_count) is not None else len(sizes)
        total_nodes = sum(sizes)
        small_count = sum(1 for size in sizes if size < 3)
        table_rows.append(
            {
                "label": config_label(row),
                "gamma": row.get("gamma", row.get("resolution")),
                "min_community_size": row.get("minCommunitySize", row.get("min_community_size")),
                "modularity": row.get("modularity"),
                "community_count": community_count,
                "top50_coverage": row.get("top50_coverage"),
                "largest_community_pct": row.get("largest_community_pct"),
                "largest_community_size": row.get("largestCommunitySize") or (max(sizes) if sizes else None),
                "smallest_community_size": row.get("smallestCommunitySize") or (min(sizes) if sizes else None),
                "total_nodes_in_distribution": total_nodes,
                "average_community_size": (total_nodes / len(sizes)) if sizes else None,
                "median_community_size": median(sizes) if sizes else None,
                "small_community_count_lt3": small_count,
                "small_community_ratio_lt3": (small_count / len(sizes)) if sizes else None,
                "size_distribution": sizes,
            }
        )

    # 選定邏輯：若明確指定 gamma + min_size，找到對應行；否則選最高 modularity
    if selected_gamma is not None and selected_min_size is not None:
        selected = next(
            (r for r in table_rows
             if _as_number(r.get("gamma")) == selected_gamma
             and _as_number(r.get("min_community_size")) == selected_min_size),
            None,
        )
        selection_rule = f"explicit: gamma={selected_gamma}, min={selected_min_size}"
    else:
        selected = max(
            table_rows,
            key=lambda item: float(item["modularity"]) if _as_number(item.get("modularity")) is not None else -math.inf,
        ) if table_rows else None
        selection_rule = "highest_modularity"

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "layer": "algorithm",
        "selection_rule": selection_rule,
        "selected_config": selected,
        "table_rows": table_rows,
    }


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def write_markdown(data: dict[str, Any], path: Path) -> None:
    lines = [
        "# 表 4-9 第一層：演算法層指標草稿",
        "",
        "| 參數組 | γ | k | Modularity | 有效社群數 | Top-50 覆蓋率 | 最大社群% | 最大社群節點數 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in data["table_rows"]:
        top50 = row.get("top50_coverage")
        top50_str = f"{top50*100:.1f}%" if top50 is not None else "N/A"
        lp = row.get("largest_community_pct")
        lp_str = f"{lp*100:.1f}%" if lp is not None else "N/A"
        lines.append(
            "| {label} | {gamma} | {min_size} | {modularity} | {count} | {top50} | {lp} | {largest} |".format(
                label=row["label"],
                gamma=_fmt(row["gamma"]),
                min_size=_fmt(row["min_community_size"]),
                modularity=_fmt(row["modularity"], 4),
                count=row["community_count"],
                top50=top50_str,
                lp=lp_str,
                largest=_fmt(row["largest_community_size"]),
            )
        )
    selected = data.get("selected_config") or {}
    t50_val = selected.get("top50_coverage")
    lp_val  = selected.get("largest_community_pct")
    t50_str = f"{t50_val*100:.1f}%" if t50_val is not None else "N/A"
    lp_str2 = f"{lp_val*100:.1f}%"  if lp_val  is not None else "N/A"
    lines.extend([
        "",
        f"**選定參數組**：`{selected.get('label', 'N/A')}`（{data['selection_rule']}）",
        "",
        f"- Modularity = {_fmt(selected.get('modularity'), 4)}",
        f"- 有效社群數 = {selected.get('community_count', 'N/A')}",
        f"- Top-50 覆蓋率 = {t50_str}",
        f"- 最大社群比例 = {lp_str2}",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_size_distribution_plot(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = data["table_rows"]
    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7.2, 4.2))
        markers = ["o", "s", "^", "D", "x"]
        linestyles = ["-", "--", "-.", ":"]
        for idx, row in enumerate(rows):
            sizes = row["size_distribution"]
            counts: dict[int, int] = {}
            for size in sizes:
                counts[int(size)] = counts.get(int(size), 0) + 1
            xs = sorted(counts)
            ys = [counts[x] for x in xs]
            ax.plot(
                xs,
                ys,
                color=str(0.15 + 0.18 * (idx % 4)),
                marker=markers[idx % len(markers)],
                linestyle=linestyles[idx % len(linestyles)],
                linewidth=1.6,
                markersize=4.5,
                label=row["label"],
            )
        ax.set_xlabel("Community size")
        ax.set_ylabel("Number of communities")
        ax.set_title("Leiden community size distribution")
        ax.grid(True, axis="y", alpha=0.25)
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(path, dpi=180)
        plt.close(fig)
    except Exception:
        # Minimal valid 1x1 PNG fallback; real runs should install matplotlib.
        path.write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
                "0000000c4944415408d763f8ffff3f0005fe02fea73581e80000000049454e44ae426082"
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--leiden_compare", type=Path, required=True)
    parser.add_argument("--output_json", type=Path, required=True)
    parser.add_argument("--output_plot", type=Path, required=True)
    parser.add_argument("--selected_gamma", type=float, default=None,
                        help="指定選定的 gamma 值（與 --selected_min_size 搭配使用）")
    parser.add_argument("--selected_min_size", type=int, default=None,
                        help="指定選定的 minCommunitySize 值")
    args = parser.parse_args()

    metrics = summarize_configs(
        load_compare(args.leiden_compare),
        selected_gamma=args.selected_gamma,
        selected_min_size=args.selected_min_size,
    )
    write_json(metrics, args.output_json)
    write_markdown(metrics, args.output_json.with_suffix(".md"))
    write_size_distribution_plot(metrics, args.output_plot)
    sel = metrics.get("selected_config") or {}
    print(f"wrote layer1 metrics to {args.output_json}")
    print(f"  選定參數組: {sel.get('label')}  modularity={sel.get('modularity')}  社群數={sel.get('community_count')}  top50={sel.get('top50_coverage')}  最大社群%={sel.get('largest_community_pct')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
