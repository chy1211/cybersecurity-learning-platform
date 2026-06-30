#!/usr/bin/env python3
"""Phase 2 Step 2.2: Cross-community outgoing degree (CCOD) ranking."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from phase2_common import (
    DEFAULT_NEO4J_PASSWORD,
    DEFAULT_NEO4J_URI,
    DEFAULT_NEO4J_USER,
    batch_write,
    cid_sort_key,
    default_output_path,
    now_iso,
    open_driver,
    write_csv,
)


FIELDNAMES = ["cid", "ccod", "rank", "community_size"]


def build_ccod_ranking(cross_edges: list[dict], community_sizes: dict) -> list[dict]:
    ccod_by_cid = defaultdict(int)
    for edge in cross_edges:
        source_cid = edge.get("source_cid")
        if source_cid is None:
            continue
        ccod_by_cid[source_cid] += int(edge.get("count", 1) or 0)

    rows = []
    for cid, size in community_sizes.items():
        rows.append(
            {
                "cid": cid,
                "ccod": int(ccod_by_cid.get(cid, 0)),
                "community_size": int(size),
            }
        )

    rows.sort(key=lambda row: (-row["ccod"], cid_sort_key(row["cid"])))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def fetch_community_sizes(session) -> dict:
    result = session.run(
        """
        MATCH (n:KGNode)
        WHERE n.communityId IS NOT NULL
        RETURN n.communityId AS cid, count(n) AS community_size
        ORDER BY cid
        """
    )
    return {record["cid"]: int(record["community_size"]) for record in result}


def fetch_cross_edges(session) -> list[dict]:
    result = session.run(
        """
        MATCH (a:KGNode)-[r]->(b:KGNode)
        WHERE a.communityId IS NOT NULL
          AND b.communityId IS NOT NULL
          AND a.communityId <> b.communityId
        RETURN a.communityId AS source_cid,
               b.communityId AS target_cid,
               count(r) AS count
        ORDER BY source_cid, target_cid
        """
    )
    return [dict(record) for record in result]


def write_rank_properties(session, rows: list[dict]) -> int:
    cypher = """
    UNWIND $rows AS row
    MATCH (n:KGNode)
    WHERE n.communityId = row.cid
    SET n.communityCCOD = row.ccod,
        n.communityFoundationRank = row.rank
    """
    return batch_write(session, cypher, rows)


def execute(uri: str, user: str, password: str, output: str | Path) -> list[dict]:
    driver = open_driver(uri, user, password)
    try:
        with driver.session() as session:
            print("[1/4] 讀取 community size...")
            community_sizes = fetch_community_sizes(session)
            if not community_sizes:
                print("  [WARN] 找不到 communityId，請先執行 step2_1_leiden.py")

            print("[2/4] 聚合跨社群有向邊...")
            cross_edges = fetch_cross_edges(session)

            print("[3/4] 建立 CCOD 排名...")
            rows = build_ccod_ranking(cross_edges, community_sizes)
            write_csv(output, FIELDNAMES, rows)

            print("[4/4] 寫回 communityCCOD / communityFoundationRank...")
            written_batches = write_rank_properties(session, rows)
            print(f"  updated community rows: {written_batches}")

    finally:
        driver.close()

    print(f"完成：{output} ({len(rows)} communities, {now_iso()})")
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--user", default=DEFAULT_NEO4J_USER)
    parser.add_argument("--password", default=DEFAULT_NEO4J_PASSWORD)
    parser.add_argument("--output", default=str(default_output_path("ccod_ranking.csv")))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    execute(args.uri, args.user, args.password, args.output)


if __name__ == "__main__":
    main()
