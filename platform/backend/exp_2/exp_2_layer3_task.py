#!/usr/bin/env python3
"""Layer 3 task-level chapter alignment metrics for experiment 2."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

# Load backend .env when this script is executed directly.
try:
    from pathlib import Path as _EnvPath
    from dotenv import load_dotenv as _load_dotenv
    for _env_parent in _EnvPath(__file__).resolve().parents:
        _env_file = _env_parent / ".env"
        if _env_file.exists():
            _load_dotenv(_env_file)
            break
except Exception:
    pass


def normalize_cid(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    text = str(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def cid_sort_key(cid: str) -> tuple[int, Any]:
    try:
        return (0, int(cid))
    except ValueError:
        return (1, cid)


def load_chapter_dict(path: Path) -> dict[str, str]:
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        data = _load_simple_yaml_mapping(path)

    mapping: dict[str, str] = {}
    if isinstance(data, dict):
        for source, value in data.items():
            if isinstance(value, dict):
                chapter = value.get("chapter_unit") or value.get("chapter") or value.get("unit")
            else:
                chapter = value
            if source and chapter:
                _add_source_mapping(mapping, str(source), str(chapter))
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            source = item.get("source_file") or item.get("source") or item.get("file")
            chapter = item.get("chapter_unit") or item.get("chapter") or item.get("unit")
            if source and chapter:
                _add_source_mapping(mapping, str(source), str(chapter))
    else:
        raise ValueError(f"Unsupported chapter dictionary format: {path}")
    return mapping


def _load_simple_yaml_mapping(path: Path) -> dict[str, dict[str, str]]:
    data: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if not raw_line.startswith((" ", "\t")) and raw_line.rstrip().endswith(":"):
            current = raw_line.rstrip()[:-1].strip().strip("'\"")
            data[current] = {}
        elif current and ":" in raw_line:
            key, value = raw_line.split(":", 1)
            data[current][key.strip()] = value.strip().strip("'\"")
    return data


def _add_source_mapping(mapping: dict[str, str], source: str, chapter: str) -> None:
    mapping[source] = chapter
    mapping[Path(source).name] = chapter
    mapping[source.replace("\\", "/")] = chapter


def source_values(node: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("source_file", "source_files", "sourceFile", "sourceFiles"):
        value = node.get(key)
        if isinstance(value, list):
            values.extend(str(v) for v in value if v)
        elif isinstance(value, str) and value:
            values.append(value)
    return values


def chapters_for_node(node: dict[str, Any], chapter_map: dict[str, str]) -> list[str]:
    chapters = []
    for source in source_values(node):
        chapter = chapter_map.get(source) or chapter_map.get(Path(source).name) or chapter_map.get(source.replace("\\", "/"))
        if chapter and chapter not in ("UNMATCHED", "SKIP"):
            chapters.append(chapter)
    return sorted(set(chapters))


def build_mock_nodes() -> list[dict[str, Any]]:
    specs = [
        ("n1", "密碼學", 1, "ch1.pdf"),
        ("n2", "資訊安全", 1, "ch1.pdf"),
        ("n3", "風險管理", 1, "ch1.pdf"),
        ("n4", "電子商務", 1, "ch2.pdf"),
        ("n5", "交易安全", 2, "ch2.pdf"),
        ("n6", "SSL", 2, "ch2.pdf"),
        ("n7", "資安政策", 2, "ch1.pdf"),
        ("n8", "門禁", 3, "ch3.pdf"),
        ("n9", "監視器", 3, "ch3.pdf"),
        ("n10", "支付閘道", 3, "ch2.pdf"),
    ]
    return [
        {
            "node_id": node_id,
            "name": name,
            "type": "concept",
            "community_id": normalize_cid(cid),
            "source_files": [source],
        }
        for node_id, name, cid, source in specs
    ]


def fetch_nodes_from_neo4j(uri: str, user: str, password: str) -> list[dict[str, Any]]:
    try:
        from neo4j import GraphDatabase
    except Exception as exc:
        raise RuntimeError("neo4j package is required for real Neo4j access; use --mock_neo4j for tests") from exc

    query = """
    MATCH (n:KGNode)
    WHERE n.communityId IS NOT NULL
    RETURN elementId(n) AS node_id,
           coalesce(n.name, n.id, n.title) AS name,
           n.type AS type,
           n.communityId AS community_id,
           n.communityFoundationRank AS community_foundation_rank,
           n.source_file AS source_file
    """
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            rows = session.run(query)
            return [dict(row) for row in rows]
    finally:
        driver.close()


def compute_dominant_chapter(nodes: list[dict[str, Any]], chapter_map: dict[str, str]) -> dict[str, Any]:
    community_totals: Counter[str] = Counter()
    chapter_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for node in nodes:
        cid = normalize_cid(node.get("community_id", node.get("communityId")))
        community_totals[cid] += 1
        chapters = chapters_for_node(node, chapter_map)
        for chapter in chapters:
            chapter_counts[cid][chapter] += 1

    communities = []
    ratios = []
    for cid in sorted(community_totals, key=cid_sort_key):
        total = community_totals[cid]
        counts = chapter_counts.get(cid, Counter())
        dominant_chapter, dominant_count = (None, 0)
        if counts:
            dominant_chapter, dominant_count = max(counts.items(), key=lambda item: (item[1], item[0]))
        ratio = dominant_count / total if total else 0.0
        ratios.append(ratio)
        communities.append(
            {
                "community_id": cid,
                "node_count": total,
                "chapter_counts": dict(sorted(counts.items())),
                "dominant_chapter": dominant_chapter,
                "dominant_count": dominant_count,
                "dominant_ratio": ratio,
            }
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metric": "dominant-chapter ratio",
        "summary": {
            "community_count": len(communities),
            "mean_dominant_ratio": mean(ratios) if ratios else None,
            "median_dominant_ratio": median(ratios) if ratios else None,
            "ge_70_count": sum(1 for ratio in ratios if ratio >= 0.70),
            "ge_70_ratio": (sum(1 for ratio in ratios if ratio >= 0.70) / len(ratios)) if ratios else None,
        },
        "communities": communities,
    }


def load_ccod_ranking(path: Path) -> dict[str, dict[str, Any]]:
    ranking: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = normalize_cid(row.get("cid") or row.get("community_id") or row.get("communityId"))
            if not cid:
                continue
            ranking[cid] = {
                "ccod": _to_float(row.get("ccod")),
                "rank": _to_int(row.get("rank")),
                "community_size": _to_int(row.get("community_size") or row.get("size")),
            }
    return ranking


def _to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def chapter_community_counts(nodes: list[dict[str, Any]], chapter_map: dict[str, str]) -> tuple[dict[str, Counter[str]], Counter[str], Counter[str]]:
    by_chapter: dict[str, Counter[str]] = defaultdict(Counter)
    community_sizes: Counter[str] = Counter()
    chapter_totals: Counter[str] = Counter()
    for node in nodes:
        cid = normalize_cid(node.get("community_id", node.get("communityId")))
        community_sizes[cid] += 1
        for chapter in chapters_for_node(node, chapter_map):
            by_chapter[chapter][cid] += 1
            chapter_totals[chapter] += 1
    return by_chapter, community_sizes, chapter_totals


def build_orders(community_sizes: Counter[str], ccod: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    cids = set(community_sizes) | set(ccod)
    size_desc = sorted(cids, key=lambda cid: (-community_sizes.get(cid, ccod.get(cid, {}).get("community_size") or 0), cid_sort_key(cid)))
    ccod_rank = sorted(
        cids,
        key=lambda cid: (
            ccod.get(cid, {}).get("rank") if ccod.get(cid, {}).get("rank") is not None else 10**9,
            -community_sizes.get(cid, 0),
            cid_sort_key(cid),
        ),
    )
    return {"size_desc": size_desc, "ccod_rank": ccod_rank}


def compute_topn_coverage(
    nodes: list[dict[str, Any]],
    chapter_map: dict[str, str],
    ccod: dict[str, dict[str, Any]],
    max_n: int = 10,
) -> dict[str, Any]:
    by_chapter, community_sizes, chapter_totals = chapter_community_counts(nodes, chapter_map)
    orders = build_orders(community_sizes, ccod)
    curves: dict[str, dict[str, Any]] = {}
    summary: dict[str, dict[str, float | None]] = {}

    for order_name, order in orders.items():
        per_n: dict[str, float] = {}
        per_chapter: dict[str, dict[str, float]] = {}
        for chapter in sorted(by_chapter):
            total = chapter_totals[chapter]
            per_chapter[chapter] = {}
            for n in range(1, max_n + 1):
                selected = set(order[:n])
                covered = sum(count for cid, count in by_chapter[chapter].items() if cid in selected)
                per_chapter[chapter][str(n)] = covered / total if total else 0.0
        for n in range(1, max_n + 1):
            vals = [chapter_curve[str(n)] for chapter_curve in per_chapter.values()]
            per_n[str(n)] = mean(vals) if vals else 0.0
        curves[order_name] = {"order": order, "average_curve": per_n, "per_chapter": per_chapter}
        summary[order_name] = {
            f"n{n}": per_n[str(n)] if str(n) in per_n else None
            for n in (1, 3, 5, 10)
        }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metric": "top-N community coverage",
        "max_n": max_n,
        "chapter_count": len(by_chapter),
        "summary": summary,
        "curves": curves,
    }


def write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_topn_plot(topn: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7.2, 4.2))
        styles = {
            "size_desc": {"color": "0.15", "marker": "o", "linestyle": "-"},
            "ccod_rank": {"color": "0.45", "marker": "s", "linestyle": "--"},
        }
        for name, curve_data in topn["curves"].items():
            curve = curve_data["average_curve"]
            xs = [int(k) for k in sorted(curve, key=lambda x: int(x))]
            ys = [curve[str(x)] for x in xs]
            ax.plot(xs, ys, linewidth=1.8, markersize=4.5, label=name, **styles.get(name, {}))
        ax.set_xlabel("Top-N communities")
        ax.set_ylabel("Average chapter coverage")
        ax.set_ylim(0, 1.05)
        ax.set_xticks(range(1, int(topn["max_n"]) + 1))
        ax.grid(True, axis="y", alpha=0.25)
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(path, dpi=180)
        plt.close(fig)
    except Exception:
        path.write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
                "0000000c4944415408d763f8ffff3f0005fe02fea73581e80000000049454e44ae426082"
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"))
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", ""))
    parser.add_argument("--chapter_dict", type=Path, required=True)
    parser.add_argument("--ccod_ranking", type=Path, required=True)
    parser.add_argument("--output_dominant", type=Path, required=True)
    parser.add_argument("--output_topn", type=Path, required=True)
    parser.add_argument("--output_plot", type=Path, required=True)
    parser.add_argument("--max_n", type=int, default=10)
    parser.add_argument("--mock_neo4j", action="store_true")
    args = parser.parse_args()

    chapter_map = load_chapter_dict(args.chapter_dict)
    ccod = load_ccod_ranking(args.ccod_ranking)
    nodes = build_mock_nodes() if args.mock_neo4j else fetch_nodes_from_neo4j(args.uri, args.user, args.password)
    dominant = compute_dominant_chapter(nodes, chapter_map)
    topn = compute_topn_coverage(nodes, chapter_map, ccod, max_n=args.max_n)
    write_json(dominant, args.output_dominant)
    write_json(topn, args.output_topn)
    write_topn_plot(topn, args.output_plot)
    print(f"wrote layer3 outputs to {args.output_dominant} and {args.output_topn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

