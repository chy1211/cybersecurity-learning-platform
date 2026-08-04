#!/usr/bin/env python3
"""convert_generic_to_platform.py — B3 前置：定版泛型圖 → 平台格式（無損 schema 轉換）

把 Neo4j 現行庫（B2 定版：2763 :Entity 節點 / 3803 :RELATION 關係）就地轉成
Phase 2（Leiden/GDS）與 exp_3 期望的平台格式：
  1. 每個 :Entity 節點加上 :KGNode label（labels 變 [Entity, KGNode]）
  2. 每條 RELATION 依 r.relation 改為同名型別關係（16 種），屬性原封搬移
  3. 節點補 n.source_file ＝ 鄰接關係 source_file 之去重清單
     （exp_2 Layer 3 讀節點層 source_file 做章節覆蓋；孤兒節點得空清單）

與舊鏈差異（2026-07-12 B3 拍板）：舊鏈用 apply_matchgpt_to_platform.py 從
Validated/ 重灌＋重放合併——平台格式以（型別,名稱）為節點身分，跨型同名不會
被吸收、合併又依 CSV 列序重放，節點/關係數無法保證等於定版 2763/3803，會造成
全鏈單圖數字分叉。本腳本改為對已凍結之定版圖做純 schema 轉換：內容零變動、
數字完全承襲；轉換後逐項對帳 final_kg.json 的 relation 分布。

用法（命令列 ASCII，經 rp.py）：
  python _tooling\\rp.py exp_1/MatchGPT/phase1_scripts/convert_generic_to_platform.py
  python _tooling\\rp.py ... --verify-only    # 只對帳不動庫

中斷/失敗還原：以修復版 neo4j_backup_restore.py（wipe 模式）restore
phase1_backups/final_kg.json 後重跑本腳本（轉換冪等：偵測到 RELATION=0 即拒跑）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Load backend .env when this script is executed directly.
try:
    from dotenv import load_dotenv as _load_dotenv
    for _env_parent in Path(__file__).resolve().parents:
        _env_file = _env_parent / ".env"
        if _env_file.exists():
            _load_dotenv(_env_file)
            break
except Exception:
    pass

from neo4j import GraphDatabase

SCRIPT_DIR   = Path(__file__).resolve().parent
MATCHGPT_DIR = SCRIPT_DIR.parent
FINAL_KG     = MATCHGPT_DIR / "phase1_backups" / "final_kg.json"
PLATFORM_BAK = MATCHGPT_DIR / "phase1_backups" / "final_platform_kg.json"

NEO4J_URI  = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = "neo4j"
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "")


def expected_from_final_kg() -> tuple[int, int, Counter]:
    data = json.loads(FINAL_KG.read_text(encoding="utf-8"))
    nodes = data["nodes"]
    rels = data["relationships"]
    dist = Counter((r.get("rel_props") or {}).get("relation") for r in rels)
    return len(nodes), len(rels), dist


def db_state(session) -> dict:
    n_total = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    n_entity = session.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
    n_kgnode = session.run("MATCH (n:KGNode) RETURN count(n) AS c").single()["c"]
    r_total = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    r_generic = session.run("MATCH ()-[r:RELATION]->() RETURN count(r) AS c").single()["c"]
    loops = session.run("MATCH (a)-[r]->(a) RETURN count(r) AS c").single()["c"]
    typed = Counter()
    for rec in session.run("MATCH ()-[r]->() WHERE type(r) <> 'RELATION' "
                           "RETURN type(r) AS t, count(r) AS c"):
        typed[rec["t"]] = rec["c"]
    return {"n_total": n_total, "n_entity": n_entity, "n_kgnode": n_kgnode,
            "r_total": r_total, "r_generic": r_generic, "self_loops": loops,
            "typed_dist": typed}


def verify(session, exp_nodes: int, exp_rels: int, exp_dist: Counter,
           post_convert: bool) -> bool:
    st = db_state(session)
    ok = True

    def chk(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print("  %-28s got=%-6s want=%-6s %s" % (name, got, want,
                                                 "OK" if good else "MISMATCH"))

    chk("nodes_total", st["n_total"], exp_nodes)
    chk("nodes_entity", st["n_entity"], exp_nodes)
    chk("rels_total", st["r_total"], exp_rels)
    chk("self_loops", st["self_loops"], 0)
    if post_convert:
        chk("nodes_kgnode", st["n_kgnode"], exp_nodes)
        chk("rels_generic_RELATION", st["r_generic"], 0)
        for t, c in sorted(exp_dist.items(), key=lambda x: -x[1]):
            chk("rel_type %s" % t, st["typed_dist"].get(t, 0), c)
        extra = set(st["typed_dist"]) - set(exp_dist)
        if extra:
            ok = False
            print("  UNEXPECTED rel types: %s" % sorted(extra))
        # node-level source_file coverage
        n_src = session.run(
            "MATCH (n:KGNode) WHERE n.source_file IS NOT NULL "
            "AND size(n.source_file) > 0 RETURN count(n) AS c").single()["c"]
        n_deg0 = session.run(
            "MATCH (n:KGNode) WHERE NOT (n)--() RETURN count(n) AS c").single()["c"]
        chk("nodes_with_source_file", n_src, exp_nodes - n_deg0)
        print("  isolated nodes (empty source list): %d" % n_deg0)
        # rel property survival spot check
        r_src = session.run(
            "MATCH ()-[r]->() WHERE r.source_file IS NOT NULL "
            "RETURN count(r) AS c").single()["c"]
        chk("rels_with_source_file", r_src, exp_rels)
    return ok


def convert(session) -> None:
    print("[1/3] add :KGNode label to every :Entity node ...")
    c = session.run("MATCH (n:Entity) WHERE NOT n:KGNode "
                    "SET n:KGNode RETURN count(n) AS c").single()["c"]
    print("  labeled: %d" % c)

    print("[2/3] retype RELATION edges by r.relation (apoc, batched) ...")
    rec = session.run(
        "CALL apoc.periodic.iterate("
        " 'MATCH (a)-[r:RELATION]->(b) RETURN a, r, b',"
        " 'CALL apoc.create.relationship(a, r.relation, properties(r), b)"
        "  YIELD rel DELETE r',"
        " {batchSize: 500}) "
        "YIELD batches, total, errorMessages RETURN batches, total, errorMessages"
    ).single()
    print("  batches=%s total=%s errors=%s"
          % (rec["batches"], rec["total"], dict(rec["errorMessages"] or {})))

    print("[3/3] materialize node-level source_file lists ...")
    c = session.run(
        "MATCH (n:KGNode) "
        "OPTIONAL MATCH (n)-[r]-() "
        "WITH n, [x IN collect(DISTINCT r.source_file) WHERE x IS NOT NULL] AS sf "
        "SET n.source_file = sf RETURN count(n) AS c").single()["c"]
    print("  nodes updated: %d" % c)


def backup_platform(driver) -> None:
    sys.path.insert(0, str(MATCHGPT_DIR))
    import neo4j_backup_restore as nbr
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp = MATCHGPT_DIR / ("neo4j_backup_%s.json" % ts)
    nbr.backup(driver, str(tmp))
    import shutil
    shutil.copy2(str(tmp), str(PLATFORM_BAK))
    print("  backup -> %s" % PLATFORM_BAK)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-only", action="store_true",
                    help="only run post-conversion verification against final_kg.json")
    args = ap.parse_args()

    exp_nodes, exp_rels, exp_dist = expected_from_final_kg()
    print("expected from final_kg.json: nodes=%d rels=%d rel-types=%d"
          % (exp_nodes, exp_rels, len(exp_dist)))

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        with driver.session() as session:
            st = db_state(session)
            if args.verify_only:
                ok = verify(session, exp_nodes, exp_rels, exp_dist, post_convert=True)
                print("VERIFY %s" % ("PASS" if ok else "FAIL"))
                return 0 if ok else 1

            # pre-flight: must be the untouched generic authoritative graph
            if st["r_generic"] == 0:
                print("ABORT: no :RELATION edges left; graph looks already "
                      "converted. Use --verify-only, or restore final_kg.json "
                      "first if you need a clean re-run.")
                return 1
            print("pre-flight DB state check (must equal frozen authority):")
            ok = verify(session, exp_nodes, exp_rels, exp_dist, post_convert=False)
            if not ok or st["r_generic"] != exp_rels:
                print("ABORT: DB does not match final_kg.json authority "
                      "(generic rels=%d, expected %d). Restore final_kg.json "
                      "with the fixed neo4j_backup_restore.py first."
                      % (st["r_generic"], exp_rels))
                return 1

            convert(session)

            print("post-conversion verification:")
            ok = verify(session, exp_nodes, exp_rels, exp_dist, post_convert=True)
            print("VERIFY %s" % ("PASS" if ok else "FAIL"))
            if not ok:
                return 1

        print("backing up platform-format graph ...")
        backup_platform(driver)
    finally:
        driver.close()

    print("DONE: platform-format graph ready (KGNode + 16 typed rel types).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
