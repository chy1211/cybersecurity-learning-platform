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
Phase 1 Step 1.5: 最佳 threshold 選擇與 final 圖譜定版
- 讀取三組 metrics，跨類別合併率=0% 前提下選結構改善最大者
- 複製為 final_kg.json，restore 到 Neo4j
- 輸出 threshold_selection_rationale.md
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import neo4j_backup_restore as _nbr
from neo4j import GraphDatabase

MATCHGPT_DIR = Path(__file__).parent.parent
RESULTS_DIR  = MATCHGPT_DIR / "phase1_results"
BACKUPS_DIR  = MATCHGPT_DIR / "phase1_backups"
NEO4J_URI    = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER   = "neo4j"
NEO4J_PASS   = os.getenv("NEO4J_PASSWORD", "")
THRESHOLDS   = [0.5, 0.7, 0.9]


def load_metrics(threshold):
    tstr = str(threshold).replace(".", "")
    path = RESULTS_DIR / f"matchgpt_t{tstr}_metrics.json"
    if not path.exists():
        print(f"[ERROR] 找不到 {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    print("=" * 55)
    print("Phase 1 Step 1.5: 最佳 Threshold 選擇")
    print("=" * 55)

    # 載入三組指標
    metrics = {t: load_metrics(t) for t in THRESHOLDS}

    # 讀取 Post-validation 基線
    with open(RESULTS_DIR / "post_validation_stats.json", encoding="utf-8") as f:
        baseline = json.load(f)

    print("\n三組指標對比：")
    print(f"{'指標':<30} {'t=0.5':>10} {'t=0.7':>10} {'t=0.9':>10}")
    print("-" * 62)

    rows = {}
    for t in THRESHOLDS:
        m  = metrics[t]
        pm = m["post_merge"]
        ms = m["merge_stats"]
        rows[t] = {
            "node_count":           pm["node_count"],
            "node_reduction_ratio": ms["node_reduction_ratio"],
            "wcc_count":            pm.get("wcc_count", "N/A"),
            "avg_degree":           pm.get("avg_degree", "N/A"),
            "leiden_modularity":    pm.get("leiden_modularity_gamma1", "N/A"),
            "cross_type_rate":      ms["cross_type_merge_rate"],
            "rel_preservation":     ms["relation_preservation_rate"],
            "merged_pairs":         ms["merged_pairs"],
        }

    def fmt(v): return f"{v:.4f}" if isinstance(v, float) else str(v)

    for label, key in [
        ("節點數",       "node_count"),
        ("節點縮減比",   "node_reduction_ratio"),
        ("WCC 數",      "wcc_count"),
        ("平均節點度",   "avg_degree"),
        ("Leiden mod", "leiden_modularity"),
        ("跨類別合併率", "cross_type_rate"),
        ("關係保留率",   "rel_preservation"),
        ("合併對數",     "merged_pairs"),
    ]:
        vals = [fmt(rows[t][key]) for t in THRESHOLDS]
        print(f"  {label:<28} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10}")

    # 選擇邏輯：
    # 1. 硬性前提：跨類別合併率 = 0%
    # 2. 主排序：節點縮減比最大
    # 3. Tie-breaker：Leiden modularity 最高（取更保守/品質更佳之 threshold）
    eligible = [t for t in THRESHOLDS if rows[t]["cross_type_rate"] == 0.0]
    if not eligible:
        print("\n[WARN] 所有 threshold 均有跨類別合併，選擇跨類別率最低者")
        eligible = THRESHOLDS

    max_reduction = max(rows[t]["node_reduction_ratio"] for t in eligible)
    tied = [t for t in eligible if rows[t]["node_reduction_ratio"] == max_reduction]
    best = max(tied, key=lambda t: (rows[t]["leiden_modularity"]
                                    if isinstance(rows[t]["leiden_modularity"], float) else 0))
    best_tstr = str(best).replace(".", "")

    print(f"\n✅ 選定最佳 threshold：{best}")
    print(f"   節點縮減比：{rows[best]['node_reduction_ratio']:.4f}")
    print(f"   跨類別合併率：{rows[best]['cross_type_rate']}")

    # 複製為 final_kg.json
    src  = BACKUPS_DIR / f"postmatchgpt_t{best_tstr}.json"
    dest = BACKUPS_DIR / "final_kg.json"
    shutil.copy2(str(src), str(dest))
    print(f"\n  ✓ {src.name} → final_kg.json")

    # 驗證備份
    _nbr.verify(str(dest))

    # Restore 到 Neo4j（Phase 2 直接接續）
    print("\n  Restore final_kg.json 到 Neo4j...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    try:
        _nbr.restore(driver, str(dest), wipe=True)
    finally:
        driver.close()

    # 寫選擇理由文件
    rationale = f"""# MatchGPT Threshold 選擇理由

## 選定值：threshold = {best}

## 選擇邏輯
1. 硬性前提：跨類別合併率 = 0%（確保本體論一致性）
2. 次要目標：節點縮減比最大（結構改善幅度最大）

## 三組對比
| threshold | 節點縮減比 | 跨類別合併率 | WCC 數 | Leiden modularity |
|-----------|-----------|------------|--------|------------------|
"""
    for t in THRESHOLDS:
        r = rows[t]
        mark = " ← 選定" if t == best else ""
        rationale += (f"| {t} | {r['node_reduction_ratio']:.4f} "
                      f"| {r['cross_type_rate']:.4f} "
                      f"| {r['wcc_count']} "
                      f"| {fmt(r['leiden_modularity'])} |{mark}\n")

    rationale += f"""
## 備份位置
- 選定 threshold 備份：`phase1_backups/postmatchgpt_t{best_tstr}.json`
- Final 圖譜備份：`phase1_backups/final_kg.json`
- Neo4j 當前狀態：final 圖譜（Phase 2 直接接續）
"""

    rat_path = RESULTS_DIR / "threshold_selection_rationale.md"
    with open(rat_path, "w", encoding="utf-8") as f:
        f.write(rationale)
    print(f"\n  ✓ 選擇理由 → {rat_path}")
    print("\n✅ 步驟 1.5 完成！final_kg.json 已就緒，Neo4j = final 圖譜")

    return best  # 回傳選定 threshold 供後續使用


if __name__ == "__main__":
    main()


