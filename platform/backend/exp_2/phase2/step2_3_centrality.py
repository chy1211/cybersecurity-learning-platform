#!/usr/bin/env python3
"""Phase 2 Step 2.3: Per-community centrality ranking with Neo4j GDS."""

from __future__ import annotations

import argparse
from pathlib import Path

from phase2_common import (
    DEFAULT_NEO4J_PASSWORD,
    DEFAULT_NEO4J_URI,
    DEFAULT_NEO4J_USER,
    batch_write,
    cid_sort_key,
    default_output_path,
    drop_gds_graph,
    open_driver,
    write_csv,
)


FIELDNAMES = ["cid", "metric", "rank", "node_name", "node_type", "score"]

# (metric_name, gds_procedure, rank_property, score_property)
# rank_property：社群內排名（1 = 最重要），供論文分析
# score_property：實際分數，供平台計算學習順序
METRICS = [
    ("out_degree", "gds.degree.stream",
     "outDegreeRank_inCommunity", "outDegree_inCommunity"),
    ("betweenness", "gds.betweenness.stream",
     "betweennessRank_inCommunity", "betweenness_inCommunity"),
    ("closeness", "gds.closeness.stream",
     "closenessRank_inCommunity", "closeness_inCommunity"),
]


def fetch_target_communities(session, min_size: int) -> list[dict]:
    result = session.run(
        """
        MATCH (n:KGNode)
        WHERE n.communityId IS NOT NULL
        WITH n.communityId AS cid, count(n) AS community_size
        WHERE community_size >= $minSize
        RETURN cid, community_size
        ORDER BY community_size DESC, cid
        """,
        minSize=min_size,
    )
    rows = [dict(record) for record in result]
    rows.sort(key=lambda row: (-row["community_size"], cid_sort_key(row["cid"])))
    return rows


def project_community_graph(session, graph_name: str, cid) -> dict:
    node_query = "MATCH (n:KGNode) WHERE n.communityId = $cid RETURN id(n) AS id"
    relationship_query = (
        "MATCH (a:KGNode)-[r]->(b:KGNode) "
        "WHERE a.communityId = $cid AND b.communityId = $cid "
        "RETURN id(a) AS source, id(b) AS target"
    )
    drop_gds_graph(session, graph_name)
    rec = session.run(
        """
        CALL gds.graph.project.cypher(
          $graphName,
          $nodeQuery,
          $relationshipQuery,
          {parameters: {cid: $cid}}
        )
        YIELD graphName, nodeCount, relationshipCount
        RETURN graphName, nodeCount, relationshipCount
        """,
        graphName=graph_name,
        nodeQuery=node_query,
        relationshipQuery=relationship_query,
        cid=cid,
    ).single()
    return dict(rec) if rec else {}


def stream_metric(session, graph_name: str, procedure_name: str) -> list[dict]:
    query = f"""
    CALL {procedure_name}($graphName)
    YIELD nodeId, score
    RETURN nodeId AS node_id,
           gds.util.asNode(nodeId).name AS node_name,
           gds.util.asNode(nodeId).type AS node_type,
           score
    """
    records = [dict(record) for record in session.run(query, graphName=graph_name)]
    records.sort(key=lambda row: (-(row.get("score") or 0.0), row.get("node_name") or ""))
    for index, row in enumerate(records, start=1):
        row["rank"] = index
    return records


def write_metric_ranks(session, rank_property: str, score_property: str,
                       records: list[dict]) -> int:
    """排名與分數同時寫回節點，平台可直接讀 score 排學習順序。"""
    valid_rank_props = {m[2] for m in METRICS}
    if rank_property not in valid_rank_props:
        raise ValueError(f"unsupported rank property: {rank_property}")
    cypher = f"""
    UNWIND $rows AS row
    MATCH (n)
    WHERE id(n) = row.node_id
    SET n.{rank_property}  = row.rank,
        n.{score_property} = row.score
    """
    rows = [{"node_id": row["node_id"],
             "rank":    row["rank"],
             "score":   round(float(row.get("score") or 0.0), 6)}
            for row in records]
    return batch_write(session, cypher, rows)


def execute(uri: str, user: str, password: str, min_size: int, output: str | Path) -> list[dict]:
    driver = open_driver(uri, user, password)
    csv_rows: list[dict] = []

    try:
        with driver.session() as session:
            communities = fetch_target_communities(session, min_size)
            if not communities:
                print(f"[WARN] 沒有規模 >= {min_size} 的社群，輸出空 CSV")
                write_csv(output, FIELDNAMES, csv_rows)
                return csv_rows

            for index, community in enumerate(communities, start=1):
                cid = community["cid"]
                graph_name = f"phase2_cent_{index}"
                print(f"[{index}/{len(communities)}] cid={cid}, size={community['community_size']}")
                try:
                    projection = project_community_graph(session, graph_name, cid)
                    if projection.get("nodeCount", 0) == 0:
                        print("  [WARN] empty projection, skipped")
                        continue

                    for metric_name, procedure_name, rank_prop, score_prop in METRICS:
                        records = stream_metric(session, graph_name, procedure_name)
                        write_metric_ranks(session, rank_prop, score_prop, records)
                        for row in records[:3]:
                            csv_rows.append(
                                {
                                    "cid": cid,
                                    "metric": metric_name,
                                    "rank": row["rank"],
                                    "node_name": row.get("node_name", ""),
                                    "node_type": row.get("node_type", ""),
                                    "score": row.get("score", 0.0),
                                }
                            )
                finally:
                    drop_gds_graph(session, graph_name)

        write_csv(output, FIELDNAMES, csv_rows)
    finally:
        driver.close()

    print(f"完成：{output} ({len(csv_rows)} top rows)")
    return csv_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--user", default=DEFAULT_NEO4J_USER)
    parser.add_argument("--password", default=DEFAULT_NEO4J_PASSWORD)
    parser.add_argument("--min_size", type=int, default=10)
    parser.add_argument(
        "--output",
        default=str(default_output_path("centrality_top3_by_community.csv")),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    execute(args.uri, args.user, args.password, args.min_size, args.output)


if __name__ == "__main__":
    main()
