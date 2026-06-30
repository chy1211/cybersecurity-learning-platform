#!/usr/bin/env python3
"""
Phase 1 Step 1.6: 跑前跑後結構指標彙整
- 讀取 pre/post/matchgpt 三階段指標
- 輸出 pre_post_matchgpt_compare.json（供論文表 4-7）
"""
import json
import sys
from pathlib import Path

MATCHGPT_DIR = Path(__file__).parent.parent
RESULTS_DIR  = MATCHGPT_DIR / "phase1_results"
THRESHOLDS   = [0.5, 0.7, 0.9]


def main():
    print("=" * 55)
    print("Phase 1 Step 1.6: 跑前跑後結構指標彙整")
    print("=" * 55)

    # 讀取三段指標
    with open(RESULTS_DIR / "pre_validation_stats.json",  encoding="utf-8") as f:
        pre  = json.load(f)
    with open(RESULTS_DIR / "post_validation_stats.json", encoding="utf-8") as f:
        post = json.load(f)

    # 找出最佳 threshold（從 rationale.md 解析，或自動從 final_kg.json 反推）
    rat_path = RESULTS_DIR / "threshold_selection_rationale.md"
    best_t = None
    if rat_path.exists():
        txt = rat_path.read_text(encoding="utf-8")
        for t in THRESHOLDS:
            if f"threshold = {t}" in txt:
                best_t = t
                break
    if best_t is None:
        # fallback：選節點縮減比最大者
        best_t = max(
            THRESHOLDS,
            key=lambda t: json.load(
                open(RESULTS_DIR / f"matchgpt_t{str(t).replace('.','')}_metrics.json",
                     encoding="utf-8")
            )["merge_stats"]["node_reduction_ratio"]
        )
    best_tstr = str(best_t).replace(".", "")
    print(f"  Final threshold：{best_t}")

    with open(RESULTS_DIR / f"matchgpt_t{best_tstr}_metrics.json", encoding="utf-8") as f:
        final_m = json.load(f)

    pm = final_m["post_merge"]
    ms = final_m["merge_stats"]

    compare = {
        "description": "Pre-validation / Post-validation / Post-MatchGPT 三階段結構對比",
        "final_threshold": best_t,
        "columns": ["pre_validation", "post_validation", f"post_matchgpt_t{best_t}"],
        "metrics": {
            "node_count": {
                "pre_validation":            pre["node_count"],
                "post_validation":           post["node_count"],
                f"post_matchgpt_t{best_t}":  pm["node_count"],
            },
            "rel_count": {
                "pre_validation":            pre["rel_count"],
                "post_validation":           post["rel_count"],
                f"post_matchgpt_t{best_t}":  pm["rel_count"],
            },
            "wcc_count": {
                "pre_validation":            pre.get("wcc_count"),
                "post_validation":           post.get("wcc_count"),
                f"post_matchgpt_t{best_t}":  pm.get("wcc_count"),
            },
            "avg_degree": {
                "pre_validation":            pre.get("avg_degree"),
                "post_validation":           post.get("avg_degree"),
                f"post_matchgpt_t{best_t}":  pm.get("avg_degree"),
            },
            "isolated_node_count": {
                "pre_validation":            pre.get("isolated_node_count"),
                "post_validation":           post.get("isolated_node_count"),
                f"post_matchgpt_t{best_t}":  pm.get("isolated_node_count"),
            },
            "leiden_modularity_gamma1": {
                "pre_validation":            pre.get("leiden_modularity_gamma1"),
                "post_validation":           post.get("leiden_modularity_gamma1"),
                f"post_matchgpt_t{best_t}":  pm.get("leiden_modularity_gamma1"),
            },
        },
        "delta_pre_to_post": {
            "node_reduction":     pre["node_count"] - post["node_count"],
            "node_reduction_pct": round((pre["node_count"] - post["node_count"]) / pre["node_count"] * 100, 2),
            "rel_reduction":      pre["rel_count"] - post["rel_count"],
            "wcc_reduction":      (pre.get("wcc_count") or 0) - (post.get("wcc_count") or 0),
        },
        "delta_post_to_matchgpt": {
            "node_reduction":      post["node_count"] - pm["node_count"],
            "node_reduction_ratio": ms["node_reduction_ratio"],
            "node_reduction_pct":  round(ms["node_reduction_ratio"] * 100, 2),
            "merged_pairs":        ms["merged_pairs"],
            "relation_preservation_rate": ms["relation_preservation_rate"],
        },
        "matchgpt_3layer_summary_path": str(RESULTS_DIR / "matchgpt_3layer_summary.json"),
    }

    out_path = RESULTS_DIR / "pre_post_matchgpt_compare.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(compare, f, ensure_ascii=False, indent=2)

    print(f"\n三階段對比（供論文表 4-7）：")
    print(f"  {'指標':<25} {'Pre-val':>10} {'Post-val':>10} {'Post-MGT':>10}")
    print("  " + "-" * 57)
    for k, v in compare["metrics"].items():
        vals = list(v.values())
        def fmt(x): return str(x) if x is not None else "N/A"
        print(f"  {k:<25} {fmt(vals[0]):>10} {fmt(vals[1]):>10} {fmt(vals[2]):>10}")

    print(f"\n  Pre→Post 節點縮減：{compare['delta_pre_to_post']['node_reduction']} "
          f"（{compare['delta_pre_to_post']['node_reduction_pct']}%）")
    print(f"  Post→MatchGPT 節點縮減：{compare['delta_post_to_matchgpt']['node_reduction']} "
          f"（{compare['delta_post_to_matchgpt']['node_reduction_pct']}%），"
          f"合併 {compare['delta_post_to_matchgpt']['merged_pairs']} 對")

    print(f"\n  ✓ 對比表 → {out_path}")
    print("\n✅ 步驟 1.6 完成！Phase 1 全部結束。")


if __name__ == "__main__":
    main()
