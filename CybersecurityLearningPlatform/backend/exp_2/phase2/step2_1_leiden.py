#!/usr/bin/env python3
"""
Phase 2 Step 2.1: Leiden parameter grid scan + finalize.

掃描模式（預設）：
  python step2_1_leiden.py
  → 跑 6×3=18 組參數，輸出比較表 leiden_18params_compare.json，
    不寫入 communityId，等人工確認後再 finalize。

定案模式：
  python step2_1_leiden.py --finalize --gamma 2.0 --min_community_size 3
  → 將選定組的社群 ID 寫入 communityId，清除臨時掃描屬性。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from phase2_common import (
    DEFAULT_NEO4J_PASSWORD,
    DEFAULT_NEO4J_URI,
    DEFAULT_NEO4J_USER,
    default_output_path,
    drop_gds_graph,
    now_iso,
    open_driver,
    platform_rel_projection,
    write_json,
)

# ─── 參數格點 ─────────────────────────────────────────────────────────────────
GAMMAS          = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
MIN_SIZES       = [1, 3, 5]
RANDOM_SEED     = 42
FINAL_PROPERTY  = "communityId"
GRAPH_NAME      = "kg_phase2_leiden"
OUTPUT_FILENAME = "leiden_18params_compare.json"


def _prop_name(gamma: float, min_size: int) -> str:
    g_str = str(gamma).replace(".", "")   # 0.5→05, 1.0→10
    return f"cid_g{g_str}_m{min_size}"


def _config_key(gamma: float, min_size: int) -> str:
    return f"γ={gamma}, minSize={min_size}"


# ─── GDS 投影 ──────────────────────────────────────────────────────────────────

def project_graph(session) -> dict:
    drop_gds_graph(session, GRAPH_NAME)
    rec = session.run(
        "CALL gds.graph.project($gn, 'KGNode', $rp) "
        "YIELD graphName, nodeCount, relationshipCount "
        "RETURN graphName, nodeCount, relationshipCount",
        gn=GRAPH_NAME,
        rp=platform_rel_projection("UNDIRECTED"),
    ).single()
    return dict(rec) if rec else {}


# ─── 掃描模式 ──────────────────────────────────────────────────────────────────

def fetch_community_sizes(session, prop: str) -> list[int]:
    rows = session.run(
        "MATCH (n:KGNode) WHERE n[$p] IS NOT NULL "
        "WITH n[$p] AS cid, count(n) AS sz RETURN sz ORDER BY sz DESC",
        p=prop,
    )
    return [int(r["sz"]) for r in rows]


def run_one_config(session, gamma: float, min_size: int) -> dict:
    prop = _prop_name(gamma, min_size)
    gds_cfg = {
        "writeProperty":    prop,
        "gamma":            gamma,
        "minCommunitySize": min_size,
        "randomSeed":       RANDOM_SEED,
        "consecutiveIds":   True,
    }
    rec = session.run(
        "CALL gds.leiden.write($gn, $cfg) YIELD communityCount, modularity "
        "RETURN communityCount, modularity",
        gn=GRAPH_NAME, cfg=gds_cfg,
    ).single()
    if rec is None:
        raise RuntimeError(f"Leiden returned no result for γ={gamma} min={min_size}")

    sizes = fetch_community_sizes(session, prop)
    total_nodes = sum(sizes)
    top50_nodes = sum(sorted(sizes, reverse=True)[:50])
    top50_cov   = round(top50_nodes / total_nodes, 4) if total_nodes else 0.0
    largest_pct = round(max(sizes) / total_nodes, 4) if sizes else 0.0

    buckets = {"1-2": 0, "3-9": 0, "10-49": 0, "50-99": 0, ">=100": 0}
    for s in sizes:
        if s <= 2:           buckets["1-2"]   += 1
        elif s <= 9:         buckets["3-9"]   += 1
        elif s <= 49:        buckets["10-49"] += 1
        elif s <= 99:        buckets["50-99"] += 1
        else:                buckets[">=100"] += 1

    return {
        "gamma":             gamma,
        "minCommunitySize":  min_size,
        "writeProperty":     prop,
        "communityCount":    int(rec["communityCount"]),
        "modularity":        round(float(rec["modularity"]), 6),
        "top50_coverage":    top50_cov,
        "largest_community_pct": largest_pct,
        "largestCommunitySize":  max(sizes) if sizes else 0,
        "smallestCommunitySize": min(sizes) if sizes else 0,
        "sizeDistribution":  buckets,
    }


def print_comparison_table(results: list[dict]) -> None:
    print("\n" + "=" * 82)
    print(f"{'γ':>5} {'minSz':>6} {'社群數':>7} {'modularity':>12} {'Top50覆蓋':>10} {'最大社群%':>10} {'>=10社群':>8}")
    print("-" * 82)
    for r in results:
        large_comm = (r["sizeDistribution"].get("10-49", 0)
                      + r["sizeDistribution"].get("50-99", 0)
                      + r["sizeDistribution"].get(">=100", 0))
        print(
            f"{r['gamma']:>5.1f} {r['minCommunitySize']:>6d} "
            f"{r['communityCount']:>7d} {r['modularity']:>12.6f} "
            f"{r['top50_coverage']*100:>9.1f}% {r['largest_community_pct']*100:>9.1f}% "
            f"{large_comm:>8d}"
        )
    print("=" * 82)
    print("  選擇提示：")
    print("  • 社群數：建議 20-60（配合技能樹粒度）")
    print("  • Top50覆蓋：越高越好（>90% 代表 Top 50 能代表大部分知識）")
    print("  • 最大社群%：建議 <25%（避免一個雜物桶社群）")
    print("  • modularity：同等社群數下選較高者\n")


def run_scan(uri: str, user: str, password: str, output: Path) -> list[dict]:
    driver = open_driver(uri, user, password)
    results = []
    total = len(GAMMAS) * len(MIN_SIZES)

    try:
        with driver.session() as session:
            print(f"[1/2] 建立 GDS 投影（KGNode × 16 關係，UNDIRECTED）...")
            proj = project_graph(session)
            print(f"  節點：{proj.get('nodeCount')}，關係：{proj.get('relationshipCount')}")

            print(f"\n[2/2] 掃描 {total} 組參數（γ × minCommunitySize）...")
            idx = 0
            for gamma in GAMMAS:
                for min_size in MIN_SIZES:
                    idx += 1
                    print(f"  [{idx:2d}/{total}] γ={gamma}, minSize={min_size}", end=" ... ", flush=True)
                    result = run_one_config(session, gamma, min_size)
                    results.append(result)
                    print(f"社群數={result['communityCount']}, modularity={result['modularity']:.4f}")

    finally:
        with driver.session() as s:
            drop_gds_graph(s, GRAPH_NAME)
        driver.close()

    payload = {
        "generated_at":  now_iso(),
        "random_seed":   RANDOM_SEED,
        "total_configs": total,
        "results":       results,
        "status":        "scan_complete_pending_finalize",
    }
    write_json(output, payload)
    print(f"\n比較表已儲存：{output}")
    print_comparison_table(results)
    print("─" * 60)
    print("請選擇最終參數後執行：")
    print("  python step2_1_leiden.py --finalize --gamma <γ> --min_community_size <m>")
    print("─" * 60)
    return results


# ─── 定案模式 ──────────────────────────────────────────────────────────────────

def run_finalize(uri: str, user: str, password: str,
                 gamma: float, min_size: int,
                 scan_output: Path) -> int:
    prop = _prop_name(gamma, min_size)

    # 確認掃描屬性存在
    driver = open_driver(uri, user, password)
    try:
        with driver.session() as session:
            check = session.run(
                "MATCH (n:KGNode) WHERE n[$p] IS NOT NULL RETURN count(n) AS c",
                p=prop,
            ).single()["c"]

        if check == 0:
            print(f"[ERROR] 節點上找不到屬性 {prop}。")
            print("        請先跑掃描模式（不加 --finalize）。")
            return 0

        print(f"確認屬性 {prop} 存在於 {check} 個節點。")
        print(f"寫入 communityId = {prop} 的值...")

        with driver.session() as session:
            # 1. 寫入 communityId
            written = session.run(
                "MATCH (n:KGNode) WHERE n[$p] IS NOT NULL "
                "SET n.communityId = n[$p] RETURN count(n) AS c",
                p=prop,
            ).single()["c"]

            # 2. 清除所有臨時掃描屬性（保持 DB 乾淨）
            all_props = [_prop_name(g, m) for g in GAMMAS for m in MIN_SIZES]
            for tmp_prop in all_props:
                session.run(
                    "MATCH (n:KGNode) WHERE n[$p] IS NOT NULL REMOVE n[$p]",
                    p=tmp_prop,
                )
            print(f"  臨時屬性（{len(all_props)} 個）已清除。")

        # 3. 更新掃描 JSON 紀錄（標記已定案）
        if scan_output.exists():
            import json
            with open(scan_output, encoding="utf-8") as f:
                data = json.load(f)
            data["status"]           = "finalized"
            data["finalized_at"]     = now_iso()
            data["selected_gamma"]   = gamma
            data["selected_min_size"] = min_size
            data["selected_property"] = prop
            data["communityId_written"] = int(written)
            write_json(scan_output, data)
            print(f"  掃描紀錄已更新（標記定案）：{scan_output}")

    finally:
        driver.close()

    print(f"\n✅ 定案完成：γ={gamma}, minCommunitySize={min_size}")
    print(f"   communityId 已寫入 {written} 個節點。")
    return int(written)


# ─── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri",      default=DEFAULT_NEO4J_URI)
    parser.add_argument("--user",     default=DEFAULT_NEO4J_USER)
    parser.add_argument("--password", default=DEFAULT_NEO4J_PASSWORD)
    parser.add_argument(
        "--output",
        default=str(default_output_path(OUTPUT_FILENAME)),
        help="比較表 JSON 輸出路徑",
    )
    # 定案模式旗標
    parser.add_argument("--finalize", action="store_true",
                        help="定案模式：將選定參數的結果寫入 communityId")
    parser.add_argument("--gamma", type=float,
                        help="[定案模式] 選定的 gamma 值")
    parser.add_argument("--min_community_size", type=int,
                        help="[定案模式] 選定的 minCommunitySize 值")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = Path(args.output)

    if args.finalize:
        if args.gamma is None or args.min_community_size is None:
            print("[ERROR] --finalize 需同時指定 --gamma 和 --min_community_size")
            return
        if args.gamma not in GAMMAS:
            print(f"[ERROR] gamma={args.gamma} 不在掃描範圍 {GAMMAS}")
            return
        if args.min_community_size not in MIN_SIZES:
            print(f"[ERROR] min_community_size={args.min_community_size} 不在掃描範圍 {MIN_SIZES}")
            return
        run_finalize(args.uri, args.user, args.password,
                     args.gamma, args.min_community_size, output)
    else:
        run_scan(args.uri, args.user, args.password, output)


if __name__ == "__main__":
    main()
