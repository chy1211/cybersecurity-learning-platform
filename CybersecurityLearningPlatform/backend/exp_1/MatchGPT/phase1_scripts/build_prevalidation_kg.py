#!/usr/bin/env python3
"""
Phase 1 Step 1.2: Build Pre-validation Knowledge Graph
- 從 Validated/ + Rejected/ 載入 original_raw_triple（共 5,593 筆）
- 僅做 normalize_entity_name（strip+lower）
- Wipe Neo4j → MERGE 全部三元組（is_validated=false）
- 計算結構指標 → pre_validation_stats.json
- 備份 → phase1_backups/prevalidation_kg.json
"""

import json
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
REJECTED_DIR  = ETL_DIR / "Rejected"
RESULTS_DIR   = MATCHGPT_DIR / "phase1_results"
BACKUPS_DIR   = MATCHGPT_DIR / "phase1_backups"

# ─── Neo4j ───────────────────────────────────────────────────────────────────
NEO4J_URI  = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = "neo4j"
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "")

BATCH_SIZE = 200  # MERGE 批次大小


def normalize_entity_name(name: str) -> str:
    """沿用 03_validate_and_import_fixed.py 之邏輯：strip + lower。"""
    return name.strip().lower()


def load_triples_from_dir(directory: Path) -> list:
    """
    從目錄樹中所有 chunk_*.json 載入三元組，使用 original_raw_triple 欄位。
    若 original_raw_triple 不存在則退而用頂層欄位（相容性 fallback）。
    """
    triples = []
    missing_original = 0
    for source_dir in sorted(directory.iterdir()):
        if not source_dir.is_dir():
            continue
        for chunk_file in sorted(source_dir.glob("chunk_*.json")):
            try:
                with open(chunk_file, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    continue
                for item in data:
                    raw = item.get("original_raw_triple")
                    if raw:
                        triples.append(raw)
                    else:
                        # fallback：直接用頂層（可能已正規化，但保留相容）
                        missing_original += 1
                        triples.append(item)
            except Exception as e:
                print(f"  [WARN] {chunk_file}: {e}")
    if missing_original:
        print(f"  [INFO] {missing_original} 筆無 original_raw_triple，使用頂層欄位")
    return triples


def wipe_neo4j(driver):
    print("  清空 Neo4j...")
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    print("  ✓ 清空完成")


def merge_triples(driver, triples: list):
    """批次 MERGE 三元組至 Neo4j。"""
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
                    r.is_validated = false
    """
    rows = []
    for t in triples:
        subj = t.get("subject", {})
        obj  = t.get("object",  {})
        s_name = normalize_entity_name(subj.get("name", ""))
        o_name = normalize_entity_name(obj.get("name", ""))
        if not s_name or not o_name:
            continue
        rows.append({
            "s_name":    s_name,
            "s_type":    subj.get("type", ""),
            "s_display": subj.get("name", s_name),
            "o_name":    o_name,
            "o_type":    obj.get("type", ""),
            "o_display": obj.get("name", o_name),
            "relation":  t.get("relation", ""),
            "source_file":  t.get("source_file", ""),
            "source_id":    t.get("source_id", ""),
            "source_index": t.get("source_index", 0),
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
    """計算結構指標（node/rel/wcc/isolated/avg_degree/type_dist/modularity）。"""
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

        # 各類實體分布
        type_dist = {}
        for rec in s.run(
            "MATCH (n:Entity) RETURN n.type AS t, count(n) AS c ORDER BY c DESC"
        ):
            type_dist[rec["t"] or "unknown"] = rec["c"]
        stats["entity_type_distribution"] = type_dist

    # WCC：用 GDS
    gname = "wcc_prevalidation"
    try:
        with driver.session() as s:
            s.run(f"CALL gds.graph.drop('{gname}', false)")
            s.run(
                f"CALL gds.graph.project('{gname}', 'Entity', "
                f"{{RELATION: {{orientation: 'UNDIRECTED'}}}})"
            )
            wcc = s.run(
                f"CALL gds.wcc.stats('{gname}') YIELD componentCount"
            ).single()["componentCount"]
            stats["wcc_count"] = wcc
            s.run(f"CALL gds.graph.drop('{gname}', false)")
    except Exception as e:
        stats["wcc_count"] = f"ERROR: {e}"

    # Leiden modularity（γ=1 粗估）
    gname2 = "leiden_prevalidation"
    try:
        with driver.session() as s:
            s.run(f"CALL gds.graph.drop('{gname2}', false)")
            s.run(
                f"CALL gds.graph.project('{gname2}', 'Entity', "
                f"{{RELATION: {{orientation: 'UNDIRECTED'}}}})"
            )
            mod = s.run(
                f"CALL gds.leiden.stats('{gname2}', {{gamma: 1.0}}) "
                f"YIELD modularity"
            ).single()["modularity"]
            stats["leiden_modularity_gamma1"] = round(mod, 6)
            s.run(f"CALL gds.graph.drop('{gname2}', false)")
    except Exception as e:
        stats["leiden_modularity_gamma1"] = f"ERROR: {e}"

    return stats


def do_backup_and_copy(dest_path: Path):
    """呼叫 neo4j_backup_restore.py backup，再將產出改名至 dest_path。"""
    result = subprocess.run(
        [sys.executable, str(MATCHGPT_DIR / "neo4j_backup_restore.py"), "backup"],
        capture_output=True, text=True, cwd=str(MATCHGPT_DIR)
    )
    print(result.stdout)
    if result.returncode != 0:
        print("[ERROR] backup 失敗：", result.stderr)
        sys.exit(1)

    # 找到最新產出的備份檔
    pattern = re.compile(r"neo4j_backup_\d+_\d+\.json")
    backups = [f for f in MATCHGPT_DIR.iterdir()
               if f.is_file() and pattern.match(f.name)]
    if not backups:
        print("[ERROR] 找不到備份檔")
        sys.exit(1)
    latest = max(backups, key=lambda f: f.stat().st_mtime)
    shutil.copy2(str(latest), str(dest_path))
    print(f"  ✓ 備份已複製至：{dest_path}")


def main():
    print("=" * 60)
    print("Phase 1 Step 1.2: Build Pre-validation Knowledge Graph")
    print("=" * 60)

    RESULTS_DIR.mkdir(exist_ok=True)
    BACKUPS_DIR.mkdir(exist_ok=True)

    # 1. 載入三元組
    print("\n[1/5] 載入 Validated + Rejected 之 original_raw_triple...")
    validated = load_triples_from_dir(VALIDATED_DIR)
    rejected  = load_triples_from_dir(REJECTED_DIR)
    all_triples = validated + rejected
    print(f"  Validated: {len(validated)} 筆")
    print(f"  Rejected : {len(rejected)} 筆")
    print(f"  合計     : {len(all_triples)} 筆（預期 5,593）")

    # 2. 連接 Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    # 3. Wipe + MERGE
    print("\n[2/5] Wipe Neo4j...")
    wipe_neo4j(driver)

    print("\n[3/5] MERGE 三元組至 Neo4j...")
    merged_count = merge_triples(driver, all_triples)

    # 4. 計算結構指標
    print("\n[4/5] 計算結構指標...")
    stats = compute_stats(driver)
    stats["source"]     = "pre_validation"
    stats["total_input_triples"] = len(all_triples)
    stats["merged_triples"]      = merged_count
    stats["timestamp"] = datetime.now().isoformat()

    stats_path = RESULTS_DIR / "pre_validation_stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 指標已儲存：{stats_path}")
    print(f"  節點：{stats['node_count']}　關係：{stats['rel_count']}")
    print(f"  WCC 數：{stats['wcc_count']}　孤立節點：{stats['isolated_node_count']}")
    print(f"  平均度：{stats['avg_degree']}　Leiden modularity：{stats['leiden_modularity_gamma1']}")

    driver.close()

    # 5. 備份
    print("\n[5/5] 備份 Pre-validation 圖譜...")
    dest = BACKUPS_DIR / "prevalidation_kg.json"
    do_backup_and_copy(dest)

    print("\n✅ 步驟 1.2 完成！")
    print(f"   指標檔：{stats_path}")
    print(f"   備份檔：{dest}")


if __name__ == "__main__":
    main()



