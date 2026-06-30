#!/usr/bin/env python3
import os

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
"""
Phase 1 Step 1.3: Build Post-validation Knowledge Graph
- 從 Validated/ 載入 5,486 筆（頂層欄位，Step 2 已正規化）
- Wipe Neo4j → MERGE（is_validated=true，含 reasoning）
- 計算結構指標 → post_validation_stats.json
- 備份 → phase1_backups/postvalidation_kg.json（MatchGPT 三組 threshold 之共用 restore 來源）
- 驗證備份完整性
"""

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

# ─── Paths ───────────────────────────────────────────────────────────────────
SCRIPT_DIR    = Path(__file__).resolve().parent
MATCHGPT_DIR  = SCRIPT_DIR.parent
BACKEND_DIR   = MATCHGPT_DIR.parents[1]
ETL_DIR       = BACKEND_DIR / "ETL_module"
VALIDATED_DIR = ETL_DIR / "Validated"
RESULTS_DIR   = MATCHGPT_DIR / "phase1_results"
BACKUPS_DIR   = MATCHGPT_DIR / "phase1_backups"

# ─── Neo4j ───────────────────────────────────────────────────────────────────
NEO4J_URI  = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = "neo4j"
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "")

BATCH_SIZE = 200


def load_validated_triples(directory: Path) -> list:
    """
    從 Validated/ 載入已過四步驟驗證之三元組（頂層欄位）。
    subject.name 已為 Step 2 正規化後的標準名稱（lowercase）。
    """
    triples = []
    for source_dir in sorted(directory.iterdir()):
        if not source_dir.is_dir():
            continue
        for chunk_file in sorted(source_dir.glob("chunk_*.json")):
            try:
                with open(chunk_file, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    continue
                triples.extend(data)
            except Exception as e:
                print(f"  [WARN] {chunk_file}: {e}")
    return triples


def wipe_neo4j(driver):
    print("  清空 Neo4j...")
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    print("  ✓ 清空完成")


def merge_triples(driver, triples: list) -> int:
    CYPHER = """
    UNWIND $batch AS row
    MERGE (s:Entity {name: row.s_name})
      ON CREATE SET s.type = row.s_type, s.display_name = row.s_display
    MERGE (o:Entity {name: row.o_name})
      ON CREATE SET o.type = row.o_type, o.display_name = row.o_display
    MERGE (s)-[r:RELATION {relation: row.relation}]->(o)
      ON CREATE SET r.source_file  = row.source_file,
                    r.source_id    = row.source_id,
                    r.source_index = row.source_index,
                    r.reasoning    = row.reasoning,
                    r.is_validated = true
    """
    rows = []
    for t in triples:
        subj = t.get("subject", {})
        obj  = t.get("object",  {})
        s_name = subj.get("name", "").strip()
        o_name = obj.get("name",  "").strip()
        if not s_name or not o_name:
            continue
        rows.append({
            "s_name":    s_name,
            "s_type":    subj.get("type", ""),
            "s_display": subj.get("display_name") or subj.get("name", s_name),
            "o_name":    o_name,
            "o_type":    obj.get("type", ""),
            "o_display": obj.get("display_name") or obj.get("name", o_name),
            "relation":  t.get("relation", ""),
            "source_file":  t.get("source_file", ""),
            "source_id":    t.get("source_id", ""),
            "source_index": t.get("source_index", 0),
            "reasoning":    t.get("reasoning", ""),
        })

    total = len(rows)
    with driver.session() as s:
        for i in range(0, total, BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            s.run(CYPHER, batch=batch)
            pct = min(i + BATCH_SIZE, total)
            print(f"  MERGE 進度：{pct}/{total}", end="\r")
    print(f"  ✓ MERGE 完成：{total} 筆有效三元組")
    return total


def compute_stats(driver) -> dict:
    stats = {}
    with driver.session() as s:
        stats["node_count"] = s.run(
            "MATCH (n) RETURN count(n) AS c"
        ).single()["c"]

        stats["rel_count"] = s.run(
            "MATCH ()-[r]->() RETURN count(r) AS c"
        ).single()["c"]

        stats["isolated_node_count"] = s.run(
            "MATCH (n) WHERE NOT (n)--() RETURN count(n) AS c"
        ).single()["c"]

        stats["avg_degree"] = round(
            (2 * stats["rel_count"]) / stats["node_count"]
            if stats["node_count"] > 0 else 0.0, 4
        )

        stats["isolated_ratio"] = round(
            stats["isolated_node_count"] / stats["node_count"]
            if stats["node_count"] > 0 else 0.0, 4
        )

        type_dist = {}
        for rec in s.run(
            "MATCH (n:Entity) RETURN n.type AS t, count(n) AS c ORDER BY c DESC"
        ):
            type_dist[rec["t"] or "unknown"] = rec["c"]
        stats["entity_type_distribution"] = type_dist

    gname = "wcc_postvalidation"
    try:
        with driver.session() as s:
            s.run(f"CALL gds.graph.drop('{gname}', false)")
            s.run(
                f"CALL gds.graph.project('{gname}', 'Entity', "
                f"{{RELATION: {{orientation: 'UNDIRECTED'}}}})"
            )
            stats["wcc_count"] = s.run(
                f"CALL gds.wcc.stats('{gname}') YIELD componentCount"
            ).single()["componentCount"]
            s.run(f"CALL gds.graph.drop('{gname}', false)")
    except Exception as e:
        stats["wcc_count"] = f"ERROR: {e}"

    gname2 = "leiden_postvalidation"
    try:
        with driver.session() as s:
            s.run(f"CALL gds.graph.drop('{gname2}', false)")
            s.run(
                f"CALL gds.graph.project('{gname2}', 'Entity', "
                f"{{RELATION: {{orientation: 'UNDIRECTED'}}}})"
            )
            stats["leiden_modularity_gamma1"] = round(
                s.run(
                    f"CALL gds.leiden.stats('{gname2}', {{gamma: 1.0}}) YIELD modularity"
                ).single()["modularity"], 6
            )
            s.run(f"CALL gds.graph.drop('{gname2}', false)")
    except Exception as e:
        stats["leiden_modularity_gamma1"] = f"ERROR: {e}"

    return stats


def do_backup_and_copy(dest_path: Path):
    result = subprocess.run(
        [sys.executable, str(MATCHGPT_DIR / "neo4j_backup_restore.py"), "backup"],
        capture_output=True, text=True, cwd=str(MATCHGPT_DIR)
    )
    print(result.stdout)
    if result.returncode != 0:
        print("[ERROR] backup 失敗：", result.stderr)
        sys.exit(1)

    pattern = re.compile(r"neo4j_backup_\d+_\d+\.json")
    backups = [f for f in MATCHGPT_DIR.iterdir()
               if f.is_file() and pattern.match(f.name)]
    latest = max(backups, key=lambda f: f.stat().st_mtime)
    shutil.copy2(str(latest), str(dest_path))
    print(f"  ✓ 備份已複製至：{dest_path}")


def verify_backup(backup_path: Path):
    result = subprocess.run(
        [sys.executable, str(MATCHGPT_DIR / "neo4j_backup_restore.py"),
         "verify", str(backup_path)],
        capture_output=True, text=True, cwd=str(MATCHGPT_DIR)
    )
    print(result.stdout)
    if result.returncode != 0:
        print("[ERROR] 驗證失敗：", result.stderr)
        sys.exit(1)


def main():
    print("=" * 60)
    print("Phase 1 Step 1.3: Build Post-validation Knowledge Graph")
    print("=" * 60)

    RESULTS_DIR.mkdir(exist_ok=True)
    BACKUPS_DIR.mkdir(exist_ok=True)

    # 1. 載入
    print("\n[1/6] 載入 Validated 三元組（頂層欄位，Step 2 已正規化）...")
    triples = load_validated_triples(VALIDATED_DIR)
    print(f"  載入：{len(triples)} 筆（預期 5,486）")

    # 2. 連接 Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    # 3. Wipe + MERGE
    print("\n[2/6] Wipe Neo4j...")
    wipe_neo4j(driver)

    print("\n[3/6] MERGE 三元組至 Neo4j...")
    merged_count = merge_triples(driver, triples)

    # 4. 計算指標
    print("\n[4/6] 計算結構指標...")
    stats = compute_stats(driver)
    stats["source"]          = "post_validation"
    stats["total_input_triples"] = len(triples)
    stats["merged_triples"]      = merged_count
    stats["timestamp"]       = datetime.now().isoformat()

    stats_path = RESULTS_DIR / "post_validation_stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 指標已儲存：{stats_path}")
    print(f"  節點：{stats['node_count']}　關係：{stats['rel_count']}")
    print(f"  WCC 數：{stats['wcc_count']}　孤立節點：{stats['isolated_node_count']}")
    print(f"  平均度：{stats['avg_degree']}　Leiden modularity：{stats['leiden_modularity_gamma1']}")

    driver.close()

    # 5. 備份（★ MatchGPT 三組 threshold 共用 restore 來源，極為重要）
    print("\n[5/6] 備份 Post-validation 圖譜（MatchGPT restore 來源）...")
    dest = BACKUPS_DIR / "postvalidation_kg.json"
    do_backup_and_copy(dest)

    # 6. 驗證備份完整性
    print("\n[6/6] 驗證備份完整性...")
    verify_backup(dest)

    print("\n✅ 步驟 1.3 完成！")
    print(f"   指標檔：{stats_path}")
    print(f"   備份檔：{dest}  ← MatchGPT 三組 threshold 共用 restore 來源")


if __name__ == "__main__":
    main()


