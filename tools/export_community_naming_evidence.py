#!/usr/bin/env python3
"""Export text-only evidence for community display-name review.

The script is read-only with respect to Neo4j. It never prints credentials and writes
JSON/Markdown evidence that can be reviewed without screenshots or GUI access.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase


TOOLS_DIR = Path(__file__).resolve().parent
HANDOFF_DIR = TOOLS_DIR.parent
PLATFORM_DIR = HANDOFF_DIR / "platform"
BACKEND_DIR = PLATFORM_DIR / "backend"
DEFAULT_NAMES = PLATFORM_DIR / "frontend" / "src" / "data" / "community-names-20260715.json"
DEFAULT_OUTPUT_DIR = HANDOFF_DIR / "analysis"


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--names", type=Path, default=DEFAULT_NAMES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=15)
    parser.add_argument(
        "--selection",
        choices=("all", "pending"),
        default="all",
        help="Review all named communities by default; use pending for placeholders only.",
    )
    return parser.parse_args(argv)


def normalize_source(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def load_target_ids(path: Path, selection: str = "all") -> tuple[dict, list[int]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    names = payload.get("names", {})
    if selection == "all":
        target_ids = sorted(int(cid) for cid in names)
    elif selection == "pending":
        target_ids = sorted(
            int(cid)
            for cid, name in names.items()
            if isinstance(name, str) and name.startswith("待人工確認")
        )
    else:
        raise ValueError(f"Unsupported selection: {selection}")
    return payload, target_ids


def fetch_community_evidence(session, community_id: int, top_n: int) -> dict:
    summary = session.run(
        """
        MATCH (n:KGNode)
        WHERE n.communityId = $community
        RETURN count(n) AS node_count,
               count(n.outDegree_inCommunity) AS analyzed_out_degree,
               count(n.betweenness_inCommunity) AS analyzed_betweenness,
               count(n.nodeLayerInCommunity) AS analyzed_layer
        """,
        community=community_id,
    ).single()

    top_nodes = [
        dict(record)
        for record in session.run(
            """
            MATCH (n:KGNode)
            WHERE n.communityId = $community
            OPTIONAL MATCH (n)-[out_rel]->(out_neighbor:KGNode)
              WHERE out_neighbor.communityId = $community
            WITH n, count(out_rel) AS live_out_degree
            OPTIONAL MATCH (in_neighbor:KGNode)-[in_rel]->(n)
              WHERE in_neighbor.communityId = $community
            RETURN n.name AS name,
                   n.type AS node_type,
                   live_out_degree,
                   count(in_rel) AS live_in_degree,
                   n.outDegree_inCommunity AS stored_out_degree,
                   n.betweenness_inCommunity AS stored_betweenness,
                   n.source_file AS source_file
            ORDER BY live_out_degree DESC, live_in_degree DESC, name
            LIMIT $top_n
            """,
            community=community_id,
            top_n=top_n,
        )
    ]
    for node in top_nodes:
        node["source_file"] = normalize_source(node.get("source_file"))

    relation_types = [
        dict(record)
        for record in session.run(
            """
            MATCH (a:KGNode)-[r]->(b:KGNode)
            WHERE a.communityId = $community AND b.communityId = $community
            RETURN type(r) AS relationship, count(*) AS count
            ORDER BY count DESC, relationship
            LIMIT $top_n
            """,
            community=community_id,
            top_n=top_n,
        )
    ]

    node_types = [
        dict(record)
        for record in session.run(
            """
            MATCH (n:KGNode)
            WHERE n.communityId = $community
            RETURN coalesce(n.type, '(missing)') AS node_type, count(*) AS count
            ORDER BY count DESC, node_type
            LIMIT $top_n
            """,
            community=community_id,
            top_n=top_n,
        )
    ]

    sources = Counter()
    all_names = []
    for record in session.run(
        """
        MATCH (n:KGNode)
        WHERE n.communityId = $community
        RETURN n.name AS name, n.source_file AS source_file
        ORDER BY name
        """,
        community=community_id,
    ):
        if record["name"]:
            all_names.append(str(record["name"]))
        sources.update(normalize_source(record["source_file"]))

    return {
        "community_id": community_id,
        "node_count": int(summary["node_count"] or 0) if summary else 0,
        "analysis_coverage": {
            "out_degree": int(summary["analyzed_out_degree"] or 0) if summary else 0,
            "betweenness": int(summary["analyzed_betweenness"] or 0) if summary else 0,
            "layer": int(summary["analyzed_layer"] or 0) if summary else 0,
        },
        "top_nodes": top_nodes,
        "relationship_types": relation_types,
        "node_types": node_types,
        "top_sources": [
            {"source": source, "count": count}
            for source, count in sources.most_common(top_n)
        ],
        "all_node_names": all_names,
        "suggested_name": None,
        "confidence": None,
        "rationale": None,
    }


def render_markdown(payload: dict) -> str:
    lines = [
        "# 分群命名文字證據",
        "",
        f"- 產生時間（UTC）：{payload['generated_utc']}",
        f"- 稽核分群數：{len(payload['communities'])}",
        "- 資料來源：現行 Neo4j，只讀查詢",
        "- 注意：此檔不以節點出度直接宣稱先備關係；僅供主題命名稽核。",
        "",
    ]
    for item in payload["communities"]:
        lines.extend([
            f"## 分群 {item['community_id']}（{item['node_count']} 節點）",
            "",
            "### 分析欄位覆蓋",
            "",
            f"- outDegree：{item['analysis_coverage']['out_degree']}",
            f"- betweenness：{item['analysis_coverage']['betweenness']}",
            f"- layer：{item['analysis_coverage']['layer']}",
            "",
            "### 高連結節點（即時計算分群內出入度）",
            "",
        ])
        for node in item["top_nodes"]:
            lines.append(
                f"- {node.get('name')}｜type={node.get('node_type')}｜"
                f"out={node.get('live_out_degree')}｜in={node.get('live_in_degree')}"
            )
        lines.extend(["", "### 關係類型", ""])
        for relation in item["relationship_types"]:
            lines.append(f"- {relation.get('relationship')}: {relation.get('count')}")
        lines.extend(["", "### 節點類型", ""])
        for node_type in item["node_types"]:
            lines.append(f"- {node_type.get('node_type')}: {node_type.get('count')}")
        lines.extend(["", "### 主要來源", ""])
        for source in item["top_sources"]:
            lines.append(f"- {source.get('source')}: {source.get('count')}")
        lines.extend([
            "",
            "### 命名結論",
            "",
            f"- 建議名稱：{item.get('suggested_name') or '尚未填寫'}",
            f"- 信心：{item.get('confidence') or '尚未填寫'}",
            f"- 理由：{item.get('rationale') or '尚未填寫'}",
            "",
        ])
    return "\n".join(lines)


def main(argv=None) -> int:
    args = parse_args(argv)
    load_dotenv(BACKEND_DIR / ".env")
    uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")

    _, target_ids = load_target_ids(args.names, args.selection)
    if not target_ids:
        raise RuntimeError(f"No community names matched selection={args.selection}")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            communities = [
                fetch_community_evidence(session, community_id, args.top_n)
                for community_id in target_ids
            ]
    finally:
        driver.close()

    payload = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_names_file": str(args.names),
        "selection": args.selection,
        "community_ids": target_ids,
        "communities": communities,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "community_naming_evidence_20260716.json"
    md_path = args.output_dir / "community_naming_evidence_20260716.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "selection": args.selection,
        "communities": len(target_ids),
        "json": str(json_path),
        "markdown": str(md_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
