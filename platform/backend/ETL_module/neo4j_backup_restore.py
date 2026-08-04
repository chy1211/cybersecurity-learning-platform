"""
neo4j_backup_restore.py
========================
Neo4j Community Edition 完整備份與還原工具

用法：
  python neo4j_backup_restore.py backup              # 備份到 neo4j_backup_<timestamp>.json
  python neo4j_backup_restore.py restore <檔案路徑>  # 從備份 JSON 還原
  python neo4j_backup_restore.py verify  <檔案路徑>  # 驗證備份完整性（不寫入 DB）

備份內容：
  - 所有節點（含全部 label 與 properties）
  - 所有關係（含 type 與 properties）

還原策略：
  - MERGE on name（不重複建立節點）
  - 還原前可選擇是否先清空 DB（--wipe 旗標）
"""

import json
import sys
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
from datetime import datetime
from neo4j import GraphDatabase

# ─────────────────────────────────────────────────────────────────────────────
# 連線設定（與 03_validate_and_import_fixed.py 相同）
# ─────────────────────────────────────────────────────────────────────────────
NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

BACKUP_DIR = os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────────────────────────────────────────────────────────
# BACKUP
# ─────────────────────────────────────────────────────────────────────────────

def backup(driver, output_path: str):
    print(f"=== 開始備份 ===")
    with driver.session() as session:

        # 1. 取得所有節點
        print("  正在匯出節點...")
        node_result = session.run("""
            MATCH (n)
            RETURN
                id(n)           AS internal_id,
                labels(n)       AS labels,
                properties(n)   AS props
            ORDER BY id(n)
        """)
        nodes = []
        for record in node_result:
            nodes.append({
                "internal_id": record["internal_id"],
                "labels":      record["labels"],
                "props":       dict(record["props"])
            })
        print(f"  → 節點數：{len(nodes)}")

        # 2. 取得所有關係
        print("  正在匯出關係...")
        rel_result = session.run("""
            MATCH (s)-[r]->(o)
            RETURN
                id(s)           AS src_id,
                labels(s)       AS src_labels,
                s.name          AS src_name,
                type(r)         AS rel_type,
                properties(r)   AS rel_props,
                id(o)           AS dst_id,
                labels(o)       AS dst_labels,
                o.name          AS dst_name
            ORDER BY id(r)
        """)
        rels = []
        for record in rel_result:
            rels.append({
                "src_id":     record["src_id"],
                "src_labels": record["src_labels"],
                "src_name":   record["src_name"],
                "rel_type":   record["rel_type"],
                "rel_props":  dict(record["rel_props"]),
                "dst_id":     record["dst_id"],
                "dst_labels": record["dst_labels"],
                "dst_name":   record["dst_name"],
            })
        print(f"  → 關係數：{len(rels)}")

    # 3. 儲存為 JSON
    backup_data = {
        "meta": {
            "created_at": datetime.now().isoformat(),
            "neo4j_uri":  NEO4J_URI,
            "node_count": len(nodes),
            "rel_count":  len(rels),
            "tool":       "neo4j_backup_restore.py"
        },
        "nodes": nodes,
        "relationships": rels
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"\n✅ 備份完成：{output_path}")
    print(f"   節點：{len(nodes)}，關係：{len(rels)}，大小：{size_mb:.2f} MB")
    return backup_data


# ─────────────────────────────────────────────────────────────────────────────
# RESTORE
# ─────────────────────────────────────────────────────────────────────────────

def restore(driver, backup_path: str, wipe: bool = False):
    print(f"=== 開始還原：{backup_path} ===")

    with open(backup_path, "r", encoding="utf-8") as f:
        backup_data = json.load(f)

    meta  = backup_data["meta"]
    nodes = backup_data["nodes"]
    rels  = backup_data["relationships"]

    print(f"  備份時間：{meta['created_at']}")
    print(f"  節點：{meta['node_count']}，關係：{meta['rel_count']}")

    with driver.session() as session:

        # 0. 選擇性清空
        if wipe:
            print("\n  ⚠️  清空現有資料庫...")
            session.run("MATCH (n) DETACH DELETE n")
            current = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            print(f"  清空後節點數：{current}")

        # 1. 還原節點
        print(f"\n  正在還原 {len(nodes)} 個節點...")
        node_ok = 0
        node_err = 0

        for node in nodes:
            labels = node["labels"]
            props  = node["props"]

            if not labels:
                print(f"  [警告] 節點無 label，跳過：{props}")
                node_err += 1
                continue

            # 以第一個 label + name 做 MERGE 鍵
            primary_label = "".join(c for c in labels[0] if c.isalnum())
            extra_labels  = ":".join(
                "".join(c for c in lb if c.isalnum()) for lb in labels[1:]
            )
            label_clause = f":{primary_label}" + (f":{extra_labels}" if extra_labels else "")

            # 選擇 MERGE 鍵：優先用 name，fallback 用所有 props
            if "name" in props:
                merge_clause   = f"MERGE (n{label_clause} {{name: $name}})"
                merge_params   = {"name": props["name"]}
                set_props      = {k: v for k, v in props.items() if k != "name"}
            else:
                # 沒有 name 的節點，用所有 props 做唯一鍵
                merge_clause   = f"MERGE (n{label_clause} $props)"
                merge_params   = {"props": props}
                set_props      = {}

            try:
                session.run(
                    f"{merge_clause} SET n += $set_props",
                    **merge_params,
                    set_props=set_props
                )
                node_ok += 1
            except Exception as e:
                print(f"  [節點錯誤] {props.get('name', '?')}: {e}")
                node_err += 1

        print(f"  → 節點還原：成功 {node_ok}，失敗 {node_err}")

        # 2. 還原關係
        print(f"\n  正在還原 {len(rels)} 個關係...")
        rel_ok = 0
        rel_err = 0

        for rel in rels:
            src_label  = "".join(c for c in rel["src_labels"][0] if c.isalnum()) if rel["src_labels"] else ""
            dst_label  = "".join(c for c in rel["dst_labels"][0] if c.isalnum()) if rel["dst_labels"] else ""
            rel_type   = "".join(c for c in rel["rel_type"] if c.isalnum() or c == "_")
            rel_props  = rel["rel_props"]
            src_name   = rel["src_name"]
            dst_name   = rel["dst_name"]

            if not src_label or not dst_label or not src_name or not dst_name:
                rel_err += 1
                continue

            try:
                session.run(f"""
                    MATCH (s:{src_label} {{name: $src_name}})
                    MATCH (d:{dst_label} {{name: $dst_name}})
                    MERGE (s)-[r:{rel_type}]->(d)
                    SET r += $props
                """, src_name=src_name, dst_name=dst_name, props=rel_props)
                rel_ok += 1
            except Exception as e:
                print(f"  [關係錯誤] {src_name} -{rel_type}-> {dst_name}: {e}")
                rel_err += 1

        print(f"  → 關係還原：成功 {rel_ok}，失敗 {rel_err}")

        # 3. 驗證
        final_nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        final_rels  = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

    print(f"\n✅ 還原完成")
    print(f"   DB 現有節點：{final_nodes}（備份：{meta['node_count']}）")
    print(f"   DB 現有關係：{final_rels}（備份：{meta['rel_count']}）")

    if final_nodes >= meta["node_count"] and final_rels >= meta["rel_count"]:
        print("   ✅ 數量吻合，還原成功")
    else:
        print("   ⚠️  數量不符，請檢查 node_err / rel_err 輸出")


# ─────────────────────────────────────────────────────────────────────────────
# VERIFY（不寫入 DB，只驗證備份 JSON 完整性）
# ─────────────────────────────────────────────────────────────────────────────

def verify(backup_path: str):
    print(f"=== 驗證備份：{backup_path} ===")
    with open(backup_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta  = data.get("meta", {})
    nodes = data.get("nodes", [])
    rels  = data.get("relationships", [])

    print(f"  備份時間  ：{meta.get('created_at')}")
    print(f"  宣告節點數：{meta.get('node_count')} → 實際：{len(nodes)}")
    print(f"  宣告關係數：{meta.get('rel_count')} → 實際：{len(rels)}")

    # 檢查節點：有幾個沒有 name
    no_name = [n for n in nodes if "name" not in n.get("props", {})]
    no_label = [n for n in nodes if not n.get("labels")]
    print(f"  無 name 節點：{len(no_name)}")
    print(f"  無 label 節點：{len(no_label)}")

    # 統計 label 分佈
    from collections import Counter
    label_counts = Counter()
    for n in nodes:
        for lb in n.get("labels", []):
            label_counts[lb] += 1

    print(f"\n  Label 分佈：")
    for lb, cnt in sorted(label_counts.items(), key=lambda x: -x[1]):
        print(f"    {lb}: {cnt}")

    # 統計關係類型分佈
    rel_type_counts = Counter(r["rel_type"] for r in rels)
    print(f"\n  關係類型分佈：")
    for rt, cnt in sorted(rel_type_counts.items(), key=lambda x: -x[1]):
        print(f"    {rt}: {cnt}")

    ok = (len(nodes) == meta.get("node_count") and len(rels) == meta.get("rel_count"))
    print(f"\n{'✅ 備份完整' if ok else '❌ 備份異常，數量不符'}")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if not args or args[0] not in ("backup", "restore", "verify"):
        print(__doc__)
        print("用法範例：")
        print("  python neo4j_backup_restore.py backup")
        print("  python neo4j_backup_restore.py restore neo4j_backup_20260517_115000.json")
        print("  python neo4j_backup_restore.py restore neo4j_backup_20260517_115000.json --wipe")
        print("  python neo4j_backup_restore.py verify  neo4j_backup_20260517_115000.json")
        sys.exit(0)

    mode = args[0]

    if mode == "backup":
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(BACKUP_DIR, f"neo4j_backup_{timestamp}.json")
        try:
            backup(driver, output_path)
        finally:
            driver.close()

    elif mode == "restore":
        if len(args) < 2:
            print("請提供備份檔案路徑")
            sys.exit(1)
        backup_path = args[1]
        wipe = "--wipe" in args

        if wipe:
            confirm = input("⚠️  --wipe 會清空現有 DB！確認繼續？(yes/no): ").strip()
            if confirm.lower() != "yes":
                print("已取消")
                sys.exit(0)

        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        try:
            restore(driver, backup_path, wipe=wipe)
        finally:
            driver.close()

    elif mode == "verify":
        if len(args) < 2:
            print("請提供備份檔案路徑")
            sys.exit(1)
        verify(args[1])


if __name__ == "__main__":
    main()
