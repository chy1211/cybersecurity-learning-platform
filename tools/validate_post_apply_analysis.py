from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path


HANDOFF_ROOT = Path(__file__).resolve().parents[1]
PHASE2_DIR = (
    HANDOFF_ROOT
    / "CybersecurityLearningPlatform"
    / "backend"
    / "exp_2"
    / "phase2"
)
sys.path.insert(0, str(PHASE2_DIR))

from phase2_common import (  # noqa: E402
    DEFAULT_NEO4J_PASSWORD,
    DEFAULT_NEO4J_URI,
    DEFAULT_NEO4J_USER,
    open_driver,
)


DEFAULT_JSON = HANDOFF_ROOT / "analysis" / "post_apply_analysis_validation_20260716.json"
DEFAULT_MD = HANDOFF_ROOT / "analysis" / "post_apply_analysis_validation_20260716.md"
SCORE_RANK_PAIRS = (
    ("outDegree_inCommunity", "outDegreeRank_inCommunity"),
    ("betweenness_inCommunity", "betweennessRank_inCommunity"),
    ("closeness_inCommunity", "closenessRank_inCommunity"),
)
LAYER_FIELDS = ("nodeLayerInCommunity", "nodeLayerInCommunity_dag")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _cid_key(value):
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


def fetch_rows(session) -> list[dict]:
    result = session.run(
        """
        MATCH (n:KGNode)
        WHERE n.communityId IS NOT NULL
        OPTIONAL MATCH (n)-[r]->(b:KGNode)
          WHERE b.communityId = n.communityId
        RETURN elementId(n) AS element_id,
               n.name AS name,
               n.communityId AS communityId,
               count(r) AS live_out_degree,
               n.outDegree_inCommunity AS outDegree_inCommunity,
               n.outDegreeRank_inCommunity AS outDegreeRank_inCommunity,
               n.betweenness_inCommunity AS betweenness_inCommunity,
               n.betweennessRank_inCommunity AS betweennessRank_inCommunity,
               n.closeness_inCommunity AS closeness_inCommunity,
               n.closenessRank_inCommunity AS closenessRank_inCommunity,
               n.nodeLayerInCommunity AS nodeLayerInCommunity,
               n.nodeLayerInCommunity_dag AS nodeLayerInCommunity_dag
        ORDER BY communityId, name, element_id
        """
    )
    return [dict(record) for record in result]


def coverage(rows: list[dict]) -> dict:
    return {
        "community_nodes": len(rows),
        "out_degree": sum(row["outDegree_inCommunity"] is not None for row in rows),
        "betweenness": sum(row["betweenness_inCommunity"] is not None for row in rows),
        "closeness": sum(row["closeness_inCommunity"] is not None for row in rows),
        "centrality_layer": sum(row["nodeLayerInCommunity"] is not None for row in rows),
        "dag_layer": sum(row["nodeLayerInCommunity_dag"] is not None for row in rows),
    }


def validate_rows(rows: list[dict]) -> dict:
    communities: dict[object, list[dict]] = defaultdict(list)
    for row in rows:
        communities[row["communityId"]].append(row)

    invalid_numeric_count = 0
    negative_value_count = 0
    non_integer_layer_count = 0
    stored_vs_live_outdegree_mismatch_count = 0
    score_rank_pair_mismatch_count = 0

    numeric_fields = [item for pair in SCORE_RANK_PAIRS for item in pair] + list(LAYER_FIELDS)
    for row in rows:
        for field in numeric_fields:
            value = row[field]
            if value is None:
                continue
            if not _is_number(value):
                invalid_numeric_count += 1
                continue
            if value < 0:
                negative_value_count += 1
        for field in LAYER_FIELDS:
            value = row[field]
            if value is not None and (not _is_number(value) or int(value) != value):
                non_integer_layer_count += 1
        stored = row["outDegree_inCommunity"]
        if stored is not None and (
            not _is_number(stored) or float(stored) != float(row["live_out_degree"])
        ):
            stored_vs_live_outdegree_mismatch_count += 1
        for score_field, rank_field in SCORE_RANK_PAIRS:
            if (row[score_field] is None) != (row[rank_field] is None):
                score_rank_pair_mismatch_count += 1

    layer_start_error_count = 0
    layer_gap_count = 0
    layer_degree_conflict_count = 0
    rank_range_error_count = 0

    for community_rows in communities.values():
        community_size = len(community_rows)
        for layer_field in LAYER_FIELDS:
            values = [row[layer_field] for row in community_rows if row[layer_field] is not None]
            if not values or any(not _is_number(value) or int(value) != value for value in values):
                continue
            layers = sorted({int(value) for value in values})
            if layers[0] != 0:
                layer_start_error_count += 1
            if layers != list(range(layers[-1] + 1)):
                layer_gap_count += 1

        by_layer: dict[int, set[int]] = defaultdict(set)
        for row in community_rows:
            layer = row["nodeLayerInCommunity"]
            if layer is not None and _is_number(layer) and int(layer) == layer:
                by_layer[int(layer)].add(int(row["live_out_degree"]))
        for degrees in by_layer.values():
            if len(degrees) != 1:
                layer_degree_conflict_count += 1
        ordered = sorted((layer, next(iter(degrees))) for layer, degrees in by_layer.items() if len(degrees) == 1)
        for (_, earlier_degree), (_, later_degree) in zip(ordered, ordered[1:]):
            if earlier_degree < later_degree:
                layer_degree_conflict_count += 1

        for _, rank_field in SCORE_RANK_PAIRS:
            ranks = [row[rank_field] for row in community_rows if row[rank_field] is not None]
            if not ranks:
                continue
            valid_ranks = all(_is_number(rank) and int(rank) == rank for rank in ranks)
            if not valid_ranks:
                rank_range_error_count += 1
                continue
            integer_ranks = sorted(int(rank) for rank in ranks)
            if (
                integer_ranks[0] != 1
                or integer_ranks[-1] > community_size
                or integer_ranks != list(range(1, len(integer_ranks) + 1))
            ):
                rank_range_error_count += 1

    return {
        "invalid_numeric_count": invalid_numeric_count,
        "negative_value_count": negative_value_count,
        "non_integer_layer_count": non_integer_layer_count,
        "layer_start_error_count": layer_start_error_count,
        "layer_gap_count": layer_gap_count,
        "layer_degree_conflict_count": layer_degree_conflict_count,
        "stored_vs_live_outdegree_mismatch_count": stored_vs_live_outdegree_mismatch_count,
        "rank_range_error_count": rank_range_error_count,
        "score_rank_pair_mismatch_count": score_rank_pair_mismatch_count,
    }


def _cycle_community(path: Path | None):
    if path is None or not path.is_file():
        return None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        first = next(csv.DictReader(handle), None)
    if not first:
        return None
    text = str(first.get("cid", "")).strip()
    try:
        numeric = float(text)
        return int(numeric) if numeric.is_integer() else numeric
    except ValueError:
        return text


def build_samples(rows: list[dict], cycle_csv: Path | None) -> dict:
    communities: dict[object, list[dict]] = defaultdict(list)
    for row in rows:
        communities[row["communityId"]].append(row)
    ordered = sorted(communities, key=lambda cid: (-len(communities[cid]), _cid_key(cid)))
    count = len(ordered)
    large = ordered[:3]
    centrality_sized = [cid for cid in ordered if len(communities[cid]) >= 10]
    middle_start = max(0, len(centrality_sized) // 2 - 1)
    medium = centrality_sized[middle_start : middle_start + 3]
    small = ordered[-3:]
    cycle = _cycle_community(cycle_csv)
    zero_degree = next(
        (cid for cid in reversed(ordered) if all(row["live_out_degree"] == 0 for row in communities[cid])),
        None,
    )

    selections = {
        "large": large,
        "medium": medium,
        "small": small,
        "cycle_edge_removed": [cycle] if cycle in communities else [],
        "all_live_outdegree_zero": [zero_degree] if zero_degree is not None else [],
    }
    samples = {}
    for category, cids in selections.items():
        category_rows = []
        for cid in cids:
            selected = sorted(
                communities[cid],
                key=lambda row: (-row["live_out_degree"], str(row["name"]), row["element_id"]),
            )[:3]
            for row in selected:
                category_rows.append(
                    {
                        "name": row["name"],
                        "communityId": row["communityId"],
                        "community_size": len(communities[cid]),
                        "stored_out_degree": row["outDegree_inCommunity"],
                        "live_out_degree": row["live_out_degree"],
                        "centrality_layer": row["nodeLayerInCommunity"],
                        "dag_layer": row["nodeLayerInCommunity_dag"],
                        "out_degree_rank": row["outDegreeRank_inCommunity"],
                        "betweenness_rank": row["betweennessRank_inCommunity"],
                        "betweenness_score": row["betweenness_inCommunity"],
                        "closeness_rank": row["closenessRank_inCommunity"],
                        "closeness_score": row["closeness_inCommunity"],
                    }
                )
        samples[category] = category_rows
    return samples


def select_api_targets(rows: list[dict]) -> dict:
    communities: dict[object, list[dict]] = defaultdict(list)
    for row in rows:
        communities[row["communityId"]].append(row)

    complete = [
        row
        for community_rows in communities.values()
        if all(item["outDegree_inCommunity"] is not None for item in community_rows)
        for row in community_rows
    ]
    unavailable = [
        row
        for community_rows in communities.values()
        if all(item["outDegree_inCommunity"] is None for item in community_rows)
        for row in community_rows
    ]

    def choose(candidates: list[dict]):
        ordered = sorted(
            candidates,
            key=lambda row: (
                re.fullmatch(r"[A-Za-z][A-Za-z0-9 ._()+/#-]{2,}", str(row["name"] or "")) is None,
                -len(communities[row["communityId"]]),
                str(row["name"]),
            ),
        )
        row = ordered[0]
        community_rows = communities[row["communityId"]]
        analyzed = sum(item["outDegree_inCommunity"] is not None for item in community_rows)
        return {
            "name": row["name"],
            "communityId": row["communityId"],
            "analysis_node_count": analyzed,
            "community_node_count": len(community_rows),
            "analysis_state": "complete" if analyzed == len(community_rows) else "unavailable",
        }

    return {"analyzed": choose(complete), "unanalyzed": choose(unavailable)}


def write_outputs(payload: dict, json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Neo4j analysis properties post-apply validation",
        "",
        f"- status: `{payload['status']}`",
        f"- coverage: `{json.dumps(payload['coverage'], ensure_ascii=False)}`",
        f"- remaining phase2 GDS projections: `{payload['remaining_gds_projection_count']}`",
        "",
        "## Error and mismatch counts",
        "",
    ]
    for key in (
        "invalid_numeric_count",
        "negative_value_count",
        "non_integer_layer_count",
        "layer_start_error_count",
        "layer_gap_count",
        "layer_degree_conflict_count",
        "stored_vs_live_outdegree_mismatch_count",
        "rank_range_error_count",
        "score_rank_pair_mismatch_count",
    ):
        lines.append(f"- {key}: `{payload[key]}`")
    lines.extend(["", "## Samples", ""])
    for category, rows in payload["samples"].items():
        lines.append(f"### {category}")
        lines.append("")
        if not rows:
            lines.append("- No matching community exists.")
        for row in rows:
            lines.append(
                "- "
                f"{row['name']} | cid={row['communityId']} | size={row['community_size']} | "
                f"stored/live OD={row['stored_out_degree']}/{row['live_out_degree']} | "
                f"centrality/DAG layer={row['centrality_layer']}/{row['dag_layer']} | "
                f"OD rank={row['out_degree_rank']} | "
                f"betweenness={row['betweenness_score']} (rank {row['betweenness_rank']}) | "
                f"closeness={row['closeness_score']} (rank {row['closeness_rank']})"
            )
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only validation of migrated Neo4j analysis properties.")
    parser.add_argument("--uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--user", default=DEFAULT_NEO4J_USER)
    parser.add_argument("--password", default=DEFAULT_NEO4J_PASSWORD)
    parser.add_argument("--cycle-csv", type=Path)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--md-output", type=Path, default=DEFAULT_MD)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    driver = open_driver(args.uri, args.user, args.password)
    try:
        with driver.session() as session:
            rows = fetch_rows(session)
            projection_record = session.run(
                """
                CALL gds.graph.list()
                YIELD graphName
                WHERE graphName STARTS WITH 'phase2_cent_'
                RETURN count(*) AS remaining, collect(graphName) AS names
                """
            ).single()
    finally:
        driver.close()

    result = validate_rows(rows)
    result["coverage"] = coverage(rows)
    result["remaining_gds_projection_count"] = int(projection_record["remaining"] or 0)
    result["remaining_gds_projection_names"] = list(projection_record["names"] or [])
    result["samples"] = build_samples(rows, args.cycle_csv)
    result["api_targets"] = select_api_targets(rows)
    error_keys = [key for key in result if key.endswith("_count")]
    result["status"] = "PASS" if all(result[key] == 0 for key in error_keys) else "FAIL"
    write_outputs(result, args.json_output, args.md_output)
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, ensure_ascii=False, indent=2))
    print(f"json_output={args.json_output}")
    print(f"md_output={args.md_output}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
