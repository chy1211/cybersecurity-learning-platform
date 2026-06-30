#!/usr/bin/env python3
"""
apply_matchgpt_to_platform.py
===============================
1. 清空 Neo4j
2. 用 03b_restore_neo4j.py 的平台格式還原（各類型有自己的 label，關係為語意名稱，source 為陣列）
3. 讀 matchgpt_merged_t07.csv，對平台格式圖譜執行相同合併
4. 統計並備份

平台格式特性：
  - 節點 label = type（:feature, :policy, :attack ...）
  - 關係 type = 語意關係（:mitigates, :uses, :has_a ...）
  - source_file / source_id / source_index 為「清單屬性」（每次出現都 append）
"""

import csv
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
import sys
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase
from tqdm import tqdm

# ─── Paths ───────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent
MATCHGPT_DIR = SCRIPT_DIR.parent
BACKEND_DIR  = MATCHGPT_DIR.parents[1]
ETL_DIR      = BACKEND_DIR / "ETL_module"
VALIDATED_DIR = ETL_DIR / "Validated"
RESULTS_DIR  = MATCHGPT_DIR / "phase1_results"
BACKUPS_DIR  = MATCHGPT_DIR / "phase1_backups"
MERGED_CSV   = RESULTS_DIR / "matchgpt_merged_t07.csv"

# ─── Neo4j ───────────────────────────────────────────────────────────────────
NEO4J_URI  = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = "neo4j"
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "")

BATCH_SIZE = 100


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1: 平台格式還原（03b 邏輯）
# ═══════════════════════════════════════════════════════════════════════════════

def safe_node_label(name: str) -> str:
    """節點 label：僅英數（Neo4j label 不允許底線開頭，type 名稱如 feature/policy 本身無底線）。"""
    return "".join(c for c in name if c.isalnum())

def safe_rel_type(name: str) -> str:
    """關係 type：保留底線，與 03b_restore_neo4j.py 行為一致。"""
    return "".join(c for c in name if c.isalnum() or c == "_")


def import_triple_platform(session, t: dict):
    """完全照搬 03b_restore_neo4j.py 的 import_to_neo4j 邏輯。"""
    s_name = t["subject"]["name"]
    o_name = t["object"]["name"]
    display_s = t["subject"].get("display_name", s_name).strip()
    display_o = t["object"].get("display_name", o_name).strip()
    s_type     = safe_node_label(t["subject"]["type"])
    o_type     = safe_node_label(t["object"]["type"])
    rel        = safe_rel_type(t["relation"])

    query = f"""
    MERGE (s:{s_type} {{name: $s_name}})
      ON CREATE SET s.display_name = $display_s
    SET s.source_file  = coalesce(s.source_file, [])  + [$source_file],
        s.source_id    = coalesce(s.source_id, [])    + [$source_id],
        s.source_index = coalesce(s.source_index, []) + [$source_index]
    MERGE (o:{o_type} {{name: $o_name}})
      ON CREATE SET o.display_name = $display_o
    SET o.source_file  = coalesce(o.source_file, [])  + [$source_file],
        o.source_id    = coalesce(o.source_id, [])    + [$source_id],
        o.source_index = coalesce(o.source_index, []) + [$source_index]
    MERGE (s)-[r:{rel}]->(o)
    SET r.source_file  = coalesce(r.source_file, [])  + [$source_file],
        r.source_id    = coalesce(r.source_id, [])    + [$source_id],
        r.source_index = coalesce(r.source_index, []) + [$source_index]
    """
    session.run(
        query,
        s_name=s_name, o_name=o_name,
        display_s=display_s, display_o=display_o,
        source_file=t.get("source_file", ""),
        source_id=t.get("source_id", ""),
        source_index=t.get("source_index", ""),
    )


def restore_platform_format(driver):
    """清空 Neo4j 後以平台格式從 Validated/ 還原。"""
    print("  清空 Neo4j...")
    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    print("  ✓ 清空完成")

    # 收集所有 chunk 檔
    files = sorted(VALIDATED_DIR.rglob("chunk_*.json"))
    print(f"  共 {len(files)} 個 chunk 檔，開始匯入...")

    total = 0
    with driver.session() as session:
        for fpath in tqdm(files, desc="  Restore", unit="file"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            for t in data:
                try:
                    import_triple_platform(session, t)
                    total += 1
                except Exception as e:
                    print(f"\n  [WARN] {fpath.name}: {e}")
    print(f"  ✓ 還原完成，匯入 {total} 筆三元組")
    return total


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2: 套用 MatchGPT 合併
# ═══════════════════════════════════════════════════════════════════════════════

def load_merge_pairs(csv_path: Path) -> list[dict]:
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def merge_pair_platform(session, name_a: str, type_a: str,
                        name_b: str, type_b: str) -> str:
    """
    在平台格式圖譜中合併兩個同類型節點。
    - 先把 B 的 source 陣列追加到 A
    - 再用 APOC mergeNodes（properties: discard → 保留 A 的 name/display_name）
    回傳 'merged' / 'not_found' / 'error'
    """
    label_a = safe_node_label(type_a)
    label_b = safe_node_label(type_b)

    if label_a != label_b:
        return "cross_type_skip"

    # 1. 先確認兩節點存在
    check = session.run(
        f"MATCH (a:{label_a} {{name: $na}}), (b:{label_b} {{name: $nb}}) RETURN 1",
        na=name_a, nb=name_b
    ).single()
    if check is None:
        return "not_found"

    # 2. 將 B 的 source 陣列追加到 A（在 APOC 合併前做，否則 discard 會丟失 B 的 source）
    session.run(f"""
        MATCH (a:{label_a} {{name: $na}}), (b:{label_b} {{name: $nb}})
        SET a.source_file  = coalesce(a.source_file, [])  + coalesce(b.source_file, []),
            a.source_id    = coalesce(a.source_id, [])    + coalesce(b.source_id, []),
            a.source_index = coalesce(a.source_index, []) + coalesce(b.source_index, [])
    """, na=name_a, nb=name_b)

    # 3. APOC mergeNodes：保留 A 的 name / display_name，合併關係
    try:
        result = session.run(f"""
            MATCH (a:{label_a} {{name: $na}}), (b:{label_b} {{name: $nb}})
            CALL apoc.refactor.mergeNodes([a, b], {{properties: 'discard', mergeRels: true}})
            YIELD node RETURN node.name AS merged_name
        """, na=name_a, nb=name_b).single()
        return "merged" if result else "not_found"
    except Exception as e:
        return f"error: {e}"


def apply_merges(driver, pairs: list[dict]) -> dict:
    stats = {"merged": 0, "not_found": 0, "cross_type_skip": 0, "error": 0}
    with driver.session() as session:
        for p in tqdm(pairs, desc="  Merging", unit="pair"):
            outcome = merge_pair_platform(
                session,
                p["name_a"], p["type_a"],
                p["name_b"], p["type_b"],
            )
            if outcome == "merged":
                stats["merged"] += 1
            elif outcome == "not_found":
                stats["not_found"] += 1
            elif outcome == "cross_type_skip":
                stats["cross_type_skip"] += 1
            else:
                stats["error"] += 1
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# Stats
# ═══════════════════════════════════════════════════════════════════════════════

def get_db_stats(driver) -> dict:
    with driver.session() as s:
        n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        r = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        # 各 label 分布
        label_dist = {}
        for rec in s.run("MATCH (n) RETURN labels(n)[0] AS lb, count(n) AS c ORDER BY c DESC"):
            label_dist[rec["lb"] or "?"] = rec["c"]
        # 各關係 type 分布（前 10）
        rel_dist = {}
        for rec in s.run("MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS c ORDER BY c DESC LIMIT 10"):
            rel_dist[rec["t"]] = rec["c"]
    return {"node_count": n, "rel_count": r,
            "label_distribution": label_dist, "top_rel_types": rel_dist}


# ═══════════════════════════════════════════════════════════════════════════════
# Backup
# ═══════════════════════════════════════════════════════════════════════════════

def backup_platform_kg(driver):
    """備份平台格式圖譜至 phase1_backups/final_platform_kg.json。"""
    sys.path.insert(0, str(MATCHGPT_DIR))
    import neo4j_backup_restore as nbr
    dest = BACKUPS_DIR / "final_platform_kg.json"
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp  = MATCHGPT_DIR / f"neo4j_backup_{ts}.json"
    nbr.backup(driver, str(tmp))
    shutil.copy2(str(tmp), str(dest))
    print(f"  ✓ 備份 → {dest}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 65)
    print("apply_matchgpt_to_platform.py")
    print("平台格式還原 → MatchGPT 合併套用")
    print("=" * 65)

    # 確認合併清單存在
    if not MERGED_CSV.exists():
        print(f"[ERROR] 找不到 {MERGED_CSV}")
        sys.exit(1)
    pairs = load_merge_pairs(MERGED_CSV)
    print(f"\n待合併對數（t=0.7）：{len(pairs)}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    # ── Step 1：平台格式還原 ────────────────────────────────────────────────
    print("\n[Step 1] 平台格式還原（03b 邏輯）...")
    restore_platform_format(driver)

    pre_stats = get_db_stats(driver)
    print(f"\n  還原後：{pre_stats['node_count']} 節點 / {pre_stats['rel_count']} 關係")
    print(f"  Label 分布（前 5）：")
    for lb, cnt in list(pre_stats["label_distribution"].items())[:5]:
        print(f"    :{lb}  {cnt}")

    # ── Step 2：套用 MatchGPT 合併 ──────────────────────────────────────────
    print(f"\n[Step 2] 套用 MatchGPT 合併（{len(pairs)} 對）...")
    merge_stats = apply_merges(driver, pairs)

    post_stats = get_db_stats(driver)
    print(f"\n  合併結果：")
    print(f"    成功合併：{merge_stats['merged']} 對")
    print(f"    節點已消失（先前被合併）：{merge_stats['not_found']} 對")
    print(f"    跨類別跳過：{merge_stats['cross_type_skip']} 對")
    print(f"    錯誤：{merge_stats['error']} 對")
    print(f"\n  合併前：{pre_stats['node_count']} 節點 / {pre_stats['rel_count']} 關係")
    print(f"  合併後：{post_stats['node_count']} 節點 / {post_stats['rel_count']} 關係")
    print(f"  節點縮減：{pre_stats['node_count'] - post_stats['node_count']} "
          f"（{(pre_stats['node_count']-post_stats['node_count'])/pre_stats['node_count']*100:.1f}%）")

    print(f"\n  合併後 Label 分布（前 5）：")
    for lb, cnt in list(post_stats["label_distribution"].items())[:5]:
        print(f"    :{lb}  {cnt}")
    print(f"\n  合併後關係 type 分布（Top 10）：")
    for t, cnt in post_stats["top_rel_types"].items():
        print(f"    :{t}  {cnt}")

    # ── Step 2.5：加 :KGNode label + type 屬性（供 Phase 2 GDS 使用）────────
    print("\n[Step 2.5] 加 :KGNode 共同 label + type 屬性...")
    with driver.session() as s:
        result = s.run("""
            MATCH (n)
            WHERE NOT n:KGNode
            WITH n, labels(n)[0] AS type_label
            SET n.type = type_label, n:KGNode
            RETURN count(n) AS updated
        """).single()
        print(f"  ✓ 已標記 {result['updated']} 個節點（:KGNode + type 屬性）")

    # ── Step 3：備份 ────────────────────────────────────────────────────────
    print("\n[Step 3] 備份平台格式 final 圖譜...")
    backup_platform_kg(driver)

    driver.close()

    # 儲存統計結果
    result = {
        "timestamp":   datetime.now().isoformat(),
        "merge_csv":   str(MERGED_CSV),
        "pairs_total": len(pairs),
        "merge_stats": merge_stats,
        "pre_stats":   pre_stats,
        "post_stats":  post_stats,
    }
    out = RESULTS_DIR / "platform_merge_stats.json"
    import json as _json
    with open(out, "w", encoding="utf-8") as f:
        _json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  ✓ 統計 → {out}")

    print("\n✅ 完成！Neo4j 當前狀態 = 平台格式 final 圖譜（可直接接平台使用）")


if __name__ == "__main__":
    main()



