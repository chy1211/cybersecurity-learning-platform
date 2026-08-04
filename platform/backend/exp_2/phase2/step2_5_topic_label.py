#!/usr/bin/env python3
"""
Phase 2 Step 2.5: 社群組成匯出（論文附錄用）

設計決定（2026-05-20）：
  不進行人工社群命名，避免主觀命名。
  社群以 ID + Top 節點呈現。

輸出：
  community_composition.csv  — 各社群的節點組成與中心性排名，供論文表 4-3 與附錄

（若未來需要命名，可在此 CSV 增加 assigned_name 欄後重跑 import 模式）
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from phase2_common import (
    DEFAULT_NEO4J_PASSWORD,
    DEFAULT_NEO4J_URI,
    DEFAULT_NEO4J_USER,
    cid_sort_key,
    default_output_path,
    open_driver,
    write_csv,
)

FIELDNAMES = [
    "cid", "community_size", "ccod_rank", "ccod",
    "top3_nodes", "top10_nodes",
    "layer_count",          # Centrality 方法的分層數
    "layer_count_dag",      # DAG 方法的分層數（比較用）
]


def fetch_community_data(session) -> list[dict]:
    """
    取得每個社群的組成資訊：
    - 節點依 outDegree_inCommunity 降冪排列（=中心性方法的先修順序）
    - ccod_rank / ccod 來自步驟 2.2
    - layer_count 來自步驟 2.4（Centrality 方法）
    """
    result = session.run("""
        MATCH (n:KGNode)
        WHERE n.communityId IS NOT NULL
        WITH n.communityId AS cid,
             collect(n) AS nodes,
             count(n) AS sz
        RETURN cid, sz,
               [nd IN nodes | {
                 name:     nd.name,
                 out_deg:  coalesce(nd.outDegree_inCommunity, 0),
                 layer:    coalesce(nd.nodeLayerInCommunity, 0),
                 dag_layer: coalesce(nd.nodeLayerInCommunity_dag, 0),
                 ccod_rank: coalesce(nd.communityFoundationRank, 9999),
                 ccod:     coalesce(nd.communityCCOD, 0)
               }] AS node_data
        ORDER BY sz DESC, cid
    """)

    rows = []
    for rec in result:
        cid       = rec["cid"]
        sz        = int(rec["sz"])
        nd_list   = rec["node_data"]

        # 依出度排序（降冪）
        nd_sorted = sorted(nd_list,
                           key=lambda x: (-x["out_deg"], x["name"] or ""))

        names     = [n["name"] for n in nd_sorted if n["name"]]
        top3      = ", ".join(names[:3])
        top10     = ", ".join(names[:10])

        # CCOD 從第一個節點取（同社群的 ccod_rank 值都一樣）
        ccod_rank = nd_sorted[0]["ccod_rank"] if nd_sorted else 9999
        ccod      = nd_sorted[0]["ccod"]      if nd_sorted else 0

        # 分層數
        layers      = {n["layer"]     for n in nd_list}
        layers_dag  = {n["dag_layer"] for n in nd_list}

        rows.append({
            "cid":            cid,
            "community_size": sz,
            "ccod_rank":      ccod_rank,
            "ccod":           ccod,
            "top3_nodes":     top3,
            "top10_nodes":    top10,
            "layer_count":    len(layers),
            "layer_count_dag": len(layers_dag),
        })

    rows.sort(key=lambda r: cid_sort_key(r["cid"]))
    return rows


def execute(uri: str, user: str, password: str, output: Path) -> list[dict]:
    driver = open_driver(uri, user, password)
    try:
        with driver.session() as session:
            print("擷取社群組成資料...")
            rows = fetch_community_data(session)
    finally:
        driver.close()

    write_csv(output, FIELDNAMES, rows)
    print(f"✅ 社群組成 CSV → {output}")
    print(f"   社群數：{len(rows)}")
    if rows:
        sizes = [r["community_size"] for r in rows]
        print(f"   規模範圍：{min(sizes)} ~ {max(sizes)}")
        print(f"   Top-5 社群（依規模）：")
        for r in sorted(rows, key=lambda x: -x["community_size"])[:5]:
            print(f"     cid={r['cid']}  size={r['community_size']}  "
                  f"ccod_rank={r['ccod_rank']}  top3=【{r['top3_nodes']}】")
    return rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--uri",      default=DEFAULT_NEO4J_URI)
    p.add_argument("--user",     default=DEFAULT_NEO4J_USER)
    p.add_argument("--password", default=DEFAULT_NEO4J_PASSWORD)
    p.add_argument("--output",
                   default=str(default_output_path("community_composition.csv")))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    execute(args.uri, args.user, args.password, Path(args.output))


if __name__ == "__main__":
    main()
