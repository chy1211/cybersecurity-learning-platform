#!/usr/bin/env python3
"""Verify that the local Neo4j environment can host the platform graph.

Checks, in order:
  1. Java runtime version (Neo4j 5.26 LTS requires Java 17 or 21)
  2. Bolt connectivity and authentication
  3. Neo4j kernel edition/version
  4. APOC availability (the platform's Cypher uses apoc.meta.cypher.type)
  5. GDS availability and version compatibility with the running kernel
  6. Graph contents against the published snapshot (nodes/relationships/communities)

Exit code is 0 only when every required check passes.

Usage:
    python tools/check_neo4j_env.py
    python tools/check_neo4j_env.py --uri bolt://127.0.0.1:7687 --user neo4j
Credentials are read from NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD when not given.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO_ROOT / "data" / "kg_snapshot" / "platform_kg.json"
GDS_VERSIONS_URL = "https://graphdatascience.ninja/versions.json"

SUPPORTED_JAVA = (17, 21)
EXPECTED_NODES = 2763
EXPECTED_RELS = 3803

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))
    print(f"[{status:4}] {name}: {detail}")


def check_java() -> None:
    try:
        proc = subprocess.run(["java", "-version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        record(FAIL, "java", f"could not run 'java -version' ({exc})")
        return
    output = (proc.stderr or "") + (proc.stdout or "")
    match = re.search(r'version "(\d+)', output)
    if not match:
        record(WARN, "java", "found java but could not parse its version")
        return
    major = int(match.group(1))
    if major in SUPPORTED_JAVA:
        record(PASS, "java", f"version {major} (supported by Neo4j 5.26 LTS)")
    else:
        record(FAIL, "java", f"version {major}; Neo4j 5.26 LTS needs Java {' or '.join(map(str, SUPPORTED_JAVA))}")


def gds_expected_for(neo4j_version: str) -> str | None:
    """Look up the GDS build that matches this exact Neo4j patch release.

    GDS is pinned per Neo4j patch version. Installing the newest 2.x against an
    older kernel fails at runtime with ClassNotFoundException rather than at
    startup, so this mapping is worth checking explicitly.
    """
    try:
        with urllib.request.urlopen(GDS_VERSIONS_URL, timeout=30) as resp:
            entries = json.loads(resp.read().decode())
    except Exception:
        return None
    for entry in entries:
        if entry.get("neo4j") == neo4j_version:
            return entry.get("version")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", ""))
    parser.add_argument("--skip-graph", action="store_true",
                       help="only check the server and plugins, not the graph contents")
    args = parser.parse_args()

    check_java()

    try:
        from neo4j import GraphDatabase
    except ImportError:
        record(FAIL, "driver", "python package 'neo4j' is not installed "
                               "(pip install -r CybersecurityLearningPlatform/backend/requirements-platform.txt)")
        return 1

    if not args.password:
        record(FAIL, "credentials", "no password given; set NEO4J_PASSWORD or pass --password")
        return 1

    try:
        driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
        driver.verify_connectivity()
        record(PASS, "bolt", f"connected to {args.uri}")
    except Exception as exc:
        record(FAIL, "bolt", f"cannot connect to {args.uri}: {type(exc).__name__}")
        return 1

    neo4j_version = None
    try:
        with driver.session() as session:
            row = session.run(
                "CALL dbms.components() YIELD name, versions, edition "
                "RETURN versions[0] AS version, edition LIMIT 1"
            ).single()
            neo4j_version = row["version"]
            record(PASS, "neo4j", f"{neo4j_version} ({row['edition']})")

            try:
                apoc = session.run("RETURN apoc.version() AS v").single()["v"]
                record(PASS, "apoc", f"{apoc} (required by platform Cypher)")
            except Exception:
                record(FAIL, "apoc", "not available; platform queries use apoc.meta.cypher.type")

            try:
                gds = session.run("RETURN gds.version() AS v").single()["v"]
                expected = gds_expected_for(neo4j_version)
                if expected is None:
                    record(WARN, "gds", f"{gds} installed; could not reach {GDS_VERSIONS_URL} to verify pairing")
                elif gds == expected:
                    record(PASS, "gds", f"{gds} matches the build published for Neo4j {neo4j_version}")
                else:
                    record(FAIL, "gds", f"{gds} installed but Neo4j {neo4j_version} expects {expected}; "
                                        f"a mismatched build fails at call time")
            except Exception:
                record(WARN, "gds", "not available; only experiment 2 (Leiden) needs it")

            if not args.skip_graph:
                counts = session.run(
                    "MATCH (n) WITH count(n) AS nodes "
                    "MATCH ()-[r]->() "
                    "RETURN nodes, count(r) AS rels"
                ).single()
                nodes, rels = counts["nodes"], counts["rels"]
                if (nodes, rels) == (EXPECTED_NODES, EXPECTED_RELS):
                    record(PASS, "graph", f"{nodes} nodes / {rels} relationships (matches published snapshot)")
                elif nodes == 0:
                    record(FAIL, "graph", "database is empty; restore data/kg_snapshot/platform_kg.json")
                else:
                    record(WARN, "graph", f"{nodes} nodes / {rels} relationships; "
                                          f"snapshot has {EXPECTED_NODES}/{EXPECTED_RELS}")

                typed = session.run(
                    "MATCH (n) WHERE n.type IS NOT NULL RETURN count(n) AS c"
                ).single()["c"]
                if typed:
                    record(PASS, "node types", f"{typed} nodes carry n.type "
                                               "(the platform colours and groups by this property)")
                else:
                    record(WARN, "node types", "no n.type property found; platform views will fall back to defaults")

                communities = session.run(
                    "MATCH (n) WHERE n.communityId IS NOT NULL "
                    "RETURN count(n) AS c, count(DISTINCT n.communityId) AS d"
                ).single()
                record(PASS if communities["c"] else WARN, "communities",
                       f"{communities['c']} nodes in {communities['d']} communities")
    finally:
        driver.close()

    if SNAPSHOT.exists():
        record(PASS, "snapshot", f"found {SNAPSHOT.relative_to(REPO_ROOT)}")
    else:
        record(WARN, "snapshot", f"missing {SNAPSHOT.relative_to(REPO_ROOT)}")

    failures = [r for r in results if r[0] == FAIL]
    print()
    print(f"{len(results)} checks: "
          f"{sum(1 for r in results if r[0] == PASS)} pass, "
          f"{sum(1 for r in results if r[0] == WARN)} warn, {len(failures)} fail")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
