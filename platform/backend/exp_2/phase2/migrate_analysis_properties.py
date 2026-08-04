#!/usr/bin/env python3
"""Safely preflight, apply, verify, or restore phase-2 analysis properties.

Dry-run is the default. Applying requires the exact confirmation token and creates
a JSON backup before invoking the authoritative step2_3 and step2_4 implementations.
This script is intentionally not run by the platform or by the clean-release build.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from phase2_common import DEFAULT_NEO4J_PASSWORD, DEFAULT_NEO4J_URI, DEFAULT_NEO4J_USER, open_driver
from step2_3_centrality import execute as execute_centrality
from step2_4_topo_layer import execute as execute_layers


PROPERTIES = (
    "outDegreeRank_inCommunity",
    "outDegree_inCommunity",
    "betweennessRank_inCommunity",
    "betweenness_inCommunity",
    "closenessRank_inCommunity",
    "closeness_inCommunity",
    "nodeLayerInCommunity",
    "nodeLayerInCommunity_dag",
)
APPLY_TOKEN = "APPLY_ANALYSIS_PROPERTIES"
RESTORE_TOKEN = "RESTORE_ANALYSIS_PROPERTIES"
REQUIRED_GDS_PROCEDURES = (
    "gds.graph.project.cypher",
    "gds.graph.drop",
    "gds.degree.stream",
    "gds.betweenness.stream",
    "gds.closeness.stream",
)


def require_confirmation(mode: str, token: str | None) -> None:
    expected = APPLY_TOKEN if mode == "apply" else RESTORE_TOKEN
    if token != expected:
        raise ValueError(f"{mode} requires --confirm {expected}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def coverage(session) -> dict:
    record = session.run(
        """
        MATCH (n:KGNode)
        WHERE n.communityId IS NOT NULL
        RETURN count(n) AS community_nodes,
               count(n.outDegree_inCommunity) AS out_degree,
               count(n.betweenness_inCommunity) AS betweenness,
               count(n.closeness_inCommunity) AS closeness,
               count(n.nodeLayerInCommunity) AS centrality_layer,
               count(n.nodeLayerInCommunity_dag) AS dag_layer
        """
    ).single()
    return {key: int(record[key] or 0) for key in record.keys()}


def gds_preflight(session) -> dict:
    version_record = session.run("RETURN gds.version() AS version").single()
    version = version_record["version"] if version_record else None
    required = list(REQUIRED_GDS_PROCEDURES)
    try:
        procedure_record = session.run(
            """
            SHOW PROCEDURES YIELD name
            WHERE name IN $required
            RETURN collect(name) AS names
            """,
            required=required,
        ).single()
    except Exception:
        procedure_record = session.run(
            """
            CALL dbms.procedures() YIELD name
            WHERE name IN $required
            RETURN collect(name) AS names
            """,
            required=required,
        ).single()
    available = set(procedure_record["names"] or []) if procedure_record else set()
    missing = sorted(set(required) - available)
    if not version or missing:
        raise RuntimeError(f"GDS preflight failed: version={version!r}, missing={missing}")
    return {
        "version": str(version),
        "required_procedures": required,
        "missing_procedures": missing,
    }


def ensure_clean_apply_state(before: dict) -> None:
    populated = {
        key: int(before.get(key) or 0)
        for key in ("out_degree", "betweenness", "closeness", "centrality_layer", "dag_layer")
        if int(before.get(key) or 0) > 0
    }
    if populated:
        raise RuntimeError(
            "analysis properties already exist; refusing repeated apply. "
            f"Restore or explicitly resolve the existing state first: {populated}"
        )


def validate_post_apply_coverage(after: dict, planned: dict) -> dict:
    expected = {
        "community_nodes": int(planned["all_nodes"]),
        "out_degree": int(planned["centrality_nodes"]),
        "betweenness": int(planned["centrality_nodes"]),
        "closeness": int(planned["centrality_nodes"]),
        "centrality_layer": int(planned["all_nodes"]),
        "dag_layer": int(planned["all_nodes"]),
    }
    mismatches = {
        key: {"expected": value, "actual": int(after.get(key) or 0)}
        for key, value in expected.items()
        if int(after.get(key) or 0) != value
    }
    if mismatches:
        raise RuntimeError(f"post-apply coverage mismatch: {mismatches}")
    return expected


def target_summary(session, min_size: int) -> dict:
    record = session.run(
        """
        MATCH (n:KGNode)
        WHERE n.communityId IS NOT NULL
        WITH n.communityId AS cid, count(n) AS size
        RETURN count(*) AS all_communities,
               sum(size) AS all_nodes,
               sum(CASE WHEN size >= $min_size THEN 1 ELSE 0 END) AS centrality_communities,
               sum(CASE WHEN size >= $min_size THEN size ELSE 0 END) AS centrality_nodes
        """,
        min_size=min_size,
    ).single()
    return {key: int(record[key] or 0) for key in record.keys()}


def backup_rows(session) -> list[dict]:
    result = session.run(
        """
        MATCH (n:KGNode)
        WHERE n.communityId IS NOT NULL
        RETURN elementId(n) AS element_id, n.name AS name, n.communityId AS communityId,
               n.outDegreeRank_inCommunity AS outDegreeRank_inCommunity,
               n.outDegree_inCommunity AS outDegree_inCommunity,
               n.betweennessRank_inCommunity AS betweennessRank_inCommunity,
               n.betweenness_inCommunity AS betweenness_inCommunity,
               n.closenessRank_inCommunity AS closenessRank_inCommunity,
               n.closeness_inCommunity AS closeness_inCommunity,
               n.nodeLayerInCommunity AS nodeLayerInCommunity,
               n.nodeLayerInCommunity_dag AS nodeLayerInCommunity_dag
        ORDER BY element_id
        """
    )
    return [dict(record) for record in result]


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def restore_rows(session, rows: list[dict]) -> int:
    result = session.run(
        """
        UNWIND $rows AS row
        MATCH (n:KGNode) WHERE elementId(n) = row.element_id
        SET n.outDegreeRank_inCommunity = row.outDegreeRank_inCommunity,
            n.outDegree_inCommunity = row.outDegree_inCommunity,
            n.betweennessRank_inCommunity = row.betweennessRank_inCommunity,
            n.betweenness_inCommunity = row.betweenness_inCommunity,
            n.closenessRank_inCommunity = row.closenessRank_inCommunity,
            n.closeness_inCommunity = row.closeness_inCommunity,
            n.nodeLayerInCommunity = row.nodeLayerInCommunity,
            n.nodeLayerInCommunity_dag = row.nodeLayerInCommunity_dag
        RETURN count(n) AS restored
        """,
        rows=rows,
    ).single()
    return int(result["restored"] or 0)


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--user", default=DEFAULT_NEO4J_USER)
    parser.add_argument("--password", default=DEFAULT_NEO4J_PASSWORD)
    parser.add_argument("--min-size", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=Path("_migration_output"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--restore", type=Path)
    parser.add_argument("--confirm")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    driver = open_driver(args.uri, args.user, args.password)
    backup_payload = None
    before = None
    planned = None
    try:
        with driver.session() as session:
            before = coverage(session)
            planned = target_summary(session, args.min_size)

            if args.restore:
                summary = {
                    "mode": "restore",
                    "before": before,
                    "planned": planned,
                }
                print(json.dumps(summary, ensure_ascii=False, indent=2))
                require_confirmation("restore", args.confirm)
                payload = json.loads(args.restore.read_text(encoding="utf-8"))
                restored = restore_rows(session, payload["nodes"])
                after = coverage(session)
                expected_before = payload.get("coverage_before")
                if restored != len(payload["nodes"]):
                    raise RuntimeError(f"restore node mismatch: {restored}/{len(payload['nodes'])}")
                if expected_before and after != expected_before:
                    raise RuntimeError(
                        f"restore coverage mismatch: expected={expected_before}, actual={after}"
                    )
                print(json.dumps({"restored": restored, "after": after}, ensure_ascii=False, indent=2))
                return 0

            gds = gds_preflight(session)
            summary = {
                "mode": "apply" if args.apply else "dry-run",
                "before": before,
                "planned": planned,
                "gds": gds,
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))

            if not args.apply:
                print(f"DRY_RUN_ONLY: use --apply --confirm {APPLY_TOKEN} to write")
                return 0

            require_confirmation("apply", args.confirm)
            ensure_clean_apply_state(before)
            run_id = timestamp()
            run_dir = args.output_dir / run_id
            backup_path = run_dir / "analysis_properties_before.json"
            backup_payload = {
                "schema_version": 1,
                "created_utc": run_id,
                "properties": list(PROPERTIES),
                "coverage_before": before,
                "nodes": backup_rows(session),
            }
            if len(backup_payload["nodes"]) != planned["all_nodes"]:
                raise RuntimeError(
                    "backup node count does not match planned community nodes: "
                    f"{len(backup_payload['nodes'])}/{planned['all_nodes']}"
                )
            write_json(backup_path, backup_payload)
            backup_hash = sha256_file(backup_path)

        centrality_csv = run_dir / "centrality_top3_by_community.csv"
        cycle_csv = run_dir / "cycle_edges_removed.csv"
        centrality_md = run_dir / "Topological_Stratification_Centrality.md"
        dag_md = run_dir / "Topological_Stratification_DirectedEdges.md"

        outputs = (centrality_csv, cycle_csv, centrality_md, dag_md)
        try:
            execute_centrality(args.uri, args.user, args.password, args.min_size, centrality_csv)
            execute_layers(args.uri, args.user, args.password, 3, cycle_csv, centrality_md, dag_md)
            with driver.session() as session:
                after = coverage(session)
            expected_coverage = validate_post_apply_coverage(after, planned)

            missing_outputs = [str(path) for path in outputs if not path.is_file()]
            if missing_outputs:
                raise RuntimeError(f"migration output files are missing: {missing_outputs}")
            manifest = {
                "schema_version": 2,
                "run_id": run_id,
                "parameters": {
                    "centrality_min_size": args.min_size,
                    "formal_layer_method": "centrality_layers",
                },
                "gds": gds,
                "coverage_before": before,
                "coverage_expected": expected_coverage,
                "coverage_after": after,
                "backup": {"path": str(backup_path), "sha256": backup_hash},
                "outputs": {str(path): sha256_file(path) for path in outputs},
                "restore_command": (
                    f"python migrate_analysis_properties.py --restore {backup_path} "
                    f"--confirm {RESTORE_TOKEN}"
                ),
            }
            write_json(run_dir / "migration_manifest.json", manifest)
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
            return 0
        except Exception as apply_error:
            restore_error = None
            restored = 0
            restored_coverage = None
            try:
                with driver.session() as session:
                    restored = restore_rows(session, backup_payload["nodes"])
                    restored_coverage = coverage(session)
                if restored != len(backup_payload["nodes"]) or restored_coverage != before:
                    raise RuntimeError(
                        "automatic restore verification failed: "
                        f"restored={restored}/{len(backup_payload['nodes'])}, "
                        f"coverage={restored_coverage}, expected={before}"
                    )
            except Exception as exc:
                restore_error = exc
            if restore_error is not None:
                raise RuntimeError(
                    f"apply failed and automatic restore also failed: {restore_error}"
                ) from apply_error
            raise RuntimeError(
                "apply failed; automatic restore succeeded and pre-apply coverage was recovered"
            ) from apply_error
    finally:
        driver.close()


if __name__ == "__main__":
    raise SystemExit(main())
